# Learning guide: how TeamForge API works

Read this top to bottom, with the code open beside you. Every section names the file to look at.

## 0. The big picture

A client sends an HTTP request with a token. The app works out **who** you are (authentication), then
**which organization** you are acting in and **what you may do there** (authorization), then runs the
business rule and stores the result in PostgreSQL.

```
request -> router -> dependencies (who? which org? which role?) -> service (rules + DB) -> response
```

## 1. How FastAPI works

- `app/main.py` has `create_app()`, an *application factory*: it builds the app, installs middleware and
  error handlers, and registers routers. Tests build their own app from it.
- A **router function** (e.g. `app/api/routers/projects.py`) is an endpoint. FastAPI reads its type hints:
  path/query parameters, the Pydantic body model, and `Depends(...)` parameters.
- **Dependencies** are functions FastAPI runs *before* your endpoint and whose result it injects:
  `get_db` (a database session), `get_current_user`, `get_tenant_context`, `get_page_params`.
- **Pydantic** models (`app/schemas`) validate input and shape output. Bad input becomes a 422 before your
  code runs. `response_model` filters what leaves the API (that is why password hashes can't leak).
- Endpoints are plain `def`, so FastAPI runs them in a threadpool; blocking database calls are fine.
- `/docs` is generated automatically from these type hints.

## 2. How the database connects

- `app/core/config.py` reads settings from environment variables (and `.env` locally) using
  pydantic-settings, and builds the connection URL (escaping special characters in the password).
- `app/db/session.py` creates one **engine** (a connection pool) and a **session factory**.
- `get_db` gives each request its own **session** and closes it afterwards. Closing without committing rolls
  back, so a failed request leaves no half-written data.
- **Alembic** (`alembic/`) records schema changes as versioned migration files. The models describe what the
  schema *should* be; migrations are how a real database gets there. `alembic check` fails if they disagree.

## 3. How SQLAlchemy works

- A **model** (`app/models`) is a Python class mapped to a table; `Mapped[...]` type hints describe columns.
- `select(Task).where(Task.organization_id == org_id)` builds SQL with *bound parameters*, so user input is
  never pasted into SQL text (this is the SQL-injection defence).
- A **session** tracks objects you load or add. Changes are sent on `flush`/`commit`. One `commit()` = one
  transaction: all changes succeed or none do (see `create_organization`: organization + owner membership).
- Constraints in the model (unique, check, foreign keys) are enforced by PostgreSQL itself, not just Python.
- Native PostgreSQL enums sort by declaration order, which is why sorting by `priority` gives
  LOW < MEDIUM < HIGH < URGENT.

## 4. How JWT authentication works

Files: `app/core/security.py`, `app/api/deps.py`, `app/services/auth.py`.

1. **Register**: the password is hashed with **Argon2id** (slow and memory-hard on purpose, with a random
   salt) and only the hash is stored.
2. **Login**: look up the user, verify the password against the hash, then create a **JWT**: a signed JSON
   payload `{sub: user_id, iat, exp}`. Signing (HS256 with `JWT_SECRET_KEY`) makes it tamper-evident, not secret.
3. **Each request**: the client sends `Authorization: Bearer <token>`. The server checks the signature and
   expiry, requires the claims, then loads the user (so deleted/disabled users are rejected at once).

Security details worth being able to explain: the accepted algorithm list is fixed on the server (so
`alg: none` tricks fail); unknown users still cost a hash verification (timing); errors say "incorrect email
or password" without saying which; roles are deliberately **not** in the token.
*Authentication* = who are you. *Authorization* = what may you do. The token only answers the first.

## 5. How multi-tenancy is enforced

The tenant is the **organization**. Tenant-owned tables carry `organization_id` (shared schema).
Defence in depth, from outermost to innermost:

1. **URL carries the tenant**: `/organizations/{org_id}/...`.
2. **`get_tenant_context`** (`app/api/deps.py`) checks the caller has a membership in `{org_id}`. If not:
   **404**, identical to "organization doesn't exist", so existence isn't leaked.
3. **Every service query filters** `organization_id == ctx.organization_id`. A project id from another
   organization simply isn't found (e.g. `get_project` in `app/services/projects.py`).
4. **Composite foreign keys** (`app/models/project.py`): a task's `(project_id, organization_id)` must match a
   project row, and `(organization_id, assignee_id)` must match a membership row. Even a buggy query cannot
   create a cross-tenant link.

Layers 3 and 4 exist even though layer 2 is there, on purpose: each assumes the one outside it may fail.

## 6. How RBAC works

File: `app/core/permissions.py`.

- Three roles (`OWNER`, `ADMIN`, `MEMBER`) map to named **permissions** (`PROJECTS_WRITE`, `MEMBERS_MANAGE`, ...).
- `TenantContext` (user + org id + role) is passed into services. A service starts a write with
  `authorize(ctx, Permission.X)`, which raises 403 if the role lacks it.
- Authorization lives in services, not routers, so any future caller (a CLI, a background job) gets the same
  checks.
- Some rules need more than a role, e.g. "members delete only their own tasks", "only owners grant OWNER",
  "an organization always keeps at least one owner". These sit in the relevant service.
- **The last-owner rule and concurrency** (`app/services/members.py`): checking "is there another owner?"
  and then writing is a race if two requests run together. The fix is to lock the organization row
  (`SELECT ... FOR UPDATE`) first, then re-read the caller's role and count owners under the lock.

## 7. How API endpoints are structured

- Resources are nouns, HTTP methods are verbs: `GET` read, `POST` create/action, `PATCH` partial update,
  `PUT` replace a sub-resource (`/assignee`), `DELETE` remove.
- Status codes: 200 OK, 201 Created, 204 No Content, 400/422 bad input, 401 not authenticated, 403
  authenticated but not allowed, 404 not found (also used to hide other tenants), 409 conflict with current
  state (duplicate email, last owner, archived project).
- Lists use `limit`/`offset`, filters as query parameters, and `sort_by` limited to an enum allowlist.
- One error format everywhere (`app/core/errors.py`).
- Routers are thin: validate -> call service -> return. See `app/api/routers/tasks.py`.

## 8. How tests are organized

All under `tests/`, using **pytest** and FastAPI's `TestClient` (HTTP client: `httpx2`).

- `conftest.py` sets safe environment first, then a session fixture creates a throwaway
  `teamforge_test` database and applies the real migrations. After each test, tables are truncated.
- These are **integration tests**: real HTTP layer, real services, real PostgreSQL. The few pure **unit**
  tests cover things like the log redactor and settings validation.
- Helpers in `tests/helpers.py` create orgs/members through the real endpoints.
- Notable suites: the **authorization matrix** (every endpoint x every role), **tenant isolation**,
  **concurrency** (threads firing simultaneous requests), and **hostile input**.
- Good habit shown here: a test that can't fail proves nothing. The concurrency tests were checked by
  removing the lock and watching them fail.

Run: `docker compose up -d db && uv run pytest`.

## 9. How Docker works here

- **Image**: a recipe (`Dockerfile`). Stage 1 installs locked dependencies; stage 2 copies only the result and
  the app code into a small image and runs as a non-root user. `.dockerignore` keeps `.env` out of it.
- **Container**: a running image. **Volume**: storage that outlives containers (the database data).
- **Compose** (`docker-compose.yml`) wires services: `db` starts and becomes healthy -> `migrate` runs once
  and exits -> `api` starts. Configuration arrives through environment variables, never baked in.
- **Healthchecks** tell Docker (and orchestrators) whether a container is alive.
- **CI** (`.github/workflows/ci.yml`) repeats lint, migrations, tests, and an image build on every push.

## 10. Explaining this project in an interview

**Thirty-second pitch.** "TeamForge is a multi-tenant project-management API in FastAPI and PostgreSQL.
The hard part was tenant isolation: users can belong to several organizations, and one tenant must never see
or change another's data. I enforce that at four levels, and I tested it with a role-by-endpoint matrix and
real concurrent requests."

**Decisions you can defend**
- *Why a shared schema?* Cheapest to operate and migrate; I compensated for the leak risk with a
  membership gate, tenant-filtered queries and composite foreign keys.
- *Why sync SQLAlchemy?* Workload is CRUD against one database; sync is simpler to test and debug, and
  FastAPI runs it in a threadpool.
- *Why aren't roles in the JWT?* So demotion and removal take effect immediately.
- *Why 404 instead of 403?* Not confirming that other tenants' resources exist.
- *Why hash invitation tokens?* A database leak shouldn't hand out working invitations.

**Questions to rehearse**
1. Walk through a request to `PATCH /organizations/{id}/tasks/{task_id}`.
2. How could two requests leave an organization without an owner, and how did you prevent it?
3. What does a composite foreign key add if you already filter by `organization_id`?
4. Authentication vs authorization; where is each implemented?
5. How do you stop SQL injection when users choose sort fields and search text?
6. What happens to a JWT after the user is deleted or demoted?
7. Why `limit` is capped and what are the downsides of offset pagination?
8. What is a database transaction, and where does this app define its boundaries?
9. What is an index, and how did you check yours are useful?
10. Unit vs integration tests: what did you choose here and why?
11. How would you scale this to many instances? (stateless app; connection pools; PgBouncer; read replicas)
12. What would you add next? (rate limiting, refresh tokens, email, audit log, RLS)

**Be honest about limits.** It isn't deployed, it hasn't been load-tested, and there's no rate limiting or
email. Saying so confidently reads as
maturity, not weakness.

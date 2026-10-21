# API reference

Base path `/api/v1` (health probes are at the root). Interactive docs: `/docs` (Swagger UI) and
`/openapi.json`. Send `Authorization: Bearer <access_token>` on every endpoint except register, login and
health.

## Conventions

- **Errors** always look like `{"error": {"code": "...", "message": "...", "details": [...]}}`.
  Codes: `validation_error` (422), `unauthenticated` (401), `forbidden` (403), `not_found` (404),
  `conflict` (409), `unprocessable` (422), `bad_request` (400), `internal_error` (500).
  Validation `details` never echo the submitted values.
- **Pagination**: `limit` (1-100, default 20) and `offset` (>= 0). Lists return
  `{"items": [...], "total": n, "limit": n, "offset": n}`.
- **404 vs 403**: callers who are not members of an organization get 404 for everything under it.
- IDs are UUIDs. Timestamps are ISO-8601 UTC. Dates are `YYYY-MM-DD`.

## Endpoints

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/health` | anyone | liveness |
| GET | `/health/ready` | anyone | readiness (queries the database; 503 if down) |
| POST | `/auth/register` | anyone | 201; 409 if email exists; password 8-128 chars |
| POST | `/auth/login` | anyone | returns `access_token`, `token_type`, `expires_in`; 403 if account disabled |
| GET | `/users/me` | authenticated | current user |
| POST | `/organizations` | authenticated | caller becomes OWNER |
| GET | `/organizations` | authenticated | only organizations the caller belongs to, with their role |
| GET | `/organizations/{org_id}` | member | |
| PATCH | `/organizations/{org_id}` | owner, admin | rename |
| DELETE | `/organizations/{org_id}` | owner | cascades to all org data; 204 |
| GET | `/organizations/{org_id}/members` | member | paginated |
| PATCH | `/organizations/{org_id}/members/{user_id}` | owner, admin | `{"role"}`; only owners grant/revoke OWNER; 409 if it would remove the last owner |
| DELETE | `/organizations/{org_id}/members/{user_id}` | owner, admin, or the member themself | leaving allowed; admins cannot remove owners; 409 for the last owner; unassigns their tasks |
| POST | `/organizations/{org_id}/invitations` | owner, admin | `{"email","role": ADMIN\|MEMBER}`; replaces a pending invite for the same email |
| GET | `/organizations/{org_id}/invitations` | owner, admin | pending invitations (never shows tokens) |
| DELETE | `/organizations/{org_id}/invitations/{invitation_id}` | owner, admin | revoke |
| POST | `/invitations/accept` | authenticated | `{"token"}`; account email must match the invitation |
| POST | `/organizations/{org_id}/projects` | owner, admin | |
| GET | `/organizations/{org_id}/projects` | member | `include_archived`, `q`, `sort_by` (created_at, updated_at, name), `order` |
| GET | `/organizations/{org_id}/projects/{project_id}` | member | |
| PATCH | `/organizations/{org_id}/projects/{project_id}` | owner, admin | 409 if archived |
| POST | `/organizations/{org_id}/projects/{project_id}/archive` | owner, admin | idempotent |
| POST | `/organizations/{org_id}/projects/{project_id}/unarchive` | owner, admin | idempotent |
| POST | `/organizations/{org_id}/tasks` | any member | 404 unknown project; 409 archived project; 422 invalid assignee |
| GET | `/organizations/{org_id}/tasks` | member | filters below |
| GET | `/organizations/{org_id}/tasks/{task_id}` | member | |
| PATCH | `/organizations/{org_id}/tasks/{task_id}` | any member | partial; `description`, `assignee_id`, `due_date` may be `null` |
| PUT | `/organizations/{org_id}/tasks/{task_id}/assignee` | any member | `{"assignee_id": uuid\|null}` |
| DELETE | `/organizations/{org_id}/tasks/{task_id}` | owner/admin: any; member: own tasks | 204 |

## Task list filters

| Parameter | Meaning |
|---|---|
| `status` | repeatable: `?status=TODO&status=IN_PROGRESS` |
| `priority` | repeatable |
| `project_id`, `assignee_id` | exact match (another tenant's id simply matches nothing) |
| `unassigned=true` | no assignee (cannot combine with `assignee_id`) |
| `due_after`, `due_before` | inclusive date range; tasks without a due date never match |
| `q` | title contains (case-insensitive, wildcards escaped), 1-100 chars |
| `sort_by` | `created_at` (default), `updated_at`, `due_date`, `priority`, `status`, `title` |
| `order` | `desc` (default) or `asc`; missing due dates always sort last |
| `limit`, `offset` | pagination |

Any value outside these allowlists returns 422.

## Authentication

1. `POST /auth/register`, then `POST /auth/login` with email and password.
2. Send the returned `access_token` as a bearer token. Tokens are HS256 JWTs with `sub` (user id), `iat`,
   `exp` (default 30 minutes, `ACCESS_TOKEN_EXPIRE_MINUTES`).
3. Expired, tampered, wrongly signed, `alg: none`, claim-less, or deleted/disabled-user tokens return 401.

## Roles

| Capability | Owner | Admin | Member |
|---|---|---|---|
| Read org, members, projects, tasks | yes | yes | yes |
| Create/update tasks, assign | yes | yes | yes |
| Delete tasks | any | any | own only |
| Create/update/archive projects | yes | yes | no |
| Invite/revoke, change roles, remove members | yes | yes (not owners, cannot grant OWNER) | no |
| Rename organization | yes | yes | no |
| Delete organization | yes | no | no |

This table is enforced by `app/core/permissions.py` and checked exhaustively by
`tests/test_authorization_matrix.py`.

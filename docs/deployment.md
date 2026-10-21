# Deployment guide

**Status: not deployed.** The Docker image and Compose stack were built and run locally; nothing here has
been exercised on a cloud provider. Treat this as a checklist, not a verified runbook.

## What exists

- `Dockerfile`: multi-stage, locked production dependencies, non-root user (uid 10001), HTTP healthcheck.
- `docker-compose.yml`: `db` (Postgres 17) -> `migrate` (one-shot `alembic upgrade head`) -> `api`.
- `.github/workflows/ci.yml`: lint, format check, migrations + drift check, tests on Postgres 17, image build
  and Compose smoke test. (Written but not yet run on GitHub.)

## Environment variables

| Variable | Notes |
|---|---|
| `APP_ENV` | set to `production` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT` | managed database credentials |
| `JWT_SECRET_KEY` | `openssl rand -hex 32`; rotating it logs everyone out |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | default 30 |
| `INVITATION_EXPIRE_HOURS` | default 72 |
| `EXPOSE_INVITATION_TOKENS` | must stay `false` in production (startup fails otherwise) |
| `ENABLE_API_DOCS` | consider `false` for public deployments |
| `LOG_LEVEL` | default `INFO` |

Inject these through the platform's secret store; never commit `.env`.

## Suggested path

1. Provision a managed PostgreSQL 17 database with backups and TLS.
2. Build and push the image from CI to a registry.
3. Run `alembic upgrade head` as a release step (the Compose `migrate` job shows the pattern) before
   starting new app instances.
4. Run the container behind a TLS-terminating reverse proxy/load balancer. Add request-size limits, rate
   limiting, and, if the proxy sets forwarded headers, configure uvicorn `--proxy-headers`
   with the proxy's address in `--forwarded-allow-ips`.
5. Use `/health` for liveness and `/health/ready` for readiness checks.
6. Ship the JSON logs (stdout) to your log platform.

## Scaling notes (reasoning, not measurements)

The app is stateless (JWT, no server-side sessions), so more instances can run behind a load balancer. The
database is the shared bottleneck: each instance has its own connection pool (SQLAlchemy defaults: 5 + 10
overflow), so size `instances x pool` below Postgres `max_connections`, or add PgBouncer. Ownership changes
serialise per organization by design; other tenants are unaffected.

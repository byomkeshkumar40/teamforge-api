# Security design

What is implemented, where, and how it is tested. This is a learning/portfolio project: it has not had an
external security review or penetration test.

## Threats considered and mitigations

| Threat | Mitigation | Test |
|---|---|---|
| Cross-tenant read/write/update/delete | membership gate (404), tenant-filtered queries, composite FKs | `test_tenant_isolation.py`, per-resource isolation tests, `test_authorization_matrix.py` |
| Privilege escalation inside an org | permission checks in every service; only owners grant OWNER | `test_members_rbac.py` |
| Orphaned organization (no owner), including races | org-row `FOR UPDATE` lock, role re-read after lock | `test_concurrency.py` (verified to fail without the lock) |
| Password theft from database | Argon2id hashes only | `test_auth.py` |
| User enumeration at login | identical error and equalised hashing cost for unknown user vs wrong password | `test_auth.py` |
| JWT forgery/misuse | fixed `HS256` allowlist, required `exp`/`iat`/`sub`, secret >= 32 chars | `test_auth.py` (alg none, other alg, wrong key, tampering, missing claims, expiry) |
| Stale authorization after demotion/removal | roles read per request, not in token | `test_members_rbac.py` |
| Invitation token theft/replay | 256-bit random token, SHA-256 digest stored, expiry, single use, email-bound, generic failures, never logged | `test_invitations.py` |
| SQL injection | SQLAlchemy bound parameters; sort fields come from enums; `LIKE` wildcards escaped | `test_security.py`, `test_projects.py`, `test_task_filters.py` |
| Mass assignment | request schemas expose only intended fields; org id comes from the URL/context | `test_security.py` |
| Malformed input crashing the DB | length limits; NUL bytes rejected (found and fixed during hardening) | `test_security.py` |
| Secrets in logs/responses | redacting JSON formatter; validation errors drop `input`; password hash never serialised | `test_foundation.py`, `test_auth.py`, `test_security.py` |
| Information leakage via errors | generic 500 body; foreign vs nonexistent org responses identical | `test_security.py`, `test_tenant_isolation.py` |
| Production misconfiguration | startup refuses `EXPOSE_INVITATION_TOKENS=true` with `APP_ENV=production`; short JWT secrets rejected | `test_foundation.py` |

## Invitation tokens in development

Email is not implemented. When `EXPOSE_INVITATION_TOKENS=true` (and `APP_ENV` is not `production`), the
raw token is returned once in the response that creates the invitation. It is never stored, listed or
logged. In any real deployment leave the flag off and deliver tokens through a mail integration.

## Known gaps

No rate limiting or lockout, no refresh tokens or revocation list, no MFA/email verification/password
reset, no CORS configuration (the API is not meant for direct browser calls from other origins yet),
no request-size limit beyond field limits (put one at the reverse proxy), no audit table. Dependency
vulnerability scanning is not automated. HTTPS termination is assumed to happen in front of the app.

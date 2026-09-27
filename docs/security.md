# Local authentication and authorization

## First administrator

Apply migrations through `0011_auth`. Run `docker compose exec api python -m app.bootstrap`, or
`python -m app.bootstrap` from the installed native Python environment. Enter a username and password
at the prompts; the password is not echoed. Bootstrap is a local administrative operation, not a public
API endpoint. It only creates an enabled ADMIN when **no users exist**, under a PostgreSQL transaction
lock. Restarting the API does not create/reset accounts. No credentials are shipped or seeded.

Usernames are normalized to lowercase and use a conservative 3?64 character ASCII identifier.
New passwords must be non-empty and at most 128 characters and are hashed using Argon2id (64 MiB, 3 iterations,
parallelism 2, random salt). Hashes and passwords never appear in API responses or audit details.
Protect database backups because they contain password hashes and application configuration.

## Session and browser flow

`POST /api/auth/login` accepts username/password and returns safe user information. It sets:

- `mm_session`: random 256-bit opaque token, HttpOnly, SameSite=Strict, Path=/.
- `mm_csrf`: a separate random CSRF token readable by the frontend, SameSite=Strict, Path=/.

Only token digests are persisted. No auth tokens are placed in localStorage, URLs or frontend source.
Unsafe authenticated HTTP requests must send `X-CSRF-Token` matching the session, and supplied Origin
must be allowed. Login also checks Origin/fetch metadata. Use the same-origin frontend API proxy;
cross-site embedding is intentionally unsupported. Non-browser clients must maintain both cookies and
send the CSRF header on mutations. API docs are public schemas, not an authorization bypass.
Health and database-health endpoints remain public for Compose readiness; all application data APIs
require login. `/api/auth/me` returns ID, username, role and permissions only.

`AUTH_SESSION_HOURS=8` is an absolute expiry, not extended by activity. At most 10 sessions per account
are retained. `POST /api/auth/logout` revokes the current session and clears cookies.
`POST /api/auth/password` requires current_password and password, revokes all account sessions,
and requires signing in again. Account edits and admin password resets revoke all sessions as well.
The frontend checks `/me` periodically, clears live data on HTTP 401/session loss, and returns to Login.

`AUTH_COOKIE_SECURE=false` supports localhost HTTP development. For deployment behind TLS, set it to
`true`, serve both UI and API through HTTPS and configure trusted origins/proxy handling explicitly.
The project still uses Vite for development hosting; authentication is not a substitute for TLS or
network isolation. Do not put secrets into URLs, shell history, tracked files or request-body logs.

## Login protection

Generic invalid-login responses cover unknown users, wrong passwords and disabled accounts.
Unknown users perform dummy password verification. PostgreSQL tracks bounded failed-login windows
by hashed remote IP and normalized username. Defaults: `AUTH_LOGIN_ATTEMPTS=10`,
`AUTH_LOGIN_WINDOW_SECONDS=900`. Rate-limited attempts return HTTP 429 with Retry-After.
Forwarded IP headers are not blindly trusted; behind a proxy this can share an IP budget among users.
Expired buckets are cleaned up on login; no Redis is required. Failed-login audit records omit attempted
credentials. Successful logins record the resolved user and update last_login_at.

## Built-in roles

| Operation | ADMIN | OPERATOR | VIEWER |
|---|---|---|---|
| Dashboards, telemetry, history, devices/tags/status, Commands | Yes | Yes | Yes |
| View Automation and Alarm rules/events | Yes | Yes | Yes |
| Request/cancel manual Commands | Yes | Yes | No |
| Acknowledge active alarms | Yes | Yes | No |
| Change Connections/Devices/Tags/Locations/Dashboards/rules | Yes | No | No |
| Transport tests, USB discovery/redetection, notification settings/tests | Yes | No | No |
| Users, password resets, Audit | Yes | No | No |
| Change own password/logout | Yes | Yes | Yes |

The backend is authoritative; hidden buttons are UX only. Controls on dashboards use exactly the same
command endpoint and permission checks as Tag details. Existing writable/enable/source/version/master
write-enable and read-back safety remain in force. No physical writes occur in authorization tests.

User endpoints: `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}` and
`POST /api/users/{id}/password` (password). Only ADMIN may use them. Self reset uses the own-password
flow instead. A shared transaction lock prevents concurrent removal of all enabled administrators.
Removing a user never erases retained Commands, alarm events or audit entries.

## Attribution and audit

Manual Commands record requested_by plus a username snapshot. Automation uses source=automation with
no fictitious human; execution never depends on whether the requesting user's session is still active.
Alarm acknowledgements store acknowledged_by, username and acknowledged_at. Old records may have no
human attribution. User deletion nulls foreign keys while preserving historical names.

Audit records cover login success/failure, logout/password changes, user mutations/reset, manual command
requests, alarm acknowledgement, Automation/Alarm changes and other configuration mutations.
API mutations and their audit record commit atomically. Summaries use action/path/entity metadata and
allowlisted user role/enabled changes, never request bodies, passwords, tokens or Telegram secrets.
`GET /api/audit` is ADMIN-only: user_id, action, from, to, limit (max 500), offset. Dates require explicit
UTC offsets. The Audit UI displays browser-local time and offers filters/pagination; no edit/delete API.
Audit retention is not implemented in this phase.

## WebSocket and worker isolation

`/api/ws/live` requires a valid session cookie and allowed Origin before accepting. The API revalidates
sessions every second and checks expiry before sending events. Disabled/revoked sessions close with
4401; clients return to Login and clear shared state. Clients reconnect with a new REST snapshot as before.

Workers use their existing database lease and internal services, not browser authentication. Telemetry,
history, Automation, alarm evaluation and Telegram continue without any logged-in user. Automation
only enqueues the existing persistent commands. This phase does not change transport or write behavior.

## Verification

`tests/test_auth.py` covers cookies/hash/expiry/CSRF, role enforcement, user mutations, last ADMIN,
command/alarm attribution, secret-free audit and WebSocket denial. The existing API tests authenticate
normally; there is no test-only authorization bypass in application code.
`tests/compose_auth_smoke.py` boots an isolated PostgreSQL/API/worker/frontend stack, creates all three
roles, verifies browser/mobile behavior and simulator control, then removes its fixtures and volume.
Other Compose regression scripts bootstrap their own isolated ADMIN and use cookies too.

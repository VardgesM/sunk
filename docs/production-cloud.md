# First production Cloud deployment ? Phase 11.1

These instructions prepare a later deployment. No real VPS, firewall, domain or physical
write was changed during implementation. Use the dedicated production file **by itself**;
`docker-compose.cloud.yml` remains a development override and is not the production stack.

## Topology and services

Ubuntu VPS: PostgreSQL, FastAPI Cloud API, and `frontend` (compiled React files served by
Caddy, also the reverse proxy). `migrate` is a one-shot preflight/Alembic job, not a worker.
There is no Modbus, serial discovery, simulator, Automation worker or outgoing sync client
on Cloud. Incoming sync endpoints are part of the API. API/Caddy run as non-root users.
The deployment user needs Docker access; Docker-group membership is privileged, but the
application does not require a root shell.

Edge PC retains its database, physical worker, Automation, local Commands/Alarms and sync
client. Edge initiates outbound HTTPS. Cloud loss does not block local collection/control.
Queued outbox records survive and retry after connectivity returns. See [sync semantics](edge-cloud.md).

| Component | Internal port | Published host port |
| --- | --- | --- |
| Caddy HTTP | 8080 | 80 TCP |
| Caddy HTTPS | 8443 | 443 TCP |
| Caddy health | 8090 | none |
| FastAPI | 8000 | none |
| PostgreSQL | 5432 | none |

Database and API backend networks are Docker `internal` networks. Only Caddy has an
Internet-facing network for browsers and automatic certificate acquisition. No Docker
socket is mounted. Forwarded headers are trusted by Uvicorn only because API has no public
port and only the private proxy network reaches it. Do not publish port 8000 later without
also revisiting that trust boundary. Caddy replaces upstream forwarding information; do not
add an untrusted CDN/proxy without configuring its trust model.

Persistent volumes: `cloud_postgres` (database), `caddy_data` (certificates/private keys),
`caddy_config` (Caddy state), prefixed by the Compose project name. Keep the project name
stable. `stop`, `restart` and ordinary `down` preserve volumes; **never use `down -v` on production**.
Caddy's filesystem is read-only apart from its volumes. Container logs rotate at 3 ? 10 MB.

## Environment

Copy `.env.cloud.example` to `.env.cloud` and protect it with `chmod 600`.
Both real `.env.cloud` and `.env.edge` are Git-ignored; only example templates are tracked.
Never use `docker compose config` without `--quiet` in shared logs: rendered config contains
credentials. Do not send database backups or Caddy volumes to Git.

| Variable | Purpose |
| --- | --- |
| `APP_MODE=cloud` | Canonical mode. Production Compose forces cloud; never merge Edge overrides. |
| `CLOUD_HOST` | Domain only, e.g. `monitor.example.com`, or test IPv4 address; no scheme/path/port. |
| `CLOUD_SCHEME` | `https` normally; `http` for temporary IP testing only. |
| `CLOUD_PUBLIC_URL` | Exact browser origin, e.g. `https://monitor.example.com`, without trailing slash. |
| `POSTGRES_DB`, `POSTGRES_USER` | Cloud-local database identifiers. |
| `POSTGRES_PASSWORD` | Required unique random database secret; no default. |
| `AUTH_COOKIE_SECURE` | `true` for HTTPS; explicitly `false` for HTTP test mode. |
| `AUTH_SESSION_HOURS` | Session lifetime, default 8 hours. |
| `AUTH_LOGIN_ATTEMPTS`, `AUTH_LOGIN_WINDOW_SECONDS` | Existing bounded login protection. |
| `MODBUS_WRITES_ENABLED` | Keep `false`; Cloud rejects physical remote requests even if Edge can write. |
| `REMOTE_COMMAND_MAX_AGE_SECONDS` | Remote delivery expiry, default 60 seconds. |
| `LOG_LEVEL` | Default INFO. |
| `CLOUD_BIND_ADDRESS` | Default 0.0.0.0; use 127.0.0.1 for SSH-tunnel-only HTTP testing. |
| `CLOUD_HTTP_PORT`, `CLOUD_HTTPS_PORT` | Defaults 80/443; random ports are supported for isolated tests. |

Compose derives `ALLOWED_HOSTS` from the domain plus localhost for health checks and
`CORS_ORIGINS` from the exact public origin. Do not use wildcard CORS/hosts. React uses
`/api` and `/api/ws/live` on the browser origin; HTTPS automatically uses WSS. There is no
localhost URL compiled into the production bundle and no separate frontend API secret.

No new application/session signing key is needed: existing authentication uses random opaque
session tokens, hashes stored in PostgreSQL, Argon2id passwords and CSRF tokens. Bootstrap
remains interactive; no `INITIAL_ADMIN_PASSWORD` environment variable is introduced.
Cloud does not need Telegram credentials; Telegram execution remains on Edge. Machine
registration secrets are distinct from human credentials and never synchronized with users.

## Initial deployment (later, on the VPS)

Prerequisites: Ubuntu deployment user with Docker Engine + Compose v2 and Git; 80/443
available; database backup plan. A server administrator may need to grant ownership of the
project directory once. This does not run the application as root.

```sh
sudo install -d -o "$USER" -g "$(id -gn)" /opt/modbus-monitor
cd /opt/modbus-monitor
git clone https://github.com/VardgesM/sunk.git .
umask 077
cp .env.cloud.example .env.cloud
chmod 600 .env.cloud
nano .env.cloud
```

Set a unique random database password in the file, and choose the HTTP or HTTPS values
below. Do not paste actual credentials into shell command arguments or this documentation.
Define this helper in the current shell (repeat after reconnecting):

```sh
cd /opt/modbus-monitor
dc() { docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml "$@"; }
dc config --quiet
dc build --pull
dc up -d --wait postgres
dc run --rm migrate
dc up -d --wait api frontend
dc exec api python -m app.bootstrap
```

The migration job validates mode/host/origin/cookies, then upgrades through
`0012_edge_cloud`. No Phase 11.1 database migration is required. It has `restart: "no"`;
a failed preflight/migration blocks API startup rather than disappearing in a restart loop.
The same migration gate may run idempotently during `up`. Bootstrap prompts for username
and password without echoing the password, and refuses if any user already exists.
Choose a strong production password even though the application permits short passwords.

## Initial IP testing versus final HTTPS

Temporary IP test:

```dotenv
CLOUD_HOST=203.0.113.10
CLOUD_SCHEME=http
CLOUD_PUBLIC_URL=http://203.0.113.10
AUTH_COOKIE_SECURE=false
MODBUS_WRITES_ENABLED=false
```

The IP above is a documentation example, not a real VPS address. Explicit `http://` disables
Caddy certificate requests. HTTP carries credentials in plaintext: prefer an SSH tunnel and
`CLOUD_BIND_ADDRESS=127.0.0.1`; do not enroll the real Edge machine secret across public HTTP.
For an SSH tunnel, use `CLOUD_HOST=localhost`, `CLOUD_PUBLIC_URL=http://localhost:8080`
and connect with `ssh -L 8080:127.0.0.1:80 deployment-user@VPS`. This is a later operator action,
not something performed by this task. Edge sync still requires HTTPS by default.

Final domain configuration:

```dotenv
CLOUD_HOST=monitor.example.com
CLOUD_SCHEME=https
CLOUD_PUBLIC_URL=https://monitor.example.com
AUTH_COOKIE_SECURE=true
MODBUS_WRITES_ENABLED=false
```

Before switching, point the real domain's A/AAAA records to the VPS and ensure both published
ports are reachable. Remove stale AAAA records rather than leaving broken IPv6 routing.
Caddy obtains/renews public certificates and redirects HTTP to HTTPS. Do not delete its data
volume on updates. Change env, run `dc run --rm migrate`, then `dc up -d --force-recreate api frontend`.
Existing HTTP sessions may need a new login; rotate any credentials exposed during HTTP testing.
Public certificate issuance cannot be verified without the real domain and was not attempted.

## Cookies, CORS and reverse proxy

Session cookie: Secure on HTTPS, HttpOnly, SameSite=Strict, Path=/, host-only (no Domain).
The CSRF cookie is intentionally readable by JavaScript; mutation requests include the
existing X-CSRF-Token header. Cross-site origins are rejected. CORS permits exactly the public
origin. WebSocket requires both the existing authenticated session and an allowed Origin;
session expiry/revocation disconnects it. Caddy supports the upgrade automatically. API paths
are not stripped; unknown API routes never fall back to index.html. SPA routes do fall back
to index.html. Static assets and API responses do not expose runtime secrets.

Caddy uses high internal ports to run non-root; its `http_port`/`https_port` options do not
change the normal public 80/443 addresses. References:
[Caddy options](https://caddyserver.com/docs/caddyfile/options),
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https),
[Uvicorn proxy settings](https://www.uvicorn.org/settings/).

## Operations

```sh
dc up -d --wait                 # start; migration gate must pass
dc stop                        # stop, retain data
dc restart api frontend        # process restart; does NOT apply env/image changes
dc ps -a
dc logs --tail=100 api frontend migrate
dc logs --tail=100 postgres
dc exec api alembic current
dc exec api alembic check
```

Restart policies are `unless-stopped` for long-running services. After a VPS/Docker reboot
containers recover using existing volumes. Health checks report PostgreSQL reachability,
API database health and Caddy liveness; health alone does not prove Edge telemetry is fresh.
A deliberately stopped container remains stopped. Inspect failures rather than repeatedly
restarting migrations. Do not scale the local worker as part of a Cloud operation.

### Backups and updates

Run these in Bash on the VPS, with the helper above. Backup files contain sensitive data:

```sh
umask 077
mkdir -p backups
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/cloud-$(date -u +%Y%m%dT%H%M%SZ).dump"
git pull --ff-only
dc build --pull
dc stop frontend api
dc run --rm migrate
dc up -d --wait api frontend
dc exec api alembic current
dc exec api alembic check
```

Check the exit status of backup and migration before continuing. If migration fails, leave
API stopped, inspect logs and fix the cause; do not use a destructive downgrade as a generic
rollback. Keep off-host backups and test restoring into a separate database. Back up
`.env.cloud` and certificate volumes securely as well. Image/runtime dependency updates are
resolved at build time with current project constraints; record the tested image digests
and Git commit for rollback/reproducibility rather than assuming a rebuild is identical.

## Diagnostics

```sh
curl --fail https://monitor.example.com/api/health
curl --fail https://monitor.example.com/api/health/db
dc exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
dc exec api python -c 'from app.core.config import Settings; s=Settings(); print(s.application_mode, s.source_mode, s.modbus_writes_enabled)'
dc exec frontend caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Expected settings: `cloud disabled False`. Only `frontend` has published ports in `dc ps`.
Log in via the browser; `/api/auth/me` reports `application_mode=cloud`. DevTools Network
should show a 101 WebSocket upgrade at `/api/ws/live`, then ready/heartbeat/events. An
unauthenticated socket is rejected. `/api/sync/status` in the authenticated session and
Settings/System show Edge ONLINE and last-seen time. An unauthenticated POST to the machine
heartbeat endpoint must return 401, not accept anonymous data. Never put a token in a URL.
Cloud health does not imply an Edge is connected; inspect both statuses.

## Connect the existing Edge PC (later)

1. Back up the local database and environment. Update the checkout and apply the migration
   through 0012 if not already applied. Keep its existing database volume, credentials,
   device/Tag configuration, serial settings and project name. Do not load example devices.
2. If already in Edge mode, reuse the UUID shown in Settings/System. Otherwise create one
   once with `python -c "import uuid; print(uuid.uuid4())"`, and save it as
   `EDGE_INSTALLATION_ID`. Never generate a different ID on every restart.
3. Generate a random token locally (e.g. a password manager, or Python secrets.token_urlsafe(48));
   store it privately, not in Git/logs or CLI command arguments. On Cloud, ADMIN opens
   Settings/System and registers the UUID, name and token over HTTPS. Cloud stores its digest.
4. Merge `.env.edge.example` into the EXISTING local `.env`; do not replace the file:

   ```dotenv
   APP_MODE=edge
   EDGE_INSTALLATION_ID=<the-stable-UUID>
   SYNC_CLOUD_URL=https://monitor.example.com/
   SYNC_TOKEN=<the-machine-token>
   SYNC_ALLOW_INSECURE_HTTP=false
   SYNC_INTERVAL_SECONDS=2
   SYNC_BATCH_SIZE=100
   SYNC_TIMEOUT_SECONDS=10
   SYNC_BACKOFF_MAX_SECONDS=60
   TELEMETRY_SOURCE=modbus
   SIMULATOR_ENABLED=false
   MODBUS_WRITES_ENABLED=false
   ```

   `APP_MODE` takes precedence over legacy `APPLICATION_MODE`; remove a conflicting legacy
   setting to avoid confusion. Native worker and native sync connect to LOCAL PostgreSQL,
   typically `POSTGRES_HOST=127.0.0.1`, never to the VPS PostgreSQL. Docker services use their
   internal `postgres` hostname. Preserve the configured database port/name/user/password.
5. For the existing Windows-native RTU workflow, stop the old worker cleanly during the
   planned update; never start a second worker on the same DB. Start only local infrastructure:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.edge.yml up -d --build postgres api frontend
   .\.venv\Scripts\python.exe -m app.worker
   ```

   In a second terminal with the same Edge environment:

   ```powershell
   .\.venv\Scripts\python.exe -m app.sync
   ```

   Alternatively run only sync in Docker using `docker compose -f docker-compose.yml -f docker-compose.edge.yml --profile edge up -d --build sync`.
   Do not also run native sync. If the existing worker is containerized on Linux, use the
   existing serial-device override and `--profile edge up -d --build`; do not change its ports.
   Use the existing Windows process supervisor/startup setup for native worker/sync persistence;
   a shell window alone does not survive a PC reboot.
6. Verify LOCAL Tags still update from modbus_rtu/modbus_tcp, then local System shows sync
   progress, Cloud System shows ONLINE, and mirrored Dashboard/Tags/history/Alarms appear.
   Verify Cloud current values are not simulated. On a controlled Cloud outage, inspect
   increasing local pending count and continued local telemetry; recovery should drain it.
7. Keep `MODBUS_WRITES_ENABLED=false` on both Cloud and Edge for first commissioning.
   Cloud now checks its own flag before creating a physical remote request, and Edge retains
   all execution-time checks. This also disables local physical writes while false on Edge;
   Automation can evaluate but cannot actuate. Simulator commands remain development-only.
   Enabling one physical relay is a separate explicitly authorized later test, with both
   flags, confirmation, frozen target configuration, expiry and read-back intact.

### Rotate or revoke a machine credential

Cloud ADMIN re-registers the same installation UUID with a new token, then updates only
Edge `SYNC_TOKEN` and restarts the sync process. Local polling/Automation need not stop.
Old-token requests fail immediately. The existing ADMIN POST `/api/sync/installations`
also accepts `enabled=false` (with the normal authenticated session + CSRF); use it to
revoke installation access. The System registration form enables an installation, so API
revocation is required for disabling in this phase. Never substitute an Admin password.
Users/password hashes never synchronize. Queue expiry prevents an old undelivered command
executing much later; uncertain delivered execution follows existing no-replay behavior.

## Local verification

`tests/compose_production_smoke.py` starts an isolated project, checks private ports/cloud-only
services, HTTP, trusted-host/origin rejection, upgrades to TLS with a temporary local CA,
verifies Secure cookies, authenticated WSS, real static React browser login and machine
heartbeat, then removes its own volumes. It does not contact a VPS or public ACME service.
Existing Phase 11 integration tests cover store-and-forward and simulator remote control.

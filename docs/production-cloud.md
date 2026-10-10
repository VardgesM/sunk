# Production Cloud behind an independent shared gateway

Read the [gateway migration and rollback runbook](gateway.md) before upgrading an existing
installation that embeds Caddy in its frontend. This is a one-time operator migration;
ordinary application updates must never manage the gateway.

## Topology

- `/opt/gateway`: independent `gateway` Compose project; Caddy, TLS renewal, public TCP 80/443.
- `/opt/modbus-monitor`: `modbus-cloud` project; PostgreSQL, API, static React/nginx, one-shot
  preflight/Alembic migration gate. No worker, simulator, Automation execution or outgoing sync.
- External `web` network connects Caddy to uniquely aliased API/frontend. PostgreSQL and
  migrations use only an internal `database` network. Application services publish no ports.
- API trusts forwarded headers only from the configured gateway IP. No Docker socket mounts.
- Edge keeps its local worker, database, Automation, Commands, Alarms and outbound sync.

| Service | Internal port | Public port |
| --- | --- | --- |
| Shared Caddy | 8080 / 8443 | TCP 80 / 443 |
| Caddy health | 8090 | none |
| Static nginx | 8080 | none |
| API | 8000 | none |
| PostgreSQL | 5432 | none |

Application volumes: `cloud_postgres`, `cloud_backups`, `cloud_updates`, with the existing
project prefix. Gateway certificate/config volumes are external and operator-managed;
existing production volume names are discovered and reused. Never delete volumes during
updates. No database migration is added by gateway separation; head remains `0014_backups`.

## Environment and authentication

Copy `.env.cloud.example` to `.env.cloud` (600). Set the database credentials, existing
`CLOUD_HOST`, `CLOUD_SCHEME=https`, exact `CLOUD_PUBLIC_URL`, `AUTH_COOKIE_SECURE=true`.
Preserve existing values when migrating. `GATEWAY_NETWORK` defaults to `web` and
`GATEWAY_IPV4` to `172.30.50.2`; match the gateway configuration and reserve that address
outside the network's dynamic pool. Set these explicitly if that subnet conflicts.
`MODBUS_API_ALIAS` / `MODBUS_FRONTEND_ALIAS` default to `modbus-api` / `modbus-frontend`.

The gateway has its own `.env` containing hostname, ports, upstream names and inspected
certificate volume names, **not** the application's credentials. Public port settings now
belong there (`GATEWAY_BIND_ADDRESS`, `GATEWAY_HTTP_PORT`, `GATEWAY_HTTPS_PORT`).

Exact allowed hosts and CORS are derived from the existing public origin. Browser requests
remain `/api` and `/api/ws/live` (WSS on HTTPS); nginx embeds no environment secrets.
Session cookies remain Secure/HttpOnly/SameSite=Strict/Path=/ and host-only. CSRF and machine
authentication are unchanged. Bootstrap remains interactive: no password in CLI arguments.
Cloud has no Telegram token. Human users/password hashes never synchronize.

## Fresh deployment

Use an ordinary deployment user with Docker access. Docker group membership is privileged;
application containers remain non-root. Prepare `/opt/gateway` and external network/volumes
using [the gateway instructions](../deploy/gateway/README.md). Do not create empty certificate
volumes as a substitute for an existing installation's volumes.

```bash
cd /opt
git clone https://github.com/VardgesM/sunk.git modbus-monitor
cd /opt/modbus-monitor
umask 077
cp .env.cloud.example .env.cloud
chmod 600 .env.cloud
nano .env.cloud
app() { docker compose --project-name modbus-cloud --env-file .env.cloud -f docker-compose.cloud.production.yml "$@"; }
app config --quiet
app build
app up -d --wait postgres
app run --rm migrate
app up -d --wait api frontend
app exec api python -m app.bootstrap
cd /opt/gateway
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --wait
```

Do not print rendered Compose configuration: it contains database secrets. API only starts
after preflight and migration succeed. For an existing database, bootstrap refuses to replace
users. All original environment/write settings must be retained; first commissioning is read-only.

## Source permissions

Keep `umask 077` for secrets. Source permission normalization happens inside the server image;
nginx config is copied with mode 644 and runtime assets owned by UID 101. Gateway runs UID 1000,
matching the original Caddy certificate owner. Its bind-mounted non-secret Caddyfile needs mode
644. No recursive chmod of the checkout or secret files is required. Regression coverage:
`python tests/docker_permissions_smoke.py` on an isolated Docker host.

## HTTP tests and HTTPS production

For a temporary localhost/SSH-tunnel test only: gateway `MODBUS_SCHEME=http`, application
`CLOUD_SCHEME=http`, exact `CLOUD_PUBLIC_URL=http://localhost:PORT`, `AUTH_COOKIE_SECURE=false`.
Bind gateway to 127.0.0.1. Never send real passwords or Edge credentials over public HTTP.
For production preserve the current hostname, HTTPS, valid DNS and Secure cookies. Caddy
renews certificates in its independent volumes. Do not change the Edge Cloud URL when
separating the gateway. Smoke tests use a temporary local CA, never public ACME.

## Operations, backup and updates

```bash
cd /opt/modbus-monitor
app() { docker compose --project-name modbus-cloud --env-file .env.cloud -f docker-compose.cloud.production.yml "$@"; }
app ps -a
app logs --tail=100 api frontend migrate
app restart api frontend                 # gateway and database stay running
app exec api alembic current
app exec api alembic check
# Before source updates: create/download an encrypted Phase 12 full backup as ADMIN.
git pull --ff-only
app build
app stop api frontend
app run --rm migrate                    # only for a release requiring migrations
app up -d --wait api frontend
```

For application updater deployments, use the active retained-image override recorded by the
host runner; see [Updater](update.md). Never overwrite a working updater-managed deployment
with an old checkout build. Updater verifies public routing but does not manage gateway.

Independent gateway operations:

```bash
cd /opt/gateway
docker compose --env-file .env ps
docker compose --env-file .env exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file .env restart caddy   # affects all hosted sites, not PostgreSQL
```

Keep encrypted application backups and their passphrases separately, off-host. Preserve
`.env.cloud` and independent gateway config/certificate volumes securely. Restart policies
recover containers after reboot; a failed migration requires investigation, not blind restarts.

## Verification

```bash
curl --fail https://CURRENT_HOST/api/health
curl --fail https://CURRENT_HOST/api/health/db
cd /opt/modbus-monitor
app exec api python -m app.update_health
app exec frontend nginx -t
docker ps
docker network inspect web
```

Only gateway publishes 80/443. Verify browser login, SPA refresh, authenticated WebSocket,
Diagnostics, Backup/Restore, Updates and Edge ONLINE with advancing telemetry/history.
Unauthenticated WebSocket and heartbeat requests must be rejected. Health alone does not
prove that an Edge is connected. Migration rollback instructions are in [gateway.md](gateway.md).

## Connect the existing Edge PC (later)

1. Back up the local database and environment. Update the checkout and apply the migration
   through 0013 if not already applied. Keep its existing database volume, credentials,
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

## Phase 11.2 upgrade

Use the [Cloud-first, Edge-second update checklist](realtime-sync.md#safe-update-existing-cloud-first)
for an already deployed installation. It preserves durable backlog and database volumes.

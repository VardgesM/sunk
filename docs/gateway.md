# Shared gateway: deployment, one-time migration and rollback

## Boundaries

`/opt/gateway` owns Caddy, TCP 80/443 and certificate renewal. `/opt/modbus-monitor` owns
only PostgreSQL, API, static React/nginx and the one-shot migration job. Separate Compose
projects share an **external** `web` network. Only API/frontend and gateway join it.
PostgreSQL and the migration job use only the application-private `database` network.
No application service publishes a host port; there is no Cloud hardware worker.

The non-root nginx frontend listens on 8080, serves SPA fallbacks, returns 404 for API
paths and missing assets, and writes only to a small `/tmp` tmpfs. It has no certificates,
runtime secrets, API proxy or Caddy binary. Caddy routes `/api` and `/api/*` to the API,
including `/api/ws/live`, and other paths to nginx. Same-origin URLs, exact allowed hosts,
CORS, CSRF, Secure/HttpOnly/Strict cookies and Edge machine authentication are unchanged.

The API trusts forwarded headers from **only** `GATEWAY_IPV4`, not `*` or the entire
shared network. Reserve that address outside Docker's dynamic IP pool. Review network
subnets before creating one; the example is infrastructure configuration, not a device
address. Unique aliases default to `modbus-api` and `modbus-frontend`. If overridden,
match them in gateway `MODBUS_*_UPSTREAM` settings.

Official references: [Caddy WebSocket proxying](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[non-root nginx](https://github.com/nginx/docker-nginx-unprivileged).

## Prepare BEFORE any cutover

1. Inspect Git status/revision, active image IDs, Compose project/config-file labels,
   networks, actual volume names and current hostname. Do not print rendered Compose
   config or container environment containing secrets to shared logs.
2. Create a Phase 12 encrypted full backup in Cloud **as ADMIN**; download it and retain
   its passphrase separately. Require `AVAILABLE` status and record its checksum.
   Preserve a protected copy outside normal retention. Do not create a plaintext dump.
3. Preserve `.env.cloud` (600), old production Compose and current API/frontend image IDs
   under a private recovery directory. Tag old images to prevent accidental loss. Preserve
   the old Caddyfile (inside its retained image). Never prune retained images during migration.
4. Inspect `docker inspect <old-frontend>` mounts at `/data` and `/config`. Reuse those
   exact volumes as gateway **external volumes**, regardless of old project-prefixed names.
   Optionally clone them to separate recovery volumes with matching ownership. Never have
   both old and new Caddy running against the same writable state at once.
5. Build and verify new API/frontend images in a separate checkout/project with synthetic
   credentials, database and certificate volumes. No physical writes; no real Edge tokens.
   Keep old production images tagged before a production build replaces `:local` tags.
6. Copy `deploy/gateway/` to `/opt/gateway`, owned by the deployment user. Set `.env` from
   `gateway.env.example`: existing `MODBUS_HOST`, `MODBUS_SCHEME`, actual Caddy volumes,
   network and reserved gateway IP. No PostgreSQL/Edge/user secrets belong in this file.
   Keep Caddyfile readable to container UID 1000 (644); `.env` remains 600.

Example helpers (preserve the real application project name):

```bash
app() { docker compose --project-name modbus-cloud --project-directory /opt/modbus-monitor --env-file /opt/modbus-monitor/.env.cloud -f /opt/modbus-monitor/docker-compose.cloud.production.yml "$@"; }
gateway() { docker compose --project-name gateway --project-directory /opt/gateway --env-file /opt/gateway/.env -f /opt/gateway/docker-compose.yml "$@"; }
# Check existing subnets before selecting the following example:
docker network create --subnet 172.30.50.0/24 --ip-range 172.30.50.128/25 web
app config --quiet
gateway config --quiet
gateway build
gateway run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

New installations additionally create the two chosen Caddy volumes before starting.
Existing installations must not substitute empty volumes for discovered certificate state.
Gateway does not share database or backup volumes.

## Controlled cutover

Pause an enabled host updater runner for the topology migration. Do not start a second
runner or modify the Edge. Stage all files/images first. Use a recovery Compose file with
absolute build paths or `--project-directory /opt/modbus-monitor`, the **same project name**,
original env and retained image override, so rollback uses the original database volumes.
Validate that recovery config resolves to the inspected volume names before stopping anything.

```bash
# Prepare new images/config before this point. No migration is required for this change.
app stop frontend
app up -d --no-deps --no-build --wait api frontend
gateway up -d --no-build --wait
curl --fail https://CURRENT_HOST/api/health
curl --fail https://CURRENT_HOST/api/health/db
```

Only replacing API/frontend interrupts application traffic. Database and Ubuntu Edge continue
running; Edge queues sync during the short cutover. Gateway takes over the unchanged public
hostname and certificate storage. Do not run `alembic downgrade` or a needless schema change.
Current revision remains `0014_backups`. Retain old backend/public networks for easy rollback.

Verify certificate validity, login, SPA deep links, authenticated WebSocket, System/Diagnostics,
Backups/Updates, Edge ONLINE, advancing current timestamps and historical receipt. Check
`docker ps`, `docker network inspect web`: only gateway publishes 80/443; database/API have
no host mapping; projects are `gateway` and `modbus-cloud`. Existing other projects are untouched.

## Immediate rollback (no database restore/downgrade)

Before cutover save `old-compose.yml` and `old-images.json` with inspected retained tags.
The latter sets API/migrate to the retained API and frontend to the retained Caddy image.
Use the original env backup if new network values were added; never retype passwords.

```bash
gateway stop caddy
# Application Compose may now be the new file; stop only application clients.
app stop api frontend
docker compose --project-name modbus-cloud --project-directory /opt/modbus-monitor \
  --env-file /PATH/TO/PRIVATE-RECOVERY/.env.cloud \
  -f /PATH/TO/PRIVATE-RECOVERY/old-compose.yml \
  -f /PATH/TO/PRIVATE-RECOVERY/old-images.json \
  up -d --no-deps --no-build --wait api frontend
```

The old frontend again owns 80/443 using original certificate volumes. Keep gateway stopped.
Verify public health/certificates and sync. Restore the old operational Compose file as well
before routine administration resumes. No database volume is removed or replaced by rollback.

## Independent operation and updates

`app restart api frontend` does not affect gateway. `gateway restart caddy` does not restart
PostgreSQL, API or frontend (browser connections briefly reconnect). `app down` leaves the
external `web` network and gateway running, serving upstream-unavailable until the app returns.
Never use volume deletion during a deployment.

Updater v1 still changes **only application images**, with the operator-pinned application
Compose. Its guard rejects a gateway service, application-published ports or certificate
mounts. Release artifacts contain server/frontend files, including `frontend/nginx.conf`,
but no gateway configuration. Health verification checks both internal version/schema/safety
and public API/database/SPA routing with certificate validation. Rollback preserves gateway
container identity and certificate mounts. The one-time old-Caddy-to-nginx topology migration
is an operator deployment, not an application updater job; update the host runner checkout
afterwards before resuming it. Old Caddy-era artifacts are incompatible with this topology.

Application backups remain encrypted Phase 12 backups. Independently preserve `/opt/gateway`
configuration and Caddy external volumes securely; these contain private certificate keys.
Do not commit runtime env files, private recovery directories or certificates.

For HTTP-only testing use `MODBUS_SCHEME=http`, matching `CLOUD_SCHEME=http`, exact public
origin and `AUTH_COOKIE_SECURE=false`; bind gateway to localhost and use an SSH tunnel.
For production keep HTTPS and Secure cookies. No public certificate is requested in smoke tests.

## Validation

`tests/compose_production_smoke.py`: separate gateway/application projects, HTTP, local-CA TLS,
Secure cookies, WSS, machine authentication, non-root SPA, private ports and gateway identity
across application restart. `tests/compose_update_smoke.py`: real encrypted backup, failed-health
rollback and successful update while gateway ID/start time remain unchanged. Synthetic data only.
`tests/docker_permissions_smoke.py` covers nginx, API and migration source access with umask 077.
These scripts remain cross-platform; they may run on a separate Ubuntu test host instead of Windows.

## Verification record: 2026-10-09

Changed files:

- Added `deploy/gateway/{Dockerfile,docker-compose.yml,Caddyfile,gateway.env.example,README.md}`,
  `frontend/nginx.conf`, this runbook, `tests/gateway_helpers.py`, and `tests/test_gateway.py`.
- Changed `docker-compose.cloud.production.yml`, `.env.cloud.example`,
  `deploy/update/cloud.compose.yml`, `frontend/Dockerfile.production` and the dev Dockerfile comment.
- Changed `server/app/updates/{compose,artifact}.py` and `server/app/release.py`.
- Updated `tests/{compose_production_smoke,compose_update_smoke,docker_permissions_smoke,test_updates}.py`.
- Updated `README.md`, `AGENTS.md`, `docs/{production-cloud,architecture,update}.md`.
- Removed `deploy/cloud/Caddyfile`; the production frontend has no Caddy responsibility.

All application tests ran on Ubuntu in a separate checkout and disposable Docker projects,
with synthetic credentials and no production database or physical equipment. Windows was
used only for source editing and SSH. The existing `shop` project was left unchanged.

| Check | Result |
| --- | --- |
| `POSTGRES_PASSWORD=<synthetic> python -m pytest tests -q` | 689 passed, 21 skipped; 268.66 s. Skipped tests require a separate `TEST_DATABASE_URL`. |
| Targeted gateway/updater/auth/backup/diagnostics/migration tests | 190 passed; 91.33 s. |
| `npm run test -- --maxWorkers=1 --testTimeout=20000` | 119 passed, 17 files; 151.38 s. Initial parallel run hit existing 5-second timeouts under the VPS CPU limit. No assertions were removed. |
| TypeScript / ESLint / frontend production build | Passed; existing Vite chunk-size warning remains. |
| Ruff on changed Python modules and tests | Passed. |
| `python tests/compose_production_smoke.py` | Passed: HTTP, local-CA HTTPS, real browser login/mobile SPA, Secure cookies, WSS, machine heartbeat, host/origin checks, Alembic and gateway independence. |
| `python tests/compose_update_smoke.py` | Passed: encrypted PostgreSQL backup, injected failure → ROLLED_BACK, then SUCCESS; gateway container ID/start time unchanged. |
| `python tests/docker_permissions_smoke.py` | Passed: all three images from 0600/0700 sources, non-root API/nginx/Vite, secret exclusion, PostgreSQL migrations/check. |
| Production application/gateway Compose + Caddy/nginx/preflight | Passed before cutover. |

During preparation the new tmpfs YAML list was corrected, and the nginx permission test's
localhost probe was made explicitly IPv4 to match its production health check. Minimal VPS
Chromium libraries were extracted only in the disposable test directory, not installed into
the host OS. These test-environment fixes did not change application business behavior.

Production cutover took 40.65 seconds. The original hostname, TLS certificate fingerprint,
environment bytes, PostgreSQL container ID/start time and other project container IDs stayed
unchanged. Original Caddy volumes were reused externally and cloned into protected recovery
volumes. No migration, database restart, physical command, Git commit or push was performed.

Private rollback assets are retained at
`/opt/modbus-monitor/.local/gateway-cutover-20261009/`: encrypted database backup, old env,
old Compose, retained image override, source copies, validation records and `rollback.sh`.
The script was syntax/config/volume-identity checked; production did not require rollback.
The isolated updater test exercised actual rollback. Run the production script only if
needed and after confirming it is still the appropriate recovery point:

```bash
bash /opt/modbus-monitor/.local/gateway-cutover-20261009/rollback.sh
```

Post-cutover: public health and database health return 200, SPA routes load, authenticated
WebSockets are accepted, all four application/gateway services are healthy, and only gateway
publishes 80/443. Edge is ONLINE and current-state timestamps advance. The operator reported
the UI working and sensors disconnected. All 243,527 existing history records were retained;
fresh successful sensor samples/history could not be verified with disconnected sensors.
Alembic remains `0014_backups`; `alembic check` reports no new operations. No startup ERROR
or traceback appeared in gateway/API/nginx logs.

The operator-run gateway copy in `/opt/gateway` is independent from the repository template.
Repository changes were transferred over SSH without committing; review/commit/push and
normal checkout alignment are a separate requested action. Keep the recovery assets until
the deployment has been accepted and an independent backup verified.

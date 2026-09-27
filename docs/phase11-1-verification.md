# Phase 11.1 verification report

Repository preparation only. No connection to the real VPS, DNS/firewall change, local
physical configuration change or physical write was performed.

## Results

| Check | Result |
| --- | --- |
| Full backend `pytest tests -q --tb=short --show-capture=no` | **522 passed in 174.27s**; TEST_DATABASE_URL supplied privately, disposable PostgreSQL schemas |
| Production unit tests `pytest tests/test_production.py -q` | **12 passed** (included above) |
| Ruff `python -m ruff check --config server/pyproject.toml server tests` | Passed |
| Frontend `npm --prefix frontend run test -- --run` | **84 passed, 13 files** |
| `npm --prefix frontend run typecheck` | Passed |
| `npm --prefix frontend run lint` | Passed |
| `npm --prefix frontend run build` | Passed; pre-existing main chunk advisory ~566.6 kB |
| Alembic upgrade/downgrade/re-upgrade and metadata comparison | Passed in existing PostgreSQL sync tests |
| Container `alembic check` / `alembic current` | Passed; head **0012_edge_cloud**; no new migration needed |
| Compose standalone / Edge / development Cloud / production Cloud | Passed; modes verified without printing rendered credentials |
| Production image builds | Passed; non-root static frontend/Caddy and shared API image |
| `git diff --check` | Passed |
| Real env files ignored, example templates trackable | Passed |

## Docker integration (all exit 0)

```sh
python tests/compose_production_smoke.py
python tests/compose_sync_smoke.py
python tests/compose_modbus_smoke.py
python tests/compose_commands_smoke.py
python tests/compose_automation_smoke.py
python tests/compose_alarms_smoke.py
python tests/compose_dashboards_smoke.py
python tests/compose_auth_smoke.py
```

Production smoke verified exactly PostgreSQL/migrate/API/frontend services; no published
API/database ports; internal networks; migration gate; HTTP routing; unknown host and
cross-origin rejection; authenticated WS; upgrade to HTTPS with an isolated local CA;
certificate verification in API client; Secure/HttpOnly/SameSite=Strict host-only cookies;
authenticated WSS; static production React browser login at mobile width; authenticated
machine registration/heartbeat; anonymous machine rejection; HTTP?HTTPS redirect;
Alembic head/metadata; proxy UID 1000; no secrets in logs. Its certificate/root was test-only;
no public certificate authority or real domain was contacted.

Initial integration found an upstream Caddy file-capability conflict with cap_drop ALL.
The production Dockerfile removes that unnecessary capability, since Caddy listens on high
internal ports. The corrected image passed. Test selectors and runtime assertions were also
corrected to match required MUI labels and Cloud's intentionally absent local worker.

Existing Docker regressions covered offline Edge continuity/catch-up, idempotent remote
simulator commands, software Modbus read/write/read-back/recovery, Automation, Alarms,
dashboard persistence/charts and authenticated roles/WebSocket/audit. Telegram was disabled.
All disposable fixture databases and volumes were removed.

## Created files

- `.dockerignore`, `.env.cloud.example`, `.env.edge.example`
- `docker-compose.cloud.production.yml`
- `deploy/cloud/Caddyfile`, `frontend/Dockerfile.production`
- `server/app/cloud_preflight.py`
- `tests/test_production.py`, `tests/compose_production_smoke.py`
- `docs/production-cloud.md`, this report

## Modified areas

- `.env.example`, `.gitignore`, server/frontend Docker ignore files
- Existing three Compose files: canonical APP_MODE, compatible APPLICATION_MODE fallback
- Settings/main: aliases and TrustedHostMiddleware
- Sync remote/runtime services: Cloud physical-write gate and accurate control availability
- Existing Compose regression fixtures: explicit APP_MODE=standalone
- README, architecture/Edge-Cloud docs and AGENTS.md

## Before a real deployment

Choose real host/domain and credentials, arrange database backups, push this repository
revision, and follow docs/production-cloud.md. Public certificate issuance, real Ubuntu VPS
networking, WAN behavior and the real Edge connection remain deployment-time checks.
Physical remote writes remain disabled by default on both sides. The local PC and production
containers were not migrated/recreated by this preparation task. No commit/push was requested
as part of this phase; changes are ready for review and commit.

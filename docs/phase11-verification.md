# Phase 11 verification

Verified locally on Windows with Docker Desktop. Production containers were not recreated;
the production database was not upgraded by these tests. All device control used a simulator
or a disposable software Modbus TCP server. No real Telegram messages or physical writes.

| Check | Command / scope | Result |
| --- | --- | --- |
| Full backend | `.venv\Scripts\python.exe -m pytest tests -q --tb=short --show-capture=no` with TEST_DATABASE_URL injected privately from Settings | 510 passed in 210.18 seconds |
| Sync PostgreSQL tests | `pytest tests/test_sync.py -q` with isolated schemas | 9 passed; included in full suite |
| Authorization route dependency review | `pytest tests/test_auth.py -q` | 42 passed in 19.23 seconds |
| Ruff | `python -m ruff check --config server/pyproject.toml server tests` | Passed |
| Frontend | `npm.cmd --prefix frontend run test -- --run` | 84 passed, 13 files |
| TypeScript | `npm.cmd --prefix frontend run typecheck` | Passed |
| ESLint | `npm.cmd --prefix frontend run lint` | Passed |
| Production frontend | `npm.cmd --prefix frontend run build` | Passed; existing >500 kB chunk advisory (main bundle ~566.6 kB) |
| Migration | `0011_auth` ? `0012_edge_cloud`, downgrade to `0011_auth`, upgrade again and compare_metadata | Passed in disposable PostgreSQL schema |
| Container metadata | `alembic check` inside isolated Edge and Cloud APIs | Passed |
| Compose | `docker compose config --quiet`; same with Edge override/profile and Cloud override | All passed |
| Images | `docker compose build api worker frontend`; final backend rebuild | Passed |
| Whitespace | `git diff --check` | Passed |

## Docker integration commands

All exited 0 and removed their isolated fixtures/volumes:

```sh
python tests/compose_sync_smoke.py
python tests/compose_modbus_smoke.py
python tests/compose_commands_smoke.py
python tests/compose_automation_smoke.py
python tests/compose_alarms_smoke.py
python tests/compose_dashboards_smoke.py
python tests/compose_auth_smoke.py
```

Edge/Cloud was repeated successfully after the final sync-process recovery changes.
It verified separate PostgreSQL databases; metadata, typed current/history and dashboard
mirrors; authenticated WebSocket; Cloud outage with uninterrupted local telemetry/history/
Automation; automatic backlog catch-up; remote alarm acknowledgement; exactly one local
simulator command per correlation; verified result synchronization; mobile Cloud chart and
controls; read-only configuration; ONLINE status; Alembic checks; logs without secrets.

The regressions verified four Modbus read function codes, software TCP failure/recovery,
source provenance, serial diagnostic APIs, simulator and software TCP write/read-back,
Automation FOR/hysteresis/ALL, Alarm lifecycle, dashboard layout/restart persistence,
authentication/roles/audit and WebSocket access control.

## Limits

No real VPS/TLS deployment, Internet WAN conditions, or physical remote relay operation was
tested. Deploy using docs/edge-cloud.md after backing up the target database. Default
standalone behavior remains supported. Outbox, receipts and mapping storage need normal
disk monitoring; this phase deliberately does not silently discard unsynchronized data.

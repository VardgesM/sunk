# Phase 11.2 verification

All database/integration verification uses disposable local databases and containers.
No production Edge database, environment, VPS or physical relay was changed. Telegram
is disabled. The Edge/Cloud and production workflows keep MODBUS_WRITES_ENABLED=false.
Existing command regressions exercise simulator/software TCP only.

## Commands

From repository root (Windows). TEST_DATABASE_URL points only to a dedicated temporary
PostgreSQL 17 container, never the operating Edge database. Secrets are not printed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short --show-capture=no
.\.venv\Scripts\python.exe -m pytest tests/test_sync.py -q
.\.venv\Scripts\python.exe -m ruff check --config server/pyproject.toml server tests
npm.cmd --prefix frontend run test -- --run
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.edge.yml --profile edge config --quiet
```

The test launcher sets APP_MODE=standalone for generic tests. Edge/Cloud fixtures select
modes explicitly and migrate isolated schemas. Alembic coverage includes offline SQL,
0012 -> 0013 with existing queued data, downgrade/upgrade and compare_metadata. Disposable
Compose APIs also run `alembic check`; production smoke verifies current head 0013.

Docker regression commands (application test images built beforehand):

```powershell
.\.venv\Scripts\python.exe -X utf8 tests/compose_sync_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_modbus_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_commands_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_automation_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_alarms_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_dashboards_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_auth_smoke.py
.\.venv\Scripts\python.exe -X utf8 tests/compose_production_smoke.py
```

Each script uses its own project/volumes and removes its fixtures. The older
`compose_telemetry_smoke.py` targets a running installation and was deliberately not
run against the working Edge; telemetry/history/WebSocket are covered by the isolated
regressions above and backend tests.

## New focused coverage

- Current 10/11/12/13 coalesces to one pending 13; current ingestion creates no history.
- One-cycle freshness despite 2000 pending historical rows; complete idempotent catch-up.
- Offline retry/backoff, new client instance/restart, typed values and source timestamps.
- GOOD/COMM_ERROR arriving in either order, repeated batches and older acknowledgements.
- Worker replacement during HTTP upload survives acknowledgement of the prior UUID.
- 24 Tags remain bounded; current/runtime provenance stays accurate.
- 12 frequently updated Tags with batch size 3 all receive a turn within four controlled
  cycles. This is a deterministic scheduler check, not a fragile elapsed-time assertion.
- Poll every 5 seconds/history every 60 seconds retains only policy-selected history.
- Every Command and Alarm transition remains independently durable.
- Existing-data initialization and old-queue migration preserve durable IDs/payloads.
- An unsent current insert replaced by delete cannot stall or later resurrect in Cloud.

## Extended Compose scenario

24 additional simulator Tags poll every 2 seconds with fixed 60-second history. Cloud is
stopped while local operation continues. To avoid waiting 100 minutes, the isolated fixture
adds 100 already-selected historical points per Tag (2400 rows) with original timestamps.
The real history policy is tested independently with controlled timestamps.

Cloud restarts, a distinctive current value is produced and sync restarts. Cloud receives
that value while history is still pending. History then drains completely; every Tag's
ordered history points, quality, source, values and timestamps match Edge with no duplicate
rows. Existing local offline Automation, remote command/read-back, Alarm acknowledgement,
authenticated WebSocket, mobile dashboard and chart checks also pass.

## Scope and limits

No real-network latency guarantee is inferred from local tests. The large-backlog fixture
uses 2400+ records, not a production-scale 100000-record benchmark. Actual network/Cloud
capacity, initial metadata dependencies and selected batch sizes affect latency. Current
state has separate capacity and history cannot impose a FIFO replay delay.

The frontend build retains its existing large-chunk warning (ECharts bundle); build succeeds.
Production public ACME/VPS deployment was not attempted. See [safe Cloud-first upgrade](realtime-sync.md).

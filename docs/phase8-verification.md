# Phase 8 verification ? 2026-09-26

## Automated checks

- Backend: 399 passed, including 37 new alarm/Telegram cases, existing Automation/Commands/Modbus,
  history and CRUD regressions. Command: `.venv\Scripts\python.exe -m pytest tests -q --tb=short --show-capture=no`.
  TEST_DATABASE_URL was supplied from Settings internally without printing credentials.
- PostgreSQL test created/dropped its own random schema, upgraded to head, compared metadata,
  downgraded to base and replayed upgrades. Offline SQL/chain tests also passed.
- `.venv\Scripts\python.exe -m ruff check --config server/pyproject.toml server/app server/alembic tests`: passed.
- `npm.cmd --prefix frontend run test`: 51 passed across 9 files (7 new alarm UI tests).
- `npm.cmd --prefix frontend run typecheck`: passed.
- `npm.cmd --prefix frontend run lint`: passed.
- `npm.cmd --prefix frontend run build`: passed. Vite warns main chunk is about 502 kB (161 kB gzip).
- `docker compose config --quiet`: passed; `docker compose build api worker frontend`: passed.

## Disposable Docker integration

Each script started a separate project/volume and removed it on completion. No test fixtures were
added to the working database; software Modbus servers were used instead of physical hardware.

- `.venv\Scripts\python.exe tests/compose_alarms_smoke.py`: passed numeric/boolean alarms, FOR,
  hysteresis, acknowledge/clear/reactivation, unique activation deliveries, separate worker/API
  PostgreSQL NOTIFY and WebSocket events, history continuity, mobile browser UI/editor/count,
  migrations and clean logs. Telegram explicitly disabled; test notification correctly SKIPPED.
- `.venv\Scripts\python.exe tests/compose_automation_smoke.py`: passed FOR, hysteresis, edge,
  ON/OFF/multiple conditions, verified automation commands, current/history/WebSocket and mobile UI.
- `.venv\Scripts\python.exe tests/compose_commands_smoke.py`: passed simulated coil/numeric/uint64,
  mobile manual controls, software TCP writes and PyModbus read-back verification.
- `.venv\Scripts\python.exe tests/compose_modbus_smoke.py`: passed four read operations, slave
  addressing, decoded values, history/charts/WebSocket, transport tests, configuration changes,
  disabled connections, COMM_ERROR on stop and automatic recovery on restart.

## Working installation

API/frontend updated; migration `0008_alarms` applied and `alembic check` reports no metadata drift.
Native worker restarted preserving existing Modbus source/master-write settings; no new physical
commands or rules were created. Existing physical telemetry already reported COMM_ERROR before the
update (transport could not open). Phase 8 does not resolve that hardware/serial availability issue.
Telegram is not enabled/configured here, so real Telegram delivery was not attempted. Success and
failure paths are covered by mocked HTTP. Physical alarm/relay actuation was not tested or required.

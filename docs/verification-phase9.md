# Phase 9 verification

All integration fixtures used disposable Compose projects and PostgreSQL volumes. No physical control commands or real Telegram messages were sent. The existing operating deployment and its configuration were not restarted or modified.

## Automated checks

- Backend: `.venv/Scripts/python.exe -m pytest tests -q --tb=short --show-capture=no` with `TEST_DATABASE_URL` supplied privately from Settings: **459 passed**. Includes decoder/Modbus, telemetry/history, Commands, Automation, Alarms, serial binding and Dashboard tests. PostgreSQL checks create a random schema, upgrade, compare metadata, downgrade and replay; no public tables are altered.
- Dashboard-focused PostgreSQL/API/migration checks: **33 passed**. Includes simultaneous default-dashboard creation, relational widget persistence, compatibility, FK deletion protection, layout revisions and bounds.
- `npm --prefix frontend run test`: **68 passed / 11 files**.
- `npm --prefix frontend run typecheck`: passed.
- `npm --prefix frontend run lint`: passed.
- `npm --prefix frontend run build`: passed. Existing main-bundle size warning remains (~503.53 kB minified); chart and dashboard code is split into separate chunks.
- `.venv/Scripts/python.exe -m ruff check --config server/pyproject.toml server/app server/alembic tests`: passed.
- `docker compose config --quiet`: passed.
- `docker compose build api worker frontend`: passed.
- Alembic upgrade/downgrade/replay and `alembic check` in isolated PostgreSQL: passed, no metadata drift.

## Compose integration commands

Run each with `.venv/Scripts/python.exe tests/<filename>` after building images. Real Telegram is disabled in all integration runs, and software Modbus servers or simulator values are used exclusively.

| Script | Verified |
| --- | --- |
| `compose_dashboards_smoke.py` | Eight widget types; real browser desktop/phone; one shared WebSocket; changing live values; ECharts history/time range; simulator coil command through existing queue and SUCCESS/read-back; alarm acknowledgement/events; resize/save/reload; persistence after stack restart; history; clean API/worker logs. |
| `compose_modbus_smoke.py` | Four read function codes, slave addressing, current/history/source/WebSocket, software TCP outage/recovery, configuration reload, disabled connection, runtime UI. |
| `compose_commands_smoke.py` | Simulator coil/numeric/exact uint64, mobile control UI, software TCP writes/read-back, current/history/command events. |
| `compose_automation_smoke.py` | FOR, hysteresis, edges, ON/OFF rules, ALL conditions, verified automation commands, mobile editor/execution history. |
| `compose_alarms_smoke.py` | Thresholds, quality/lifecycle, FOR/hysteresis, acknowledgement/reactivation, WebSocket, mobile UI, Telegram-disabled delivery deduplication. |

All five completed successfully and removed their isolated fixture databases. No physical relay test was performed for Phase 9. Phase 9 is implemented and verified in code/built images; applying it to an already running installation uses the documented rebuild/migration deployment procedure.

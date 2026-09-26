# Modbus Monitor

A configurable industrial monitoring platform. FastAPI and the worker share one Python package;
React/TypeScript/MUI provides the interface. Phase 8 adds Alarms and optional Telegram notifications alongside Automation, verified commands, RTU/TCP reads, simulator
telemetry, current values, history and WebSocket charts. Physical writes are disabled by default.
Authentication and dashboard editing remain deferred.

## Repository

- `server/app`: API, shared settings/database infrastructure, schemas, and separate worker entry point.
- `server/alembic`: foundation, configuration, current values, commands and `0007_automation` / `0008_alarms` migrations.
- `frontend/src`: existing shell, four configuration pages, API client, health indicator and UI tests.
- `tests`: health/worker tests, relational CRUD tests, migration checks and opt-in PostgreSQL integration.
- `docs`: [architecture](docs/architecture.md), [database](docs/database.md), [Modbus boundary](docs/modbus.md).
- `AGENTS.md`: permanent project rules.

## Start with Docker Compose

Install Docker with Compose v2 (Docker Desktop with Linux containers on Windows). From the repository root:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

On macOS/Linux copy the example only if `.env` does not exist. Edit `.env` and replace `POSTGRES_PASSWORD` with your own
local password. The example is a placeholder, not a real credential. Do not commit `.env`.

```sh
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
docker compose logs -f api worker
```

Open http://localhost:5173. API docs: http://localhost:8000/docs.
Health: http://localhost:8000/api/health and http://localhost:8000/api/health/db.
The status chip checks API liveness on load and every 15 seconds; it does not report device or database health.

Compose starts `postgres`, `api`, `worker`, and `frontend`. PostgreSQL, API and frontend have health
checks. Worker health is observable through heartbeat logs; there is no misleading process-only health
check. The API applies migrations before starting; the worker waits for API/database readiness.
The API applies migrations through `0009_serial_binding` on existing databases and fresh volumes.
Existing tags with history_enabled=true begin storing every sample after upgrade; review their
policy/retention settings before running high-frequency collection.

### Enable simulated live values

Set these values in your local `.env`, then run `docker compose up --build -d --wait`:

```dotenv
TELEMETRY_SOURCE=simulator
SIMULATOR_ENABLED=false
SIMULATOR_FAILURE_PROBABILITY=0
WORKER_CONFIG_REFRESH_SECONDS=2
STALE_MULTIPLIER=3
STALE_CHECK_SECONDS=1
HISTORY_CLEANUP_SECONDS=3600
```

Simulation defaults to disabled. Create an enabled Connection, Device, and Tags through the UI;
the Tags page displays current values, quality, last successful update, and live connection status.
No serial port or TCP device is contacted. The worker reloads configuration every two seconds and
respects each tag's polling interval. Disabling a tag, device, or connection stops its acquisition.

Numeric simulation changes gradually in the raw type domain, then applies
`engineering = raw * scale + offset` once. Tag limits constrain engineering values. Boolean values
are unscaled. An impossible range produces BAD. An optional failure probability between 0 and 1
produces COMM_ERROR while retaining the previous value. Stale detection marks GOOD values STALE
after three configured polling periods by default, including when the worker stops.

REST snapshots and PostgreSQL LISTEN/NOTIFY support reconnect recovery; notifications are not durable.
See the [live protocol](docs/live-protocol.md) for payloads, quality states, and recovery behavior.

```sh
docker compose down
```

This preserves the `postgres_data` volume. `docker compose down -v` deliberately deletes database data.
Changing the password in `.env` does not change a database user already stored in an existing volume;
update the database role credentials explicitly when reusing data.

The Compose frontend runs the Vite development server. Production Nginx/static hosting is deferred.
All published ports bind to localhost. Changing `FRONTEND_PORT` also requires updating CORS origins
if accessing the API directly; Vite uses same-origin `/api` requests through its proxy.

## Local development (Windows PowerShell)

Requires Python 3.11+ and Node 24, plus PostgreSQL 17 or the Compose database.
Run from the repository root after creating `.env` as above:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "./server[dev]"
docker compose up -d postgres --wait
.\.venv\Scripts\python.exe -m alembic -c server/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload --port 8000
```

In a second terminal at the repository root:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

In a third terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Using `npm.cmd` avoids PowerShell execution policy restrictions on `npm.ps1`. On macOS/Linux,
use `.venv/bin/python` and `npm` in the equivalent commands. Root `.env` settings use `localhost`
for PostgreSQL; Compose overrides the database host to `postgres` and the proxy target to `api`.
Settings load `.env` relative to the current directory, so run Python commands from the root.
Ctrl+C stops host-run API/worker processes cleanly. Simulator development requires no serial device or Modbus host.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check --config server/pyproject.toml server/app server/alembic tests
.\.venv\Scripts\python.exe -m alembic -c server/alembic.ini upgrade head --sql
cd frontend
npm.cmd run test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
cd ..
docker compose config --quiet
```

The default backend suite covers health/worker behavior, complete relational CRUD, transport/tag
validation, unique keys, safe deletion, foreign keys, hierarchy cycles, filters, pagination and offline
migrations. Relational tests use SQLite **only as a test harness**; PostgreSQL is still the only runtime
database. Frontend tests cover dynamic forms, search/filter requests, server errors, confirmation and
dependency-conflict feedback. Tests contain isolated fixtures; no fixtures are seeded into the app.

## Configure the platform

1. Create Locations and optionally select parent locations.
2. Create a Connection. Choose TCP (typed host and port) or RTU (manually typed serial port and serial settings).
3. Create a Device, selecting its Connection, optional Location and unicast slave ID 1–247.
4. Create Tags for that Device with unique lowercase keys and explicit register type/encoding.

Tag addresses are **zero-based Modbus offsets**. A manual's `40001` notation commonly corresponds
to holding-register offset `0`; the application does not interpret or convert this notation. Entering
40001 stores offset 40001. See [addressing decisions](docs/modbus.md) before configuring tags.
Writable enables eligibility for the manual command pipeline; the physical master switch defaults off. Enabled state and poll intervals control the selected telemetry source;
history_enabled and its policy independently control historical storage. Explicit modbus mode enables reads; physical writes additionally require the master switch and confirmation.
Empty databases show empty management pages; no inventory or sensors are hardcoded.

## Configuration API

### View historical charts

1. Enable simulation as above, then create or edit a Tag.
2. Enable History and choose every_sample, fixed_interval, or on_change.
3. For a development fixed-interval example, set poll interval to 1000 ms and history interval to
   5000 ms. Both settings are saved in PostgreSQL; no runtime examples are seeded.
4. Optionally set retention days; blank retains indefinitely. Save and wait for several samples.
5. Click the Tag name to open `/tags/:id`. Select a preset/custom range or Refresh history.

The details page shows live values separately from the REST history chart. Numeric charts use lines;
boolean charts use steps. Timestamps display in browser-local time while storage/queries use UTC.
Chart zoom/pan is local; use a smaller query range for more detail in downsampled results.

`GET /api/tags/{id}/history` accepts `from`, `to`, `limit`, `order`, and `max_points`.
It defaults to the last 24 hours, ascending order and 1000 records, caps raw results at 5000, and
allows ranges up to 366 days. `max_points` (up to 2000) requests deterministic SQL time buckets with
min/max/average and first/last timestamps. Invalid-quality buckets are gaps, not fake values.

One-second every_sample storage produces **86,400 rows per tag per day**. Prefer fixed_interval or
on_change for many frequent tags. Retention runs hourly by default in bounded worker batches, even
for disabled history. Tags with retained history return 409 on deletion. See [history documentation](docs/history.md)
for threshold semantics, recovery, failure isolation, API fields, and storage estimates.

### Configuration endpoints

Each of `/api/locations`, `/api/connections`, `/api/devices`, `/api/tags` supports:

| Method/path | Result |
| --- | --- |
| GET collection | 200, array; `limit` (1–500, default 100) and `offset` (>=0) |
| POST collection | 201, created entity |
| GET `/{id}` | 200 entity or 404 |
| PATCH `/{id}` | 200 entity; full merged-record validation |
| DELETE `/{id}` | 204; 409 if referenced by dependent configuration |

Additional filters: locations `parent_id`, `roots_only`; connections `protocol`, `enabled`; devices
`connection_id`, `location_id`, `enabled`; tags `search` (name/key), `device_id`, `register_type`,
`enabled`. Missing foreign keys and invalid fields return 422; uniqueness conflicts return 409.
See http://localhost:8000/docs for request/response schemas. Clearing nullable fields requires explicit
null; omitted PATCH fields remain unchanged. Protocol changes must clear incompatible transport fields.

### Current-value API

- `GET /api/tags/values`: snapshot with `tag_id`, `device_id`, effective `enabled`, and `quality` filters;
  keyset pagination uses `after_tag_id` and `limit` (1–500).
- `GET /api/tags/{id}/value`: one tag's latest state, including null state before its first reading.
- `/api/ws/live`: live events, readiness, heartbeat, and resynchronization messages.

The frontend loads a snapshot, connects, and snapshots again to close the connection gap.
Revisions prevent older snapshots from replacing newer live updates. Each affected cell updates
without reloading the page. Large numbers include an exact decimal companion for browser display.

## PostgreSQL integration check

With PostgreSQL running, set a `postgresql+asyncpg://` connection URL through `TEST_DATABASE_URL`
in your terminal (do not commit credentials). The role needs permission to create schemas.

```powershell
# Enter the URL privately in your shell environment, then run:
.\.venv\Scripts\python.exe -m pytest tests/test_postgres.py -q
```

This opt-in test creates a unique temporary schema, applies migrations, checks metadata consistency,
exercises API database health and a full CRUD flow, checks PostgreSQL constraints/concurrent reparenting,
then downgrades/replays migrations and removes only its test schema. Without the variable it skips.
It also verifies typed current values, constraints, and transactional notification delivery/rollback.

After starting Compose also run:

```powershell
docker compose exec api alembic current
docker compose exec api alembic check
Invoke-RestMethod http://localhost:8000/api/health/db
docker compose logs --tail 100 api worker postgres frontend
```

These commands validate the running containers; the isolated-schema test does not replace checking
container startup and logs. Do not downgrade a populated application database just to run tests.

With simulation enabled, run the opt-in container smoke test:

```powershell
.\.venv\Scripts\python.exe tests/compose_telemetry_smoke.py
# Development stack only: deliberately restarts worker/PostgreSQL and injects failures.
.\.venv\Scripts\python.exe tests/compose_telemetry_smoke.py --restarts
```

These create and remove their own configuration fixtures. The restart variant leaves the worker
running with simulation enabled and failure probability zero through process environment overrides;
set `.env` explicitly to persist that choice. Do not run database tests concurrently with this variant.

Optional browser verification uses an installed Microsoft Edge:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "./server[dev,browser]"
.\.venv\Scripts\python.exe tests/browser_live_smoke.py
.\.venv\Scripts\python.exe tests/browser_history_smoke.py
```

This checks actual live value changes, visible quality/status, and a mobile form at 375px width,
then removes its fixtures. Browser tooling is optional and is not installed in runtime containers.
The history smoke test also verifies fixed-interval and on-change storage against PostgreSQL,
numeric/boolean charts, custom ranges, mobile layout, disabled history, safe deletion, and continued
live updates without historical refetches. It removes only the history/configuration it creates.

## Schema changes (future tasks)

```powershell
.\.venv\Scripts\python.exe -m alembic -c server/alembic.ini revision --autogenerate -m "describe change"
.\.venv\Scripts\python.exe -m alembic -c server/alembic.ini upgrade head
```

Import new ORM models in `app.models`, review generated migrations, and document architectural changes.
The API and worker must remain separate runtime processes; only the worker communicates with devices.

## Real Modbus (Phase 5)

Set `TELEMETRY_SOURCE=modbus` and `SIMULATOR_ENABLED=false`, then recreate the worker with Compose.
PyModbus **3.13.1** reads RTU/TCP from database configuration. There is no simulated fallback.
The shell labels simulation explicitly; Tags show the retained value's source and communication errors.
Connections show runtime state and a worker-executed transport Test; Devices show derived availability.

See [Modbus behavior](docs/modbus.md) and [deployment instructions](docs/modbus-deployment.md) for
native Windows worker commands, localhost database configuration, Linux serial device mappings,
Windows Docker limitations, reconnect settings and the first real-device checklist.
Stop the container worker before starting a native worker; a database advisory lock enforces one owner.

Runtime endpoints: `/api/system/runtime`, `/api/system/serial-ports`,
`/api/connections/{id}/status`, `/api/devices/{id}/status`, and POST/GET `/api/connections/{id}/test`.
The API never opens serial/TCP Modbus transports. Test success verifies transport opening only.

Run isolated software TCP integration after building the application images:

```powershell
.\.venv\Scripts\python.exe tests/compose_modbus_smoke.py
```

This creates a separate Compose project/database, verifies all four reads through current values,
history, WebSocket and actual browser charts, stops/restarts the server, tests configuration changes,
then removes its project and volume. It does not seed the development database.
Do not run the simulator restart smoke concurrently with tests using the development PostgreSQL.

## Phase 5 validation

- Backend: 218 passed with PostgreSQL integration enabled (217 passed, 1 skipped without it).
- Frontend: 32 tests passed; TypeScript, ESLint and production build passed.
- Ruff, Compose validation, image builds, migrations through `0009_serial_binding`, PostgreSQL
  upgrade/downgrade/replay and Alembic metadata comparison passed.
- Isolated Docker TCP: four read functions, slave addressing, source/status/test APIs, current/history,
  WebSocket/chart rendering, communication failure/recovery and dynamic configuration passed.
- Simulator regression: worker/database restart recovery, stale/error states and live updates passed.
- History browser regression: numeric/boolean charts, policy changes, custom ranges, mobile layout,
  independent live values and fixture cleanup passed.

Physical RTU hardware/virtual serial integration remains unverified. Windows COM access from Linux
Docker containers is not equivalent to native access; use the documented native worker workflow.
The Compose frontend remains a development server; authentication and production hosting are deferred.

## Phase 6: verified manual commands

See [command lifecycle and safety](docs/commands.md). Only the worker command processor writes.
`MODBUS_WRITES_ENABLED=false` preserves read-only operation by default. The UI reports the worker's
actual switch, including a native Windows worker. Simulator writes work without enabling physical I/O.

Writable Tag details now provide manual controls; `/commands` displays durable status and filters.
POST `/api/tags/{id}/commands` enqueues a typed request. SUCCESS requires read-back; requested values
never replace actual values optimistically. Queue expiry defaults to 60 seconds, communication attempts
to 3. Uncertain writes are not resent; restart-interrupted commands fail for operator review.

```powershell
# Build first. These tests use isolated databases/software devices, never configured sensor hardware.
docker compose build api worker frontend
.\.venv\Scripts\python.exe tests/compose_commands_smoke.py
.\.venv\Scripts\python.exe tests/compose_modbus_smoke.py
```

For deployment, apply `alembic upgrade head` or recreate the API (its startup migrates automatically),
then restart the worker to load Phase 6. With a native Windows worker, keep the container worker stopped
and use the existing [native startup instructions](docs/modbus-deployment.md). Keep the physical switch
false unless an explicitly configured test actuator is ready. Existing sensor Tags remain read-only.
Commands require a Phase 6 worker; the API cannot execute them on its own.

### Phase 6 verification results

- Backend: **320 passed** with PostgreSQL enabled, including encoder permutations, command guards,
  RTU read/write exclusion, lost acknowledgement handling, queue claiming, expiry and regression tests.
- Frontend: **39 passed**; TypeScript, ESLint and production build passed.
- Ruff passed. Alembic offline SQL, isolated PostgreSQL upgrade/downgrade/replay and metadata checks passed.
- Docker images built; Compose configuration validated. Isolated command integration passed simulator
  OFF -> ON, numeric/exact uint64, current/history/WebSocket, mobile browser controls and Commands page.
- Test-only TCP server writes/read-back passed. Existing TCP read integration passed all four read
  functions, source/status, history/charts/WebSocket, transport reconfiguration and stop/restart recovery.
- Isolated integration volumes/configuration were removed. No real sensor/relay writes were performed.

The connected sensor worker is a native Windows process. Updating Docker API/frontend does not reload
that process's Python code: restart it with the documented native command to load the Phase 6 processor.
Keep `MODBUS_WRITES_ENABLED=false` for sensor-only operation; do not enable it to troubleshoot reads.

## Phase 7: Automation / Conditions

Open **Automation** to configure dynamic ALL/ANY conditions, FOR duration, hysteresis, cooldown
and verified SET_TAG_VALUE actions. All actions use the existing persistent command queue; physical
writes remain disabled by default. No physical automation rules are seeded.

Apply `alembic upgrade head` (or recreate the API, whose startup applies migrations), then restart
the worker and frontend to load Phase 7. For Windows COM ports use the existing native worker
workflow, with `MODBUS_WRITES_ENABLED=false` during deployment.

See [Automation behavior, API, safety and simulator testing](docs/automation.md).
Run `.\.venv\Scripts\python.exe tests/compose_automation_smoke.py` after
`docker compose build api worker frontend` for the isolated simulator/browser integration.


### Phase 7 verification results

- Backend (including isolated PostgreSQL): **362 passed**. Automation-specific tests: **37 passed**.
- Frontend: **44 passed** across 8 files; TypeScript, ESLint and production build passed.
- Ruff and Docker Compose validation passed. Alembic offline SQL, PostgreSQL upgrade/downgrade/replay,
  and metadata comparison passed. At Phase 7 verification the local API ran migration `0007_automation`.
- `tests/compose_automation_smoke.py`: simulator ON/OFF rules, FOR, hysteresis, single-edge behavior,
  ALL conditions, source=automation commands, verified values, history/WebSocket and mobile UI passed.
- `tests/compose_commands_smoke.py` and `tests/compose_modbus_smoke.py`: existing simulator/software TCP,
  command read-back, four read functions, charts, history/live updates and outage recovery passed.
- All disposable integration projects and their fixture volumes were removed. No physical automation
  tests were run, and no rules were seeded in the working database. Physical writes remain disabled.

The exact integration commands (from the repository root, after building images) are:

```powershell
.\.venv\Scripts\python.exe tests/compose_automation_smoke.py
.\.venv\Scripts\python.exe tests/compose_commands_smoke.py
.\.venv\Scripts\python.exe tests/compose_modbus_smoke.py
```


## Alarms and Telegram (Phase 8)

Open **Alarms** for active events, retained history, rule management and Telegram delivery results.
Alarms never control equipment; Automation continues to use verified commands. Fresh GOOD values,
FOR delay and hysteresis determine activation/clear. Acknowledge records operator awareness;
it does not clear an abnormal reading. See [alarm lifecycle and Telegram setup](docs/alarms.md).

Telegram defaults off. Set TELEGRAM_ENABLED=true and TELEGRAM_BOT_TOKEN privately in the worker
environment, configure chat ID in the Alarms -> Telegram tab, then explicitly send a test.
The token is never accepted by the browser/API. A queued test is only successful when delivery
status is SENT. Network failures are isolated and are not retried automatically.

After pulling this phase: `docker compose up --build -d --wait` applies migration 0008 and updates
the stack. For native RTU workflow, update API/frontend containers and restart the native worker
using the same existing source/database configuration (do not start a second Docker worker).

Additional isolated regression: `.venv\Scripts\python.exe tests/compose_alarms_smoke.py` after
`docker compose build api worker frontend`. No physical I/O or real Telegram in this test.

Phase 8 exact commands, results and integration limits: [verification report](docs/phase8-verification.md).


## Phase 8.1: Automatic USB-RS485 binding

Connections -> Modbus RTU now supports **Manual** and **Auto detect**. Select the worker-discovered
USB adapter once; Auto resolves its current COM/Linux port and recovers when it reappears under a
new name. Existing connections stay Manual until explicitly changed. Ambiguous adapters are never
chosen randomly; optional bounded probing reads only configured Tags/slaves, never writes.

See [USB identity, probing, hotplug and deployment](docs/serial-binding.md). Configure
SERIAL_SCAN_SECONDS=5 and SERIAL_PROBE_BUDGET_SECONDS=10 in the worker environment if needed.
Migration `0009_serial_binding` adds identity/runtime fields. Upgrade with
`docker compose up --build -d --wait`; for Windows native RTU keep the Docker worker stopped and
restart the native worker after API migration. Re-detect subsequently needs no process restart.

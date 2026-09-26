# Automatic USB-RS485 binding (Phase 8.1)

## User workflow

Existing Connections remain **Manual** with the same serial_port after migration 0009_serial_binding.
Manual accepts COM names or Linux paths as before. In Connections -> Edit -> Modbus RTU choose
**Auto detect**, then select an adapter discovered by the worker. Its current COM name is shown
only to help identify the physical adapter. Save USB identity once; serial_port must be null in Auto.
Baud rate, parity, stop/data bits and timeout remain configured exactly as in Manual mode.

Stored fields: serial_port_mode (manual/auto), usb_vid and usb_pid (integers 0..65535, UI displays hex),
usb_serial_number, usb_hardware_id, usb_manufacturer, usb_product, serial_probe_enabled (false by
default). Manufacturer/product are descriptive labels, not hardcoded brand filters. Auto requires
VID/PID; adapters without USB metadata can continue in Manual. TCP does not accept USB settings.
PATCH validates the merged record; switching to Manual clears identity/probe fields explicitly.

## Matching and confidence

The worker uses [pySerial enumeration](https://pyserial.readthedocs.io/en/latest/tools.html#serial.tools.list_ports).
It only considers enumerated serial ports with the configured USB VID/PID; no scanning HID, network,
Bluetooth or arbitrary COM ranges. Matching order:

1. A configured serial number is a hard constraint. One matching serial -> MATCHED_BY_SERIAL.
   If that serial is missing, report NOT_FOUND; never silently weaken it to a different serial.
2. Exact useful hardware ID distinguishes candidates (e.g. a USB location/interface suffix).
   Generic VID/PID-only hardware strings are not unique identity. Duplicate serials may be
   distinguished by useful hardware ID. Hardware locations can change when moving USB sockets.
3. If only one VID/PID candidate exists, metadata-only mode reports MATCHED_BY_HARDWARE_ID.
   **This identifies the available adapter type, not a guaranteed unique physical unit.** For
   adapters without unique serials, enable read-only probing to confirm the configured bus profile.
4. Multiple candidates without a unique identity -> AMBIGUOUS. Never select the first COM port.
   Optional probing resolves ambiguity or verifies a lone weak VID/PID match.

Runtime Connection status exposes detected_port, detection_status (MATCHED_BY_SERIAL,
MATCHED_BY_HARDWARE_ID, MATCHED_BY_MODBUS_PROBE, AMBIGUOUS, NOT_FOUND, ERROR), detected_at and
an actionable detection_error. Null status means not detected yet/manual. DISABLED applies to
connection state. Status API hides a stale resolved port when worker/configuration is not current.
Static identity never gets overwritten with the transient port.

## Read-only probing

Enable `Allow read-only Modbus probe if ambiguous` deliberately. No addresses/slaves are invented:
one deterministic enabled readable Tag per configured enabled slave with Tags is selected by Tag ID.
Every selected slave must answer its configured read and decode successfully. All four existing
read functions are supported; coil reads do not write coils. Encoding/count/address come from Tags.
An adapter must uniquely pass the complete selected profile; two responders remain AMBIGUOUS.
A bus where a selected slave is unavailable is not considered a match. Without eligible Tags,
report that safe identification is unavailable. Two buses with identical maps cannot be distinguished
by these reads; use USB identity or Manual mode. Reads are evidence, not cryptographic identity.

Probe uses the configured baud/parity/stop/data bits/timeout, zero library retries, temporary clients
closed in finally, at most 8 ports and 8 slaves, and a total SERIAL_PROBE_BUDGET_SECONDS budget
(default 10s, range 1..30). Exhausting the total budget selects nothing, even if an earlier candidate
answered. Occupied ports belonging to another enabled Connection are never probed. No writes are
called by discovery. Expected failures do not crash worker; unexpected failures are logged.

All physical port access shares canonical per-port locks (Windows COM case/prefix aliases and Linux
realpaths), in addition to the existing per-Connection lock. Polling, transport tests, write/read-back
and probes cannot overlap on the same bus. The Connection lock keeps the resolution stable for an
entire command operation, including verification. Other independent connections keep polling.

## Hotplug and re-detection

SerialBinder is a separate worker task under the existing database advisory lease. Enumeration
runs every SERIAL_SCAN_SECONDS (default 5s, range 1..300), plus changed connection config or an
explicit request. It does not enumerate per Tag read. Successful unchanged probe bindings are
cached until force-re-detect, candidate/profile changes or connection failure. Ordinary transport
reconnect uses the existing exponential backoff. A missing adapter invalidates/ closes its client;
reappearance at another port opens a new client without altering configuration versions.
A temporary COMM_ERROR while disconnected preserves prior values, then GOOD resumes on real reads.

POST /api/connections/{id}/redetect queues a PostgreSQL diagnostic request (202); it requires a
live Modbus worker and enabled Auto RTU connection. UI **Re-detect** shows pending/result through
GET /api/connections/{id}/status. No API serial access and no application restart. Existing Test
transport uses the resolved port. Opening the port still does not claim a slave read was verified.
GET /api/system/serial-ports now includes vid/pid/serial_number/hwid/manufacturer/product. No secrets.

Connection_runtime holds derived detection fields and redetect mailbox IDs. No runtime COM number
is stored as configuration. Migration downgrade refuses while Auto connections exist: first convert
them to Manual with explicit known ports. This avoids guessing a port or losing USB identity silently.

## Windows / Linux / Docker

Enumeration sees the **worker host**. Native Windows worker discovers Windows COM ports; moving an
adapter between USB sockets may change COM number. No driver installation is performed. Drivers
and the USB device must already work with the OS. Missing metadata uses Manual or conservative probing.
Linux supports /dev/ttyUSB*, /dev/ttyACM* and USB metadata; by-id aliases normalize to physical paths.
A Linux Docker worker only sees mapped devices and available container metadata. A Docker device
mapping is a fixed deployment mapping: a newly named host device may require updating/recreating the
container mapping. Auto binding cannot expose an unmapped device or bypass permissions. Keep the
existing optional Compose device override/native Windows workflow; no device mapping is hardcoded.

## Tests

Automated tests mock enumeration and clients: manual compatibility, serial/hardware/VID-PID matching,
Windows/Linux paths, no match/ambiguity, readonly probes, timeout bounds, reserved ports, lock exclusion,
unplug/replug/COM changes, config reload, re-detect and status. PostgreSQL tests validate migration and
Auto constraints in an isolated schema. UI tests cover identity selection, no saved COM in Auto,
missing adapters and re-detect feedback. Physical verification, if available, performs reads only;
unplug/replug is not claimed as physically verified unless an actual cable test was performed.


### Verification recorded before commit (2026-09-27)

- Backend: 428 passed, including isolated PostgreSQL migration upgrade/downgrade/replay and Auto
  identity constraints. `pytest tests -q --tb=short --show-capture=no` with TEST_DATABASE_URL supplied
  privately from Settings.
- Ruff: `python -m ruff check --config server/pyproject.toml server/app server/alembic tests` passed.
- Frontend: `npm --prefix frontend run test` ? 55 passed in 10 files. Typecheck, ESLint and production
  build passed. Vite reports the existing main-chunk size warning (approximately 503 kB minified).
- `docker compose config --quiet` and API/worker/frontend image builds passed.
- `python tests/compose_modbus_smoke.py` passed TCP reads, grouped telemetry, history/charts,
  WebSocket, configuration changes, disconnect/recovery and runtime diagnostics.
- `python tests/compose_commands_smoke.py` passed simulator/manual UI and software TCP write/read-back
  regressions; no physical writes. Both disposable projects and fixture databases were removed.
- Physical adapter metadata was read successfully on the Windows worker host; its unique USB serial
  was available and existing sensor/relay telemetry was GOOD. Actual production Auto-mode conversion
  and physical unplug/replug verification were not performed before this commit. COM renumbering and
  reconnect are covered by injected enumeration/client tests.

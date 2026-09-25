# Manual commands and verified writes (Phase 6)

All physical control actions go through PostgreSQL `commands`. Only the worker command processor
calls PyModbus write methods. The API validates/enqueues; the frontend never changes actual values
optimistically. Automation, schedules, alarms, authentication and permissions are not implemented.
Command records provide a durable action record, but **not authenticated actor attribution**.
Keep the current localhost-only deployment; the master switch is not an authorization system.

## Enabling control

`MODBUS_WRITES_ENABLED=false` is the default, on the **worker**. It has no effect on reads.
Set it true only for an explicitly configured writable test actuator, then restart that worker.
For a native Windows worker, use `$env:MODBUS_WRITES_ENABLED='true'` in its terminal; changing API
settings alone does not enable physical writes. Worker heartbeat reports the actual switch to the UI.
Old/offline workers cannot accept new commands. Simulator commands do not require the physical switch.
There is no fallback between simulator and real mode.

Tags must be enabled and writable, with enabled Device and Connection. Supported targets:

- Coil: a JSON boolean, function 05, followed by function 01 read-back.
- Holding register: uint16/int16 (function 06), uint32/int32/float32/uint64/int64/float64 (function 16),
  followed by function 03 read-back of the derived 1/2/4 registers.
- Input registers/discrete inputs are never writable. A writable flag on a Tag does not bypass the
  master switch or verification. No broadcast writes, masks, custom functions or device resets.

Encoder inversion is `raw = (engineering - offset) / scale`, then packing the configured raw type,
byte order within words and order of complete words. Zero scale, nonfinite/out-of-range values, and
fractional raw integers are rejected rather than silently rounded. Float encoding rounds to IEEE
precision; the encoded value must also respect the Tag's engineering min/max limits.

## Lifecycle and persistence

`QUEUED -> EXECUTING -> VERIFYING -> SUCCESS | FAILED`. Unclaimed commands can become CANCELLED or
EXPIRED. Only successful read-back can produce SUCCESS. A valid mismatching reading produces FAILED,
stores the actual verified value and updates current/history/WebSocket with that actual reading.
Verification failure does not undo a device action. A communication error never substitutes fake zero.

The API stores requested value, previous current value at enqueue, source=manual, source mode, three
configuration versions, request UUID, expiry and timestamps. Numeric/boolean fields are relational
typed columns; numeric API command values are exact decimal strings to preserve uint64/browser precision.
Responses include Tag/Device names (current metadata), verified value, attempts, status/error and revision.
There is no command deletion endpoint: retained command FKs block Tag deletion with HTTP 409.

The sole worker claims with `SELECT ... FOR UPDATE SKIP LOCKED` and commits EXECUTING before I/O.
The existing database advisory lease still enforces one worker owner. The processor rechecks enable
flags, writable, type/limits, master switch, source mode, expiry and all configuration versions.
Any configuration change requires a fresh command; queued commands cannot silently target a changed
slave, address or encoding. Configuration rows remain share-locked over the bounded transport operation,
so a concurrent configuration edit waits until that operation completes.

The existing connection client and lock cover the entire write/read-back sequence, including all
slave IDs on an RTU bus. There is no separate transport path. Commands execute sequentially in this
phase; ordinary polling continues on independent connections. A slow command can delay later commands.
Read persistence compares acquisition timestamps so an older pending poll cannot overwrite read-back.
Physical I/O and SQL cannot form one atomic transaction: a database failure after a device action may
leave its outcome unknown. Do not infer exactly-once physical execution from queue durability.

## Verification and retry rules

Booleans and integer engineering values compare exactly. Floating comparison uses the raw requested
magnitude, twice its IEEE epsilon (2^-23 for float32, 2^-52 for float64), scaled into engineering units,
with half a raw subnormal as a lower bound. Large offsets do not inflate tolerance. A mismatch is never
retried and never triggers an automatic compensating write.

`COMMAND_MAX_ATTEMPTS=3` bounds communication attempts. `COMMAND_RETRY_SECONDS=1` delays attempts by
base delay times attempt number; connection-manager backoff still applies. Before any send, transient
connection failure may retry. **After entering a write call, no second write is sent**, even if its
acknowledgement is lost: subsequent attempts only read back. Configuration/encoding/protocol rejection
and mismatch do not retry. Failed read-back reports that the physical action may have occurred.

`COMMAND_MAX_AGE_SECONDS=60` sets enqueue expiry; the worker also applies its own maximum age. Expiry
is checked before transmission, including after waiting for the transport. Expired work is not sent.
On worker restart, previous EXECUTING/VERIFYING rows become FAILED with an unknown-outcome message;
they are never replayed. The operator must inspect actual values before issuing a new request.

## API and live events

- `POST /api/tags/{id}/commands`: `{ "value": "12.5", "request_id": "<UUID>", "confirm_physical": true }`.
  Returns 202. Boolean targets use true/false, not strings. Physical mode requires confirmation.
  Supply a stable request UUID when retrying an HTTP request; duplicate matching requests return the
  original command. A conflicting UUID returns 409. Only manual source can be submitted.
- `GET /api/commands`: bounded list, newest first; status, device_id, tag_id, request_id, limit (1–500,
  default 100) and offset filters. Request ID lookup can reconcile an uncertain HTTP submission.
- `GET /api/commands/{id}`: durable status snapshot.
- `POST /api/commands/{id}/cancel`: QUEUED only; executing/terminal requests return 409.

PostgreSQL `commands_changed` notifications contain only the command ID and commit with the change.
The existing API listener and `/api/ws/live` fan out `{ "type": "command_status", "data": <CommandRead> }`.
Notifications may coalesce intermediate statuses; the command row is authoritative. Existing readiness/
resync events trigger a command REST snapshot. Frontend merging rejects lower command revisions.
No second socket/broker is introduced. Current-value notifications retain their existing format.

## Interface and development tests

Writable Tag details show actual value/quality separately from requested value, verified value and
command status. Numeric requests remain decimal strings; coils offer ON/OFF. Physical requests require
a confirmation dialog. The Commands page shows the latest 100 filtered commands and queued cancellation.

Simulator commands use the same queue/encoder/verification/current/history/live paths in the worker.
A successful simulated control holds the decoded setpoint until configuration changes or worker restart;
other simulator Tags keep their gradual random walks. This is development state, not a persisted physical
actuator model. Failure probability applies to command communication/read-back as well as polling.

Run `python tests/compose_commands_smoke.py` after building Compose images (browser extra and Edge
required). It uses an isolated Compose project/database: coil OFF -> ON, numeric and exact uint64 writes,
history/WebSocket, actual mobile browser controls, then a test-only PyModbus TCP server. The software
server has test fixtures only; the test never uses the running project's device configuration. Cleanup
removes the isolated volume, not development data.

## Physical relay checklist (not hardware-verified)

1. Use an explicitly identified test relay with a manufacturer-confirmed writable coil/register address.
2. Confirm slave ID, zero-based address, supported write function and electrical load state.
3. Keep existing SHT20 sensor Tags non-writable. Never guess actuator registers or use sensor configuration
   registers as write tests.
4. Start with the master switch false; verify normal reads and current quality first.
5. Enable writes only on the intended worker, submit one confirmed manual command, and inspect read-back
   plus the actual relay. Register read-back proves a value, not mechanical actuation or external safety.
6. Turn the master switch off and restart the worker when testing is complete.

No physical relay write was performed during Phase 6 implementation.

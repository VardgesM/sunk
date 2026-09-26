# Modbus reads, verified commands and simulator

Phase 5 uses PyModbus 3.13.1 in the worker only. Async TCP and serial clients use the installed
keyword-only `count` and `device_id` read APIs. API/frontend never instantiate transport clients.
All transport settings, slave IDs, register definitions and polling intervals come from PostgreSQL.

## Addressing and validation decisions

`tags.address` is a **zero-based Modbus protocol offset**, in the range 0–65535. The UI explicitly
labels it zero-based. Vendor manuals may label a holding register `40001`; in the common reference
number convention that means holding-register offset `0`. These representations are not universal.
Users must consult the device manual and enter the actual protocol offset and register type separately.
**No 40001-style interpretation or automatic subtraction is implemented.** Entering `40001` stores
the literal offset 40001. A multi-register type must fit completely through offset 65535.

- `coil` and `discrete_input` use `bool` in this phase; packed bits inside numeric registers are deferred.
- `input_register` and `holding_register` use uint16/int16, uint32/int32/float32, or uint64/int64/float64.
  These occupy one, two, or four registers respectively.
- Byte order and word order independently accept `big`/`little`. Numeric forms expose byte order,
  and multi-register types also expose word order. Stored order fields on boolean objects are inert.
- Only coils and holding registers may be marked writable. Physical writes additionally require
  the worker master switch, a confirmed queued command and read-back verification.
- Scale defaults to 1 and offset to 0; the numeric transform is `raw * scale + offset`.
  Finite scale, offset, and optional limits are stored; min must be <= max. Numeric decoding is applied before current-value and history persistence.
- Positive poll intervals and enabled flags control collection. `history_enabled` and
  history policy now control separate historical storage. Real I/O requires explicit modbus source mode.
- For the current unicast scope, **slave IDs are 1–247 for both RTU and TCP**. Broadcast 0 and special
  TCP unit identifiers 248–255 are deferred. A connection/slave-ID pair must be unique.

RTU requires a manually entered serial port plus positive baud rate, parity N/E/O, stop bits 1/1.5/2,
and data bits 7/8. UI defaults are editable and saved in PostgreSQL. Opening a port may fail if the driver does not support the configured settings. TCP requires an IP address or hostname without URL
scheme/port; omitted TCP port defaults to 502. Transport-specific fields from the other protocol must
be null. Switching protocol must provide the new fields and clear the old fields in the same PATCH.
All connections have a positive timeout in milliseconds. Worker transport tests report reachability without claiming a slave was read.

## Development simulator

Set `TELEMETRY_SOURCE=simulator` on the worker. No serial ports or TCP endpoints are opened. Behavior
depends on data type, bounds, scale and offset, never names/keys. All three enabled flags (tag, device,
connection) apply. `SIMULATOR_FAILURE_PROBABILITY` (0–1, default 0) injects communication failures.

Numeric simulation walks gradually in decoded raw space and returns engineering values using
`raw * scale + offset`, exactly once. Configured min/max are engineering limits: their inverse transform
is intersected with the data type's raw domain, including negative/zero scales. Integer raw samples
remain integral. Missing limits use a small development window (up to 100 raw units), clamped to the
admissible domain. Steps are at most 2% of the window (one raw unit minimum for integers). Configuration
changes reset the walk. Zero scale yields the constant offset; impossible limits produce BAD.
Boolean samples randomly toggle, respect bounds interpreted as 0/1, and ignore numeric scale/offset.

Each `Reading` carries a typed engineering value, UTC acquisition time and pre-scaling raw diagnostic
text. Decimal arithmetic is used; this is not a bit-accurate Modbus float codec. The real Modbus source decodes and scales before returning the same contract. Byte/word ordering remains stored
configuration, without a simulated wire encoding. Simulator commands never contact devices.

Injected failures set COMM_ERROR and retain prior value/time. Source exceptions are logged and set BAD
without stopping other tags. The next success clears errors and sets GOOD. A stopped worker leads to
STALE after the configured number of missed periods; the API performs this quality-only maintenance.

Reference: [Modbus Organization specifications](https://www.modbus.org/modbus-specifications)
define the protocol addressing and serial unicast scope; the limits above describe this application's
current supported subset.

## Reads, decoding and scheduling

The manager creates one reusable client per enabled Connection. Calls map directly to
`read_coils`, `read_discrete_inputs`, `read_input_registers`, and `read_holding_registers`.
The Device supplies `device_id`; the Tag supplies the zero-based address and derived count.
16/32/64-bit types consume 1/2/4 registers; bit objects consume one bit. Polling never calls write methods.

The decoder reverses bytes inside each 16-bit word for little byte order, and reverses whole
words for little word order, then decodes signed/unsigned integers or IEEE floats. All four order
combinations are tested. Nonfinite floats, wrong response lengths and malformed words are BAD.
Engineering values use Decimal arithmetic for `raw * scale + offset` exactly once. Real readings
are not clamped to configured min/max: these are not alarms or physical measurement corrections.
Raw register words and the decoded raw value remain available as diagnostic text.

Due tags on the same device/register type are grouped across contiguous or overlapping addresses,
without gaps, up to 125 registers or 2000 bits. Each tag retains independent decoding, history and
poll interval. Invalid group responses mark the affected group BAD. Future tags are never read early.

The scheduler allows one in-flight read per connection, up to 32 independent connections by default.
The manager also locks each connection, including transport tests. RTU buses never receive concurrent
requests; TCP uses the same conservative serialization. Duplicate enabled RTU port paths are rejected
(after path normalization). Operators must not configure aliases for the same physical bus.
A PostgreSQL advisory session lock enforces a single worker per database, including native workers.
Losing that session cancels acquisition and closes clients before retrying ownership.

Configuration refresh (default 2 seconds) cancels affected reads and replaces clients when transport
settings change. Disabled connections/devices/tags are not read. Shutdown closes every client.
Opening and response watchdogs have separate budgets; PyModbus retries and automatic reconnect are disabled so the manager owns
bounded exponential reconnect backoff (default 1 to 30 seconds). A missing slave on an open
transport receives its own backoff and does not close the bus or suppress other slaves. A slow/unavailable bus does not block
independent connections. INFO logs cover lifecycle/configuration; successful samples are not logged at INFO.

## Quality, source and runtime status

Transport timeout/refusal/no-response produces COMM_ERROR; an exception response or invalid decoded
payload produces BAD. Both preserve the last successful value/source/time and store a readable error.
Success clears the error and sets GOOD. Existing per-tag stale detection and DISABLED behavior remain.
Current/history values identify simulator, modbus_rtu or modbus_tcp; unknown legacy source stays null.
A source switch inserts a value-free BAD history boundary before the next successful sample.

`GET /api/system/runtime` reports worker mode/heartbeat. Connections have separate persistent runtime
rows. CONNECTED means transport availability, not that every slave works; last_success is an actual
successful response. Stale worker state becomes DISCONNECTED. Device status is derived from enabled
Tags: all GOOD is ONLINE; all COMM_ERROR/STALE is OFFLINE; mixed failures or BAD is DEGRADED; no evidence
is UNKNOWN; disabled configuration is DISABLED. Status describes observed readings, not a safety guarantee.

`POST /api/connections/{id}/test` returns 202 and a token. Poll the corresponding GET `/test` for the
result. The worker opens the configured transport under its normal lock; no invented register is read.
RTU success means only that the serial port opened; TCP success means only that a connection opened.
Tests require a live worker in modbus mode and expire after 30 seconds/configuration changes.
`GET /api/system/serial-ports` returns worker-host pyserial discovery, not API-host or browser ports.
Manual serial entry remains available. See [deployment and first-device checklist](modbus-deployment.md)
for Windows native workers, Docker Desktop limitations, Linux device mappings and software test commands.

The automated suite does not claim physical RTU verification. Separate local bench checks have
verified configured SHT20 reads and unloaded relay command read-back; those checks do not verify
electrical contact behavior. Unit tests cover serial construction/serialization and
transport-independent decoding; the software TCP server covers all read functions, slave addressing,
failure and recovery. Manual commands are implemented in Phase 6; Automation uses that queue in Phase 7; authorization remains
deferred. Commands are durably recorded but do not yet identify an authenticated requester.

## Phase 6 write extension

The read-only Phase 5 transport now also serves the command processor under its existing per-connection
lock. Physical writes remain off by default. Coils use write_coil; one-word registers use write_register;
longer numeric values use write_registers. Only the command processor may call them, and every successful
command requires decoded read-back. See [write safety and encoding](commands.md).

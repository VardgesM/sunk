# Real Modbus deployment and first-device setup

## Source mode

`TELEMETRY_SOURCE` accepts `disabled`, `simulator`, or `modbus`. Unset/empty preserves the earlier
`SIMULATOR_ENABLED` flag (true => simulator, false => disabled). New installations should select a mode
explicitly. `TELEMETRY_SOURCE=modbus` together with `SIMULATOR_ENABLED=true` is rejected at startup.
There is no automatic fallback from a failed real device to simulation. Changing mode requires a
worker restart; changing Connection/Device/Tag configuration does not.

For real reads, set these local environment settings and recreate the worker:

```dotenv
TELEMETRY_SOURCE=modbus
SIMULATOR_ENABLED=false
MODBUS_BACKOFF_INITIAL_SECONDS=1
MODBUS_BACKOFF_MAX_SECONDS=30
WORKER_MAX_PARALLEL_CONNECTIONS=32
```

```sh
docker compose up --build -d --wait
```

RTU and TCP are selected separately by each stored Connection protocol. There are no built-in
device definitions, serial ports, addresses, or slave IDs. The shell labels simulation explicitly.
Each current/history GOOD sample also identifies `simulator`, `modbus_rtu`, or `modbus_tcp`; migrated
older samples remain unknown. Retained values keep their original source during errors. Switching
source inserts a BAD boundary before the next successful historical sample, preventing a continuous
chart line from silently joining simulated and real values.

## Windows native worker with Docker API/database/frontend

Linux containers under Docker Desktop do not see Windows COM ports as native Windows serial ports.
Merely adding a COM name to Connection configuration does not map hardware into that Linux VM.
Docker documents [USB/IP options and platform restrictions](https://docs.docker.com/desktop/features/usbip/);
this project does not install drivers or configure USB forwarding.

The straightforward Windows RTU workflow is to run the shared Python worker natively:

```powershell
# At the repository root; existing .env credentials remain in that uncommitted file.
docker compose stop worker
docker compose up -d --wait postgres api frontend
.\.venv\Scripts\python.exe -m pip install -e "./server[dev]"
$env:POSTGRES_HOST='localhost'
# POSTGRES_PORT must match your published PostgreSQL port in .env.
$env:TELEMETRY_SOURCE='modbus'
$env:SIMULATOR_ENABLED='false'
.\.venv\Scripts\python.exe -m app.worker
```

The worker uses the same database/configuration, now enumerating the Windows host's serial ports.
Use the discovered port or manually enter the port reported by the operating system. Ctrl+C closes
clients cleanly. Stop the native worker before restarting the container worker. One database advisory
lease prevents accidental simultaneous workers; a second process logs an ownership error and waits.
Database interruptions cancel collection and close clients before ownership is reacquired. The lease
does not coordinate separate databases or unrelated Modbus master applications: do not run those on
the same physical bus.

Other development options are Modbus TCP with containerized workers, or deployment on native Linux,
a Raspberry Pi, or an industrial PC with local serial access. No physical RTU hardware or Windows
virtual serial pair was verified during this phase.

## Optional Linux serial mapping

Default Compose contains no hardware mapping and works without serial devices. On a Linux deployment,
create an uncommitted `compose.rtu.local.yml` with explicit environment-supplied paths and permissions:

```yaml
services:
  worker:
    devices:
      - "${RTU_HOST_DEVICE}:${RTU_CONTAINER_DEVICE}"
    group_add:
      - "${RTU_DEVICE_GID}"
```

Set RTU_HOST_DEVICE to your adapter's actual host path (a stable `/dev/serial/by-id/...` path is useful),
RTU_CONTAINER_DEVICE to its chosen path inside the worker, and RTU_DEVICE_GID to the numeric host group
owning the device. These are deployment values, not application defaults. Store the **container path**
in the Connection form. Grant the non-root worker appropriate serial permissions; no privileged
container is required by the application. Then run:

```sh
docker compose -f docker-compose.yml -f compose.rtu.local.yml up -d --build --wait
```

See [Compose devices/group mappings](https://docs.docker.com/reference/compose-file/services/).
Serial discovery returns only ports visible to the worker, not an inventory of the API host.
Two logical Connections must not represent the same physical bus. Matching normalized paths/symlink
aliases are rejected; the operator must also avoid wiring two independent adapters onto one bus as
competing masters.

## First real device checklist

Confirm these against the vendor documentation before enabling collection:

1. Transport: RTU or TCP; actual serial port or IP/hostname and TCP port.
2. RTU baud rate, parity, stop bits, data bits; adapter driver/permissions, RS-485 wiring/termination.
3. Device slave/unit ID (current supported unicast scope: 1–247).
4. Vendor register map and object type: coil, discrete input, input register, holding register.
5. Zero-based protocol offset. A manual's holding register 40001 often corresponds to offset 0,
   but confirm the vendor's convention yourself. The application never subtracts 40001 automatically.
6. Data type and required width (derived automatically): 16-bit=1 word, 32-bit=2, 64-bit=4.
7. Byte order within each word, word order across the complete value, signedness and float encoding.
8. Scale, offset and unit. Engineering value is decoded raw × scale + offset.
9. A realistic poll interval and timeout for the bus/device; history policy/retention independently.
10. Use Test transport, then check actual Tag quality/value against a known device reading.

**Example only:** if a vendor explicitly documents a big-endian unsigned 16-bit temperature value
in tenths of a degree at holding reference 40001, configure holding_register / offset 0 / uint16 /
scale 0.1 and the documented unit. Do not apply this example to a different register map. Nothing is
automatically inserted into the database. Writable flags alone do not enable physical control;
see the [master write switch and verified command pipeline](commands.md).

## Verification without hardware

The test-only PyModbus software server defines deterministic words/bits and two slave IDs. It is
never imported by application startup or seeded into a production database.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_modbus.py tests/test_runtime.py -q
docker compose build api worker frontend
.\.venv\Scripts\python.exe tests/compose_modbus_smoke.py
```

The final command uses a randomly named isolated Compose project/database, dynamically allocated
host ports, and the optional `tests/docker-compose.modbus-test.yml`. It verifies all read functions,
source/typed storage/history/WebSockets, actual browser charts, connection testing, configuration
reload, server-stop failure and restart recovery, and removes its test volume afterward. It requires
the browser extra and Edge. It does not change the running development project's source mode.
RTU parameter mapping/serialization and all decoding permutations are unit-tested; physical serial
timing, adapter drivers, cable/CRC behavior and actual device register maps still require hardware.


## Polling failure isolation

Requests remain serialized per transport. A PyModbus 3.13.1 no-response exception while the
transport remains connected delays only that slave, using the configured exponential backoff.
Other slaves continue on the existing client. A closed transport, port error or outer watchdog
failure still reconnects the transport. Connection opening has its own timeout; response watchdogs
allow one second beyond the library timeout so normal missing-slave timeouts can finish cleanly.
Command writes retain their existing no-replay and verification behavior.

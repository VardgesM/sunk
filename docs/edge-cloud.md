# Edge / Cloud synchronization (Phase 11)

## Deployment roles

`APPLICATION_MODE=standalone` preserves the local application. `edge` keeps polling,
Commands, Automation, Alarms and history local and adds an independent `python -m app.sync`
process. `cloud` serves remote users and mirrors; it never runs a transport worker.
Use separate PostgreSQL databases and separate environment files. Do not turn an Edge
database into a Cloud database. Persisted installation identity/mode reject implicit changes.

Only application HTTPS traffic crosses the network. PostgreSQL is bound to localhost
in Compose; never expose it publicly. Put the Cloud API/frontend behind a TLS reverse
proxy for a VPS deployment and set `AUTH_COOKIE_SECURE=true`. Provisioning a VPS and
certificates is outside this phase. `SYNC_ALLOW_INSECURE_HTTP=true` is for isolated tests only.

## Start

1. Copy `.env.example` separately to `.env.cloud` and `.env.edge` (never commit either).
   Set distinct database credentials and host ports if both stacks share a machine.
2. Cloud: set `APPLICATION_MODE=cloud`, then run:

   ```sh
   docker compose --env-file .env.cloud -p monitor-cloud -f docker-compose.yml -f docker-compose.cloud.yml up --build -d
   docker compose --env-file .env.cloud -p monitor-cloud -f docker-compose.yml -f docker-compose.cloud.yml exec api python -m app.bootstrap
   ```

3. Generate a stable installation UUID and a random machine token (at least 32 characters).
   Log into Cloud as ADMIN, open Settings/System and register that UUID, name and token.
   Cloud stores only its SHA-256 digest. Keep the token in the Edge environment as
   `SYNC_TOKEN`; it is never a human password and never returned by APIs.
4. Edge: set `APPLICATION_MODE=edge`, `EDGE_INSTALLATION_ID` to that UUID,
   `SYNC_CLOUD_URL=https://your-cloud-host/` and `SYNC_TOKEN`. Select the existing
   `TELEMETRY_SOURCE` explicitly. Physical writes remain disabled by default.

   ```sh
   docker compose --env-file .env.edge -p monitor-edge -f docker-compose.yml -f docker-compose.edge.yml --profile edge up --build -d
   ```

Both APIs apply migration `0012_edge_cloud` at startup. Back up an existing database
before upgrading. Initial Edge capture briefly locks synchronized tables and queues
existing records atomically; allow extra time/disk for a large history database.

### Native Windows worker

Keep the existing native RTU workflow. Run only PostgreSQL/API/frontend in Docker with
the Edge override; do not start the container worker. In the native worker and sync
process environments set `APPLICATION_MODE=edge`, the same installation UUID and
`POSTGRES_HOST=127.0.0.1` with the published database port. Run:

```sh
python -m app.worker
python -m app.sync
```

These are separate processes sharing the same Edge database. The sync process can also
run in Docker while the worker is native; only the worker needs USB/COM access. Run one
sync process per database (enforced by an advisory lease). Never run a second worker.

## Durable outbox and recovery

PostgreSQL transaction triggers capture an explicit allowlist of metadata/current/history,
alarm, command, runtime status and Automation records into `sync_outbox`. A rolled-back
original transaction cannot leave a sync event. Events have UUIDs and local sequence numbers.
The first Edge initialization captures existing rows using SQL and then enables capture
in the same transaction. No passwords, sessions, user records, Telegram tokens or machine
secrets are included. Serial enumeration and worker host details are excluded.

Each cycle polls durable remote requests and sends a batch. `SYNC_INTERVAL_SECONDS`
defaults to 2; `SYNC_BATCH_SIZE` defaults to 100 (6?500). Capacity is reserved for metadata,
command results, alarms, current/status, Automation, and history lanes, in that priority
order. History cannot monopolize control delivery. Missing dependencies are retained and
retried after a short delay so later parent metadata can progress. Invalid rows remain
queued with an error indication rather than being silently dropped.

A network failure leaves rows locally and increases retry delay up to
`SYNC_BACKOFF_MAX_SECONDS` (60 default). `SYNC_TIMEOUT_SECONDS` bounds HTTP calls.
Only explicitly acknowledged event IDs are removed. PostgreSQL receipts make an upload
retry harmless. A per-entity sequence prevents late replay overwriting newer state.
Outages can grow disk usage: monitor the pending count and disk capacity; there is no
silent backlog deletion or guessed deployment limit. Cloud receipts and identity mappings also
consume storage and are retained for idempotency; history retention is not a receipt cleanup policy.
Cloud recovery drains the backlog.
Local telemetry, control and Automation do not wait for any HTTP call.

## Metadata and identity

Cloud maps `(installation UUID, entity, original primary key)` to a stable UUID5 public ID
and a Cloud-local relational primary key. This isolates equal integer IDs from different
Edges. `/api/sync/mappings?edge_id=...&entity=tags` exposes the safe mapping.
Tag keys are namespaced; dashboard names include the Edge name. Source names, units,
bindings and timestamps are retained. Cloud configuration is read-only even for ADMIN;
users and machine enrollment remain Cloud-local. Password hashes never synchronize.

Edge configuration deletes retain disabled Cloud tombstones where history needs its FK.
Dashboard layout/binding deletes synchronize normally. Edge retention does not delete
Cloud history. There is no bidirectional configuration conflict resolution.

## Current values, history and browser events

Cloud stores normal native typed current/history rows and reuses existing REST/chart APIs.
Original source and recorded timestamps are preserved. Cloud ingestion sends the existing
transactional PostgreSQL NOTIFY events for current values, Commands and Alarms. Browsers
use the existing authenticated WebSocket and revision-aware snapshot merge. Edge-to-Cloud
HTTP batching and Cloud-to-browser WebSocket are separate links.

Cloud can mark outdated current values STALE, but never generates historical samples or
runs local Alarm/Automation engines. Network delay can make Cloud values stale while Edge
continues normally. All machines should have synchronized UTC clocks (NTP).

## Remote Commands and Alarm acknowledgement

Existing role checks apply: VIEWER cannot control or acknowledge; OPERATOR/ADMIN can.
Cloud creates a durable correlated request and an existing Command in PENDING_EDGE.
Delivery changes it to DELIVERED. Edge records the request once in `remote_inbox`, checks
expiry, frozen target versions, mode, enabled/writable state and worker availability,
then calls the existing command enqueue service. The worker alone executes and verifies.
The lifecycle continues QUEUED ? EXECUTING ? VERIFYING ? SUCCESS/FAILED.

`REMOTE_COMMAND_MAX_AGE_SECONDS` defaults to 60. Expired undelivered requests never execute.
Repeated delivery reuses the inbox result, never enqueues twice. A delivered request with
an unknown result remains visible until Edge reconciliation; Cloud does not guess whether
an uncertain physical action occurred. Commands interrupted during physical execution keep
the existing no-replay safety. Cloud cancellation is rejected because delivery might
already have occurred. Physical confirmation and `MODBUS_WRITES_ENABLED` remain mandatory.

Cloud user ID/name are snapshotted for audit. They are not mapped to a fabricated Edge
human account. Automation remains local with source=automation and no interactive session.
Remote acknowledgement similarly uses a durable request; the Alarm stays ACTIVE in Cloud
until the Edge result/event arrives. Delivery errors are visible in Settings/System.

## Machine API and status

Version 1 endpoints under `/api/sync/v1`: POST `heartbeat`, POST `events`, GET `requests`.
They require an enabled registered UUID in `X-Edge-ID` and `Authorization: Bearer ...`.
A token has access only to its installation. Payload entities/columns are allowlisted;
there is no arbitrary SQL/database access. ADMIN can rotate or disable credentials through
POST `/api/sync/installations`; update the Edge environment after rotation.

Authenticated `/api/sync/status` reports mode, pending count, last success and safe error.
Cloud Edge status is ONLINE for a heartbeat within 30 seconds, otherwise OFFLINE (or DISABLED).
`/api/sync/requests` exposes recent remote delivery results. Settings/System displays these
states without relying only on colors. Cloud Modbus configuration mutation is blocked by
the backend, not just hidden controls.

## Verification

`tests/test_sync.py` uses two disposable PostgreSQL schemas with authenticated APIs.
`python tests/compose_sync_smoke.py` starts separate disposable Edge and Cloud databases,
uses simulator-only telemetry/Automation, interrupts Cloud, checks catch-up, history,
remote command read-back/idempotency, acknowledgement, WebSocket and mobile dashboard/chart.
It removes its fixtures and volumes. It never writes physical relays or sends Telegram.
No real VPS, WAN outage or physical remote-control test is implied by these checks.

## Production preparation (11.1)

The Compose commands above describe local/development deployment. For an Ubuntu VPS use [the dedicated production stack](production-cloud.md), which has no worker service or public database/API port. `APP_MODE` is now the canonical environment name; legacy `APPLICATION_MODE` remains supported, with APP_MODE taking precedence. Remote physical requests now also require Cloud MODBUS_WRITES_ENABLED=true; leave it false for initial monitoring. Edge execution safety is unchanged.

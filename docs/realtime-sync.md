# Realtime current state and durable history (Phase 11.2)

## Why the old queue lagged

Migration 0012 captured every current-value and runtime-row update as a new outbox
record. Although priority lanes reserved some capacity for current values, each lane
replayed oldest-first. Polling and worker heartbeats could produce rows faster than
that lane drained. Cloud was correctly displaying old snapshots, sometimes including
an old simulator source, while the newest real value waited behind them. History was
already independent; current refreshes were unnecessarily durable snapshots.

## Latest state versus durable records

`tag_current_values` still contains one typed latest state per Tag. Edge PostgreSQL
atomically UPSERTs its pending sync row by `coalesce_key=tag_current_values:<tag_id>`.
There is one persisted installation identity per Edge database, so this is one pending
state per installation + Tag. Four unsent readings 24.1, 24.2, 24.4, 24.6 become one
pending reading: 24.6. Connection and worker runtime snapshots coalesce the same way.

Every replacement obtains a new outbox sequence and event UUID. An acknowledgement
or deferred retry for an older UUID cannot delete or delay its replacement. Capture
and the local data change share one transaction. No HTTP call runs in the worker.

History, Alarm events, Commands/results, Automation events and metadata are **not**
coalesced. Each selected history row remains durable even after Edge retention deletes
its original row. No history is derived from current-value packets on Cloud. Intermediate
current quality changes may coalesce, but existing history quality markers and Alarm/
Command events retain their own durable records. There is no fallback to simulator.

Cloud maps installation + Tag into its existing stable UUID/native Tag mapping. The
mapping's monotonic Edge outbox sequence rejects old/duplicate current packets, including
GOOD -> COMM_ERROR and COMM_ERROR -> GOOD delivered out of order. Source timestamps,
last successful source timestamp, updated timestamp, quality, typed values, source,
error and revision are preserved. Browser revisions still use the existing snapshot
and shared WebSocket merge. Cloud's local stale maintenance may mark delayed values
STALE; it does not manufacture history.

Durable event UUIDs retain Cloud receipts for retry idempotency. Current/runtime packets
use their mapping sequence (worker runtime uses heartbeat timestamp) instead of creating
an endless receipt per refresh. Existing old receipts are retained. History identity
mappings and receipts continue consuming storage intentionally.

## Batching and latency

Each cycle does the following, without a per-Tag HTTP request:

1. Heartbeat and retrieve remote requests (existing expiry, permissions and queue safety).
2. Bounded metadata/command/alarm/Automation event batch with reserved capacity per lane.
   Metadata goes first inside the batch so relational dependencies can resolve.
3. Freshly select and upload latest current states.
4. Upload runtime snapshots, worker provenance first.
5. Upload one bounded historical batch.

Current batches rotate stable Tag keys so continuously updating Tags cannot monopolize
a small batch. The cursor is only a scheduling hint; a restart may restart the rotation
but cannot lose pending state.

The next cycle waits only the remaining configured interval, rather than adding a full
interval after processing. Under normal network/load conditions current latency is about
one sync interval plus request/processing time. It is not a hard realtime guarantee:
network timeouts/backoff, first metadata enrollment, more Tags than batch capacity and
server throughput can extend it. A history FIFO never sits ahead of current states.

| Setting | Default / purpose |
| --- | --- |
| `SYNC_INTERVAL_SECONDS` | 2 seconds between cycle starts where processing permits |
| `SYNC_BATCH_SIZE` | 100; existing metadata/event and runtime capacity, range 6..500 |
| `SYNC_CURRENT_BATCH_SIZE` | Unset: use SYNC_BATCH_SIZE; explicit range 1..500 |
| `SYNC_HISTORY_BATCH_SIZE` | Unset: use SYNC_BATCH_SIZE; explicit range 1..500 |
| `SYNC_TIMEOUT_SECONDS` | Existing bounded request timeout, default 10 seconds |
| `SYNC_BACKOFF_MAX_SECONDS` | Existing capped network failure backoff, default 60 seconds |

Example Edge configuration (no credentials):

```dotenv
SYNC_INTERVAL_SECONDS=2
SYNC_BATCH_SIZE=100
SYNC_CURRENT_BATCH_SIZE=100
SYNC_HISTORY_BATCH_SIZE=100
MODBUS_WRITES_ENABLED=false
```

History backlog does not consume the current batch allowance. New current state is
selected immediately before its upload. Missing metadata/invalid records remain pending
with deferred retries and an error indication; they are not silently discarded.

## Outages, history policy and counters

Offline: local Modbus, UI, Automation, Commands and history continue independently.
Pending current rows stay bounded by Tag count; durable history/events grow on disk.
After recovery the latest current batch precedes historical catch-up. Restarting sync
loses no pending data because no correctness state exists only in client memory.

For an environmental sensor, **poll 5 seconds / fixed history interval 60 seconds** is
one useful configuration, not a global limit or default imposed on existing Tags.
`every_sample`, `fixed_interval` and `on_change` are unchanged. History-disabled Tags
still synchronize live current values. Changing history policy is an explicit user action.

Local Settings/System and `GET /api/sync/status` now expose:

- `pending_current`: latest realtime states;
- `pending_history`: durable selected history;
- `pending_status`: replaceable runtime snapshots;
- `pending_commands`: durable Commands and remote inbox results;
- `pending_events`: Alarm/Automation events;
- `pending_metadata`: configuration dependencies;
- `pending`: their total (backward-compatible).

These counters describe the database serving that API. Cloud's local outbox is normally
empty; its ONLINE/last-seen indicator describes connected Edges, not their backlog size.
Inspect the **Edge** System page for its pending counters. Monitor disk use while offline;
there is no automatic dropping of durable history to enforce a guessed capacity.

## Migration and compatibility

New revision: `0013_realtime_sync`, after unchanged `0012_edge_cloud`.
Adds nullable unique `sync_outbox.coalesce_key` and `(entity, id)` index; replaces capture
function and initial enrollment SQL. Upgrade keeps the newest pending current/runtime
row per key, clears its deferred retry, and preserves all durable history/event rows,
UUIDs and original timestamps. Current/history application tables are unchanged.

Migration takes table locks and compacts existing rows in SQL. Plan a maintenance window
and sufficient database disk/WAL capacity for a large queue. Deleted obsolete snapshots
become reusable database space; the physical volume need not shrink immediately.
Downgrade restores append-only capture but cannot reconstruct discarded intermediate
current snapshots. It does not erase durable history/events. Never use downgrade as an
unreviewed production rollback.

Wire protocol stays version 1. Old Edge packets are accepted by upgraded Cloud; upgrade
**Cloud first**, then Edge. Both application code and schema must be upgraded together.
Do not reset the outbox sequence, installation UUID, mapping tables or database volumes.
An old database restore requires a separate recovery plan because sequences must not
move backwards relative to already-acknowledged Cloud state.

## Safe update: existing Cloud first

These are operator instructions, not actions performed by this task. Keep the existing
Compose project name, `.env.cloud`, volumes and machine registration. In the VPS shell:

```sh
cd /opt/modbus-monitor
set -e
dc() { docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml "$@"; }
umask 077
mkdir -p backups
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/cloud-$(date -u +%Y%m%dT%H%M%SZ).dump"
# Check the backup command succeeded before continuing.
git pull --ff-only
dc config --quiet
dc build
dc stop frontend api
dc run --rm migrate
# Continue only if migration succeeded.
dc up -d --wait api frontend
dc exec api alembic current
dc exec api alembic check
dc logs --tail=100 api migrate
```

Expect head `0013_realtime_sync`. Keep `MODBUS_WRITES_ENABLED=false` in Cloud environment.
Verify authenticated telemetry/WebSocket and Edge ONLINE. While Cloud is stopped Edge
continues locally and queues data. Store backups securely outside Git and test restoration
into a separate database. Do not delete volumes.

## Safe update: existing Windows-native Edge

Plan a short **local** maintenance window: stopping the worker suspends local polling and
Automation during the software update. Cloud outages alone do not require stopping it.
Keep the existing database, UUID, token, Modbus/USB configuration and startup supervisor.

1. In the existing worker and sync terminals press Ctrl+C and wait for clean exit. If
   supervised, stop those two jobs through that supervisor first. Do not terminate every
   Python process or start a second hardware worker. If sync is containerized, use the
   explicit `stop sync` command below instead of a native sync terminal.
2. From the existing repository directory in PowerShell:

```powershell
function dc { docker compose -f docker-compose.yml -f docker-compose.edge.yml @args }
dc stop api frontend
# Only if the installation uses the Docker sync service:
# dc --profile edge stop sync
New-Item -ItemType Directory -Force backups | Out-Null
$backupName = 'edge-' + (Get-Date -Format 'yyyyMMddTHHmmss') + '.dump'
# Dump to a container file first: Windows PowerShell text redirection can corrupt binary dumps.
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/phase112-edge.dump'
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
dc cp postgres:/tmp/phase112-edge.dump (Join-Path backups $backupName)
if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed' }
dc exec -T postgres rm /tmp/phase112-edge.dump
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git update failed' }
.\.venv\Scripts\python.exe -m pip install -e './server[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency update failed' }
dc build api frontend
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
# Native processes retain their existing local DB environment; preserve APP_MODE=edge.
# Keep MODBUS_WRITES_ENABLED=false. Optional new batch settings can be added to .env.
dc run --rm --no-deps api alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; leave services stopped' }
dc run --rm --no-deps api alembic current
dc run --rm --no-deps api alembic check
dc up -d --wait postgres api frontend
.\.venv\Scripts\python.exe -m app.worker
```

In another terminal with the same existing Edge environment:

```powershell
.\.venv\Scripts\python.exe -m app.sync
```

If sync was already Docker-managed, build/recreate **only sync** with
`dc --profile edge up -d --build sync` instead. For an existing Linux-container worker,
use its existing Compose/serial override; stop worker/sync/API before backup+migration,
rebuild and restart them afterwards. Never start Docker worker in addition to native RTU.

Verify head 0013, local source `modbus_rtu`/`modbus_tcp`, fresh Cloud values while history
pending decreases, and both sides' write flags remain false. Do not test physical relay
writes as part of this update. If migration fails, inspect/fix the error; preserve backups
and volumes and do not restart old writers against a partially planned upgrade.

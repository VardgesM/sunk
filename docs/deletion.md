# Configuration deletion and retained history

Deletion removes an object from **active configuration**. It does not erase evidence of previous
operation. Migration `0015_configuration_archive` adds nullable UTC `archived_at` to Locations,
Connections, Devices, Tags, Automation rules and Alarm rules. Archived operational objects are
always disabled. Their internal IDs never become the identity of a replacement object.

## What Delete does

| Object | Consequences |
| --- | --- |
| Tag | Stop polling; remove current state; archive dependent Automation/Alarm rules; detach dashboard bindings. |
| Device | Archive this device and all active Tags below it, with the same consequences as Tag deletion. |
| Connection | Archive this connection, its active Devices and their Tags. |
| Location | Archive the folder; move its child locations and devices to its parent, or root/no location. Equipment remains operational. |
| Automation rule | Archive the whole rule, preserving conditions, actions, executions and linked command history. |
| Alarm rule | Archive the rule; close open events with `clear_reason="Configuration deleted"`; retain all events. |

If a deleted Tag participates in a multi-condition rule, the **whole rule** is retired. Removing just
one condition could change the meaning of ALL/ANY and cause unintended control. Rules are never
automatically reconnected to a new Tag with the same key. Dashboard charts retain their other Tag
bindings; widgets with no remaining bindings are removed. The dashboard layout revision changes.

Pending commands for retired Tags, and pending commands from retired Automation rules, become
`CANCELLED`. Deletion waits for an in-flight write/read-back transaction under the existing transport
protection. If a communication failure releases that transaction between verification attempts,
archival can proceed; the next attempt fails validation, reports an uncertain physical outcome, and
never resends the write. A claimed command that has not entered execution must
revalidate configuration and fails if its target/rule was retired. Uncertain commands are never
replayed. Pending Telegram deliveries for retired Alarm rules are skipped; an already sending
notification cannot be recalled.

**Deleting configuration does not switch physical outputs OFF.** Put equipment into its intended
safe state through the existing verified command flow before deleting its configuration. The UI
confirmation explains the consequences; permissions, CSRF and Cloud read-only configuration rules
remain in force. No restore/unarchive or permanent history-purge UI is introduced.

## Retention, API and identifiers

- Existing DELETE routes still return 204. Repeating DELETE on an archived object is harmless;
  an unknown ID returns 404. History/references no longer cause a 409 on these routes.
- Normal configuration lists, polling and live snapshots omit archives. PATCH of an archived
  object returns 404, and new references/commands targeting it are rejected.
- The six configuration list endpoints accept `archived=true` for retained metadata. Responses
  include `archived_at`. Archived objects are not available in normal configuration selectors.
- `GET /api/tags/{id}/history` and `GET /api/automation/rules/{id}/executions` still expose retained
  records by original ID. Commands and Alarm event APIs keep their original attribution/references.
  There is currently no dedicated archive browser in the web UI.
- Retention continues to apply to archived Tag history according to its existing policy. Deletion
  itself never purges telemetry history. Full encrypted backups include archives; portable
  configuration exports include active configuration only.
- Partial unique indexes allow reusing a retired Tag key or a retired Device's connection/slave ID.
  The replacement receives a new internal/stable identity; old history stays with the original.
- Foreign keys remain restrictive. This is explicit transactional archival, not SQL cascade deletion.

The PostgreSQL transaction advisory lock `927013` protects the configuration lifecycle. Deletion
takes it exclusively before any configuration rows; configuration mutations, command execution,
Automation/Alarm evaluation and polling persistence take it shared. Existing per-transport locks
still serialize physical IO. Command progress notifications use their existing separate transaction
without reacquiring this gate, so a waiting deletion cannot deadlock an in-flight write/read-back.

## Edge / Cloud and upgrade order

Edge remains authoritative. Archive metadata, cancelled commands, Alarm closures, dashboard changes
and current-value invalidations synchronize through the existing durable/state lanes. Retained
history is neither discarded nor coalesced. Cloud hides retired objects from operational lists;
out-of-order updates remain protected by existing mapping sequence numbers. New Cloud accepts queued
pre-migration metadata lacking `archived_at` as an active legacy record. Unknown fields remain rejected.

Upgrade **Cloud before Edge**. Old Cloud cannot ingest the new archive field; Edge would retain such
events for retry until Cloud is upgraded. Do not clear the outbox to resolve a version mismatch.

1. Create/download encrypted full backups of both installations and retain their passphrases
   separately. Preserve deployment environment files and current release images.
2. Update Cloud using its existing deployment/updater procedure. Stop application writers for the
   migration, run `python -m alembic -c alembic.ini upgrade head` from `server` (or the existing
   migration container), then restart API/frontend and verify health and revision
   `0015_configuration_archive`. Do not touch the independent Caddy gateway.
3. On Edge, stop the **actual configured** native worker and sync services and API before migration.
   Do not guess service names or start a second worker. Pull/build the reviewed release using the
   installation's usual workflow; from `server`, run the same Alembic upgrade. Restart the existing
   API, worker, sync and frontend; retain all environment/write settings and database volumes.
4. Verify current polling, Cloud heartbeat and queue drain before using deletion. Test retirement
   with disposable simulator configuration first. No production deletion or physical write is
   part of automated verification.

Downgrade refuses if archived keys/slave IDs have been reused: restoring full unique constraints
would otherwise require deleting data. Even without collisions, a schema downgrade is not an
undo-delete action. Use the documented encrypted backup recovery/reconciliation procedure if recovery
is necessary; never delete volumes or blindly downgrade an actively syncing installation.

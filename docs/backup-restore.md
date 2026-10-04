# Backup, restore and portable configuration (Phase 12)

ADMIN: **Settings / Backup & Restore** (`/settings/backups`). Backend authorization and
existing HttpOnly session/CSRF checks protect every operation, including downloads. Other
roles cannot enumerate backups. This feature never accesses Modbus.

## Choose the right operation

| Operation | Contents | Purpose |
|---|---|---|
| Full backup | PostgreSQL database, migration/version metadata, non-secret API settings | Recover this installation, its users, telemetry, commands and retained events |
| Configuration export | Locations, Connections, Devices, Tags/history policies, Dashboards/widgets/bindings/layouts, Automation conditions/actions, Alarm rules | Transfer configuration to a new installation |

Full backups include sensitive database contents (password **hashes**, session digests,
machine credential digests, device/network information). Therefore only encrypted `.mmbak`
files can be downloaded. Supply an independent passphrase of at least 12 characters when
creating/validating a backup. It is not stored, logged, or sent to any third party. Keep it
outside the backup storage; there is no password recovery. This requirement is for backup
encryption, not the login password policy. Use HTTPS for production browser access.

Keep downloaded copies on independent, access-controlled storage. The server backup volume
alone will not survive losing the PC/disk. Backups are not uploaded to Cloud automatically.
Source code, images, virtualenvs, caches, logs and raw `.env` files are excluded.

### Where the encryption password/key lives

- The administrator chooses the passphrase in **New backup passphrase** when creating a
  backup. Validation asks for it again; offline restore prompts without echo using `getpass`.
- The application derives an AES key in process memory from that passphrase and the random
  salt using Scrypt. Neither the passphrase nor the derived key is persisted in PostgreSQL,
  backup metadata, `.env`, logs or frontend storage. The archive header contains only public
  format/salt/nonce information; it does not contain the secret key.
- Keep the passphrase in an independent password manager accessible from another device, or
  a protected offline recovery record. Record which backup UUID/file it belongs to. Do not
  keep the only copy on the Edge PC or inside the database/archive you need to recover.
- A copied `.mmbak` and its passphrase can be decrypted without the original installation,
  original PostgreSQL database or original Admin login. Loading the recovered dump still
  requires the documented compatible PostgreSQL/tools and local administrative access.
  Losing the passphrase makes the encrypted backup unusable.

### Recovery settings and secrets

`configuration/settings.json` records the API process's non-secret settings. It excludes
all `SecretStr` fields (database password, Telegram token, sync machine token) and forces
the informational write-enable value to false. It is **never applied automatically**.
Native worker settings may differ from API settings; separately keep a protected recovery
record of worker environment, USB/serial permissions and deployment overrides. Securely
save or regenerate database credentials, machine credentials and Telegram token outside
Git. A database backup cannot recover environment secrets or OS device drivers.

## Format version 1

Envelope: `MMBACKUP` + byte `0x01`, 16-byte random salt, 12-byte nonce, AES-256-GCM ciphertext,
16-byte authentication tag. The entire header is authenticated additional data. Key
derivation: Scrypt, N=32768, r=8, p=1, 32-byte key; passphrase UTF-8. Ciphertext contains gzip TAR:

```text
manifest.json
database.dump
configuration/settings.json
```

Only these three regular files are accepted. Absolute/relative traversal, links, duplicate
members, unexpected/missing files and oversized expanded content are rejected. Authentication
must succeed before parsing; manifest SHA-256/size checks verify dump and settings. Plaintext
temporary files live in a private temporary directory and are removed on completion/error.
Interrupted processes can leave temporary directories; remove abandoned `backup-*`, `validate-*`,
or `restore-*` directories only with all backup/restore processes stopped. They contain sensitive data.

Manifest: `format=modbus-monitor-backup`, `format_version=1`, UTC `created_at`,
`application_version`, `migration_revision`, `deployment_mode`, `postgres_major`, file digests.
`database.dump` is PostgreSQL custom format. `pg_export_snapshot` ties its snapshot to the
manifest's migration revision; the API holds a migration-table share lock during creation.
Polling need not stop for backup. Restore requires the same deployment mode and PostgreSQL
major, a known migration in the installed code, then upgrades to head. Newer/unknown schemas
are rejected. The Docker API image includes PostgreSQL 17 client tools; native API/restore
hosts must install compatible `pg_dump` and `pg_restore` on PATH.

## Storage and limits

| Environment | Default |
|---|---|
| `BACKUP_DIRECTORY` | `.local/backups` for native processes; `/var/lib/modbus-monitor/backups` in Compose |
| `BACKUP_RETENTION_COUNT` | 10 completed generated backups |
| `BACKUP_MAX_UPLOAD_MB` | 2048; also limits generated encrypted archives |
| `BACKUP_MAX_EXPANDED_MB` | 8192 |
| `BACKUP_TIMEOUT_SECONDS` | 1800 per PostgreSQL tool |
| `CONFIGURATION_MAX_UPLOAD_MB` | 10 |

Compose adds `backups` (local) / `cloud_backups` (production Cloud) volumes. API user owns the
private directory. UUID-only addressing ignores user filenames. OS locks protect artifacts
during creation, download, validation and restore; retention skips busy/prepared artifacts
and retries on subsequent creation. Uploaded/failed files are manually removed, not silently
discarded. UI refresh displays statuses/errors. An interrupted operation can be cancelled
only after its OS lock is released. No scheduled backups are implemented in this phase.
Ensure enough space for database dump, TAR/encrypted files **and a complete staging database**.

Native Windows API deployments must also restrict the backup directory's NTFS ACL to the
service account and administrators; POSIX mode flags alone do not enforce Windows ACLs.

## Portable JSON version 1

```json
{
  "format": "modbus-monitor-config",
  "version": 1,
  "exported_at": "2026-10-04T00:00:00Z",
  "application_version": "0.1.0",
  "data": {
    "locations": [], "connections": [], "devices": [], "tags": [],
    "dashboards": [], "widgets": [], "automation_rules": [], "alarm_rules": []
  }
}
```

Each object is `{ "id": "portable UUID", "values": { ...validated configuration fields... } }`.
Fields follow existing create schemas. Relationships such as `connection_id`, `device_id`,
`parent_id`, `tag_id`, `target_tag_id`, `dashboard_id` and widget `tag_ids` contain portable UUIDs,
**not database integer IDs**. Imports preserve those UUIDs. Exports create/reuse a local
identity registry; it is independent of Edge/Cloud sync identifiers.

Explicit allowlists exclude users/hashes, sessions, notification destinations/credentials,
current values, history, alarm events, commands/results, runtime state and sync queues/mirrors.
Names, descriptions and network/USB configuration are still private information; protect
the JSON file. Do not put passwords in configuration names/descriptions.

Flow: upload JSON -> server preview -> explicit confirmation -> apply. Preview exercises the
same schemas, relationships and database constraints in a rolled-back savepoint. Apply
revalidates under configuration locks and commits once. A failure rolls back the entire
import. Stable-ID reuse, Tag key/dashboard slug conflicts, conflicting Connection/Automation/
Alarm names, duplicate IDs and existing default-dashboard conflicts are rejected. No merge,
overwrite, external references or selective import is provided. Rename conflicting source
configuration or use a fresh installation; do not randomly rewrite UUIDs to bypass conflicts.

Imported Connections, Automation rules and Alarm rules (including Telegram notification flags)
are disabled. This intentional safety change is shown in the preview. Review serial identity,
IP/port, Tag addresses and rules before enabling. Devices/Tags/history policies and dashboard
configuration remain as exported. No control command is generated by import.

Configuration transfer is local ADMIN-only in standalone/edge. Cloud can back up/restore its
own database, but cannot import/export authoritative physical configuration.

## Full restore procedure

1. Download an independent backup of the **current** installation first. Record code revision
   and environment outside Git. Trust the backup's origin: PostgreSQL dumps can contain SQL;
   encryption authenticates a file against its passphrase, not its producer's trustworthiness.
2. Upload/select `.mmbak`, enter passphrase and click **Validate backup**. The API validates
   integrity, archive, manifest, mode, migration and fully parses `pg_restore` output without
   executing its SQL. Validation never changes the active database.
3. Type `RESTORE` and click **Prepare full restore**. This records intent only. It does not
   replace a running application's database.
4. Set `MODBUS_WRITES_ENABLED=false` in every relevant environment. Stop native workers/sync
   processes and every API or other database client. The restore command refuses a live database;
   it never terminates connections on your behalf.
5. Run the offline command below, supplying the UUID displayed by the UI. The command prompts
   for the encryption passphrase without echo. Do not put it on the command line.
6. Restore builds a **new staging database**, restores in one transaction, upgrades Alembic to
   head and checks required schema. Only after success does it block new connections briefly
   and atomically rename databases. The original remains `mm_previous_<random>` with connections
   disabled for rollback. It is not deleted. Record the printed name securely.
7. Health is checked on the restored database. Sessions are revoked; sign in using an account
   from the backup. Unfinished local/remote commands expire, and restored GOOD readings become
   STALE until fresh telemetry arrives. Physical writes remain disabled during commissioning.
8. Restart appropriate services, inspect health/current values/history, then review hardware
   and local control configuration. Manually remove the retained previous database only after
   recovery is verified and independent backups are safe.

### Local Compose (PowerShell or shell)

Stop native Windows worker/sync first if used. Keep PostgreSQL running:

```sh
docker compose --profile edge stop frontend api worker sync
docker compose run --rm --no-deps -e MODBUS_WRITES_ENABLED=false api python -m app.restore --id BACKUP_UUID --confirm RESTORE
docker compose up -d api frontend
docker compose exec api alembic current
docker compose ps
```

Use your normal documented native-worker command or `docker compose up -d worker` only after
review. Never start both workers. Resume sync only after the reconciliation section below.
Standalone needs no Cloud. Native restore from repository root:

```powershell
$env:MODBUS_WRITES_ENABLED='false'
.venv\Scripts\python.exe -m app.restore --id BACKUP_UUID --confirm RESTORE
```

Native command must see the **same backup directory** as the API; prefer the one-off API container
for Docker-created backups. `POSTGRES_HOST/PORT/DB/USER/PASSWORD` identify the target. The DB role
needs ownership and `CREATEDB` (provided by the project's PostgreSQL initialization). PostgreSQL
must not be public. Do not delete Docker volumes.

### Production Cloud

Use your actual private environment filename (example below `.env.cloud`):

```sh
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml stop frontend api
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml run --rm --no-deps -e MODBUS_WRITES_ENABLED=false api python -m app.restore --id BACKUP_UUID --confirm RESTORE
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml up -d api frontend
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml exec api alembic current
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml ps
```

Cloud runs no hardware worker. API health: `/api/health/db`; log in again to inspect the system.
If restore failed before activation, original DB is unchanged (the transient connection fence
is removed). If an OS/process failure interrupted the final switch, inspect artifact status and
`pg_database` before restarting. Do not run a second blind restore.

### Rollback

Keep services stopped. Using `psql` connected to maintenance database `postgres`, inspect exact
names first (`SELECT datname, datallowconn FROM pg_database`). The CLI prints the retained name;
substitute it and your configured database name deliberately:

```sql
BEGIN;
ALTER DATABASE your_database RENAME TO recovery_failed_review;
ALTER DATABASE mm_previous_RECORDED_SUFFIX RENAME TO your_database;
ALTER DATABASE your_database ALLOW_CONNECTIONS true;
COMMIT;
```

Never connect to a database being renamed. Do not drop `recovery_failed_review` until diagnosis.
If restore stopped before renaming but left the original fenced, `ALTER DATABASE your_database
ALLOW_CONNECTIONS true` restores access after verifying the original is still the intended DB.

## Edge/Cloud recovery and replacement Edge PC

A point-in-time restore is not an Edge/Cloud rewind protocol. The other database may have
advanced sequence numbers, deliveries or acknowledgements after the backup. Both Edge sync
and Cloud ingestion pause behind `recovery_state.sync_review_required` after full restore;
local telemetry/Automation do not depend on this fence. Existing sync payload/ordering semantics
are unchanged. The stored outbox/history is retained, not discarded.

Before releasing the fence, an administrator must reconcile counterpart checkpoints, ID
sequences and completed remote deliveries; keep old remote actions disabled/expired. This
phase does **not** automate distributed point-in-time reconciliation. For a fresh replacement
Edge, the straightforward supported workflow is **configuration import into a new database**,
new installation ID and new machine credential, then register it in Cloud. Retain the old
installation's Cloud history and encrypted backup for reference. Do not reuse the old identity
for a fresh database. Do not run old and replacement Edge workers against the same bus.

To recover the same local installation including history/users, full restore works with sync
paused. Reconfigure environment secrets, verify adapter auto-detection and read-only telemetry,
then obtain a reviewed reconciliation plan for the existing Cloud. Releasing the fence is an
explicit maintenance action, not a routine restart step:

### Manual workflow: restore -> verify -> resume sync

**Verify (operator review; no automatic reconciliation):**

1. Leave the sync service stopped and keep `MODBUS_WRITES_ENABLED=false`. Start the local API
   and, after hardware review, the appropriate local worker. A restarted sync process also
   remains blocked: it reads the persisted fence before making any Cloud request. Restarting
   the API, worker, sync process or PC does not clear this flag.
2. Confirm `/api/health/db` is healthy, sign in with a restored account, inspect retained history
   and check fresh read-only telemetry. Confirm old unfinished commands are expired. Read the
   restored database's fence using the existing local database administration connection:

   ```sql
   SELECT backup_id, restored_at, sync_review_required
   FROM recovery_state WHERE id = 1;
   ```

   Check that this is the intended backup and `sync_review_required` is **true**.
3. Compare with Cloud's state: installation identity, synchronization checkpoints/sequences
   and completed remote deliveries. Resolve advancement since the backup before resuming.
   Fresh local readings or a healthy database alone do **not** prove synchronization is safe.
   If this cannot be established, keep the fence and use the new-identity configuration-import
   recovery option above. Do not reset counters, discard history or disable ordering checks
   just to make the backlog disappear.

**Resume (explicit maintenance command after successful review):**

```sh
python -m app.restore --resume-sync --confirm RECONCILED
```

For a Docker Edge API, run the command in the same restored environment:

```sh
docker compose exec api python -m app.restore --resume-sync --confirm RECONCILED
docker compose --profile edge up -d sync
```

For native Windows sync, run the command using the native environment connected to that same
database, then start the existing native sync process. Use only one sync process. Query the
fence again (now **false**) and check Cloud freshness, history catch-up and remote request
statuses while physical writes remain disabled. The command does not enable physical writes.

Run it in the restored API environment only **after** reconciliation. It does not perform
reconciliation itself. Keep `MODBUS_WRITES_ENABLED=false` while verifying catch-up. Same guidance
applies to restoring Cloud while Edge has advanced. Never synchronize passwords or reuse a
human password as a machine credential.

## API

All routes below are ADMIN-only and under `/api/system`. Mutations require CSRF.

- `POST /backups` - JSON `{ "passphrase": "..." }`; encrypted backup, 201.
- `GET /backups` - metadata/status list (no passwords or settings content).
- `GET /backups/{uuid}/download` - encrypted file, no-store.
- `DELETE /backups/{uuid}` - remove inactive artifact, 204.
- `POST /backups/upload` - raw `application/octet-stream` body; safe server-generated UUID.
- `POST /restores/{uuid}/validate` - passphrase JSON; returns validated manifest.
- `POST /restores/{uuid}/confirm` - `{ "confirmation": "RESTORE" }`; prepare offline procedure.
- `POST /restores/{uuid}/cancel` - cancel prepared/interrupted job, never an active locked job.
- `POST /configuration/export` - versioned JSON; POST records stable IDs and audit.
- `POST /configuration/preview` - uploaded configuration JSON; counts/errors/warnings.
- `POST /configuration/import` - `{ "document": <export>, "confirmation": "IMPORT" }`.

Corrupt input/semantic conflicts report 400/422, relational conflicts or inappropriate operation
409, oversized upload 413, wrong media type 415, unavailable tooling/storage 503. No raw SQL,
subprocess stderr, passwords or filesystem paths are returned. Audit records contain action
and artifact UUID, never body/passphrase. Restore tooling reports sanitized errors.

## Validation commands

```sh
python -m pytest tests/test_backups.py -q
python -m ruff check --config server/pyproject.toml server tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
docker build -t modbus-phase12-test ./server
python tests/compose_backup_smoke.py
```

The smoke test creates a random isolated PostgreSQL container/network and tmpfs database,
checks migration up/down/drift, real encrypted pg_dump backup, validation, live-restore refusal,
staged offline restore, retained history, expired commands, revoked sessions and retained old DB.
It removes only its own disposable container/network. It never connects to production/hardware.

### Verified results (2026-10-04)

| Check | Result |
|---|---|
| `python -m pytest tests -q --tb=short`, `TEST_DATABASE_URL` = disposable PostgreSQL 17 | **570 passed**, 0 skipped, 182.67 s; includes 36 backup/security tests and existing regression suites |
| Follow-up key/recovery review: `python -m pytest tests/test_backups.py -q --tb=short` | **40 passed**, 8.11 s; four additional cases cover recovery without original files, manual resume, write-disable guard and explicit CLI confirmation |
| `npm --prefix frontend test` | **92 passed**, 14 files, 14.24 s; includes 7 Backup/Restore UI tests |
| `python -m ruff check --config server/pyproject.toml server tests` | Passed |
| Frontend `typecheck`, `lint`, `build` | Passed; build exit 0, existing main bundle size warning (>500 kB) |
| `python tests/compose_backup_smoke.py` | Passed with real PostgreSQL tools; restored API DB-health and restored Admin login also verified |
| Alembic upgrade/downgrade/head and metadata drift | Passed on PostgreSQL; no new upgrade operations detected |
| Local and production Cloud `docker compose config --quiet` | Passed using a non-secret validation placeholder for the required Cloud password |

No production migration, VPS deployment, physical Modbus write or real Telegram request was performed.

### Implementation map

- API: `server/app/api/backups.py`, registration in `main.py`, ADMIN/CSRF classification in
  `services/auth.py`.
- Storage/validation: `services/backup_archive.py`, `backup_postgres.py`, `backup_store.py`,
  `configuration_transfer.py`; schemas in `schemas/backup.py`; offline CLI `app/restore.py`.
- Database: `models/backup.py`, model registration, migration `0014_backups.py`; recovery
  fence `services/recovery.py` used by `sync/client.py` and `api/sync.py`.
- Existing validators: `services/commands.py`, `automation.py`, `dashboards.py` accept an
  explicit import-only disabled-configuration check; normal execution defaults remain strict.
- UI: `frontend/src/pages/BackupRestorePage.tsx`, `api/backups.ts`, route in `App.tsx`, link
  in `pages/SystemPage.tsx`.
- Deployment: server Dockerfile/pyproject/settings, both Compose files, `.env.example`,
  `.env.cloud.example`, `.gitignore`.
- Tests: `tests/test_backups.py`, `backup_postgres_smoke.py`, `compose_backup_smoke.py`,
  `frontend/src/test/backups.test.tsx`; migration-head expectations updated in
  `tests/test_migrations.py` and `compose_production_smoke.py`.
- Documentation: README, architecture/database docs, this guide and AGENTS rules.

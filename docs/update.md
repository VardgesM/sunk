# Manual updates (Updater v1)

## Supported deployments and safety boundary

System → Updates is ADMIN-only (including status); POST actions require the normal session,
same-origin and CSRF checks. Checks and installations are **manual**. There is no release timer,
scheduled installation, remote shell API, or updater access to Modbus.

The first deployment handler supports the dedicated **production Cloud Compose** stack:
`postgres`, `migrate`, `api`, `frontend`. The API prepares a release and encrypted backup.
A separate, opt-in **host runner** builds images, stops API/frontend, migrates and restarts them.
The API has **no Docker socket**, host credentials or permission to run deployment commands.
The runner processes only explicitly approved jobs; its polling is not scheduled updating.

Version checks also work on standalone/Edge. **In-app installation is deliberately unavailable
for native Windows worker/sync and other unmanaged topologies in v1.** There is no reliable
cross-platform supervisor in the current deployment. Never guess process names or start a
second worker. Use the manual procedure below; future handlers can implement the same
deployment interface after their lifecycle is explicitly managed.

Cloud updating cannot stop local Edge polling, Automation, alarms or local Commands.
Edge sync catches up after Cloud restarts. No setting, including `MODBUS_WRITES_ENABLED`,
is changed by the updater. Neither validation nor health checks sends control commands.

## Release format and trust

The canonical application version remains `[project].version` in `server/pyproject.toml`.
Stable versions must be `major.minor.patch` (no prerelease/build suffix in v1).
Two assets are attached to a published GitHub Release `vX.Y.Z` (or `X.Y.Z`):

- `modbus-monitor-X.Y.Z.tar.gz`: application source needed to build API/frontend images.
- `modbus-monitor-X.Y.Z.json`: detached, versioned manifest:

```json
{
  "format": "modbus-monitor-release",
  "format_version": 1,
  "version": "1.2.0",
  "minimum_version": "1.1.0",
  "created_at": "2026-10-05T00:00:00Z",
  "migration_revision": "0014_backups",
  "sha256": "<64 lowercase hex characters: SHA-256 of the complete tar.gz>",
  "size": 12345,
  "files": {
    "server/pyproject.toml": {"size": 100, "sha256": "<file SHA-256>"}
  }
}
```

This is an illustrative schema, not a deployable artifact. The manifest is **detached** to
avoid a self-referential archive checksum. Every archive member is listed with size/hash.
Allowed roots are `server/`, `frontend/`, and `deploy/cloud/Caddyfile`; local env files,
hidden directories, caches, databases, backups, keys, symlinks, hardlinks and traversal
paths are rejected. Expanded/compressed sizes and member counts are bounded. Python is
parsed as data for the migration chain, never imported during artifact validation.

The manifest version must match the packaged pyproject version and the migration head.
Existing migration files must be byte-for-byte unchanged compared with the running image,
apart from Git CRLF/LF newline conversion (Python itself normalizes those on import).
The minimum version gates required intermediate upgrades. The runner revalidates the
archive in its private directory before building; incoming Compose files are never used.

GitHub source archives are not releases. Only fixed asset names in the configured repository
are downloaded over HTTPS, with a restricted GitHub redirect allowlist. SHA-256 detects
corruption; it is **not a publisher signature**. Publishing rights on the configured repository
are a deployment trust boundary. The format version permits signed manifests later.
See the [GitHub Releases API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

## Publishing a release

1. Change only the canonical version in `server/pyproject.toml`; review migrations and update
   tests/docs. Do not change old migrations. Reinstall the editable Python package after a bump.
2. Run backend/frontend regression tests and rehearse on an isolated Cloud database.
3. Commit reviewed source. Use a clean checkout; the packager refuses dirty trees and only
   selects Git-tracked application files. Never commit a real `.env` or secret.
4. Build the assets outside the checkout (example versions below are placeholders):

```bash
python -m pip install -e './server[dev]'
python -m app.release --root . --output /tmp/modbus-release --minimum-version 1.1.0
git tag v1.2.0
git push origin v1.2.0
gh release create v1.2.0 /tmp/modbus-release/modbus-monitor-1.2.0.tar.gz /tmp/modbus-release/modbus-monitor-1.2.0.json --title '1.2.0' --notes-file release-notes.md
```

The version in the tag and asset names must be the actual pyproject version. Do not replace
assets on an already-installed release. Prefer GitHub immutable releases. Normal update
checks use public GitHub Releases (no GitHub credential storage/private-repository support).

## One-time Cloud host setup (operator action; not performed by the application)

First deploy this updater-capable version by the existing manual deployment process.
Use the existing deployment user with Docker access. Keep the current Compose project name,
database volumes, backup volume, environment and ports unchanged.

The following paths assume `/opt/modbus-monitor`. The host runner needs its own stable venv,
outside release directories, with the current server package installed. Do not auto-update
that runner venv as part of a job.

```bash
mkdir -p /opt/modbus-monitor-update/shared /opt/modbus-monitor-update/private
chmod 700 /opt/modbus-monitor-update/shared /opt/modbus-monitor-update/private
python3 -m venv /opt/modbus-monitor-update/venv
/opt/modbus-monitor-update/venv/bin/pip install /opt/modbus-monitor/server
cp deploy/update/host.example.json /opt/modbus-monitor-update/host.json
chmod 600 /opt/modbus-monitor-update/host.json
```

Provision ownership so the API's non-root runtime UID and the deployment runner user can
read/write **only the shared directory**. The standard image uses UID 1000; verify with
`docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml exec api id`.
Do not chmod/chown your whole deployment, env file, or secrets, and do not use mode 777.
If the host deployment UID differs, provision an appropriate UID/ACL for this dedicated
directory. `private/`, host config and Docker access remain inaccessible to the API container.

Add to the existing private `.env.cloud`:

```dotenv
UPDATE_SHARED_DIRECTORY=/opt/modbus-monitor-update/shared
UPDATE_REPOSITORY=VardgesM/sunk
UPDATE_DISK_RESERVE_MB=4096
```

No backup passphrase belongs in this file. `UPDATE_ENABLED` is false by default; the optional
override enables it only for API and attaches API to a dedicated private Docker bridge for
outbound GitHub HTTPS. It publishes no additional ports; PostgreSQL stays internal.
Customize host.json absolute paths/project name to match
the deployment. Do not store this file under shared storage or inside a downloaded release.

```bash
docker compose --env-file .env.cloud -f docker-compose.cloud.production.yml -f deploy/update/cloud.compose.yml up -d --no-deps api
/opt/modbus-monitor-update/venv/bin/python -m app.updater --config /opt/modbus-monitor-update/host.json
```

Keep the runner under an operator-managed terminal/service; it does not install an OS service.
`--once` processes one already-prepared job, then exits. `--status` prints the safe persistent
journal even while API/database is unavailable. Host singleton lock prevents two runners.
There is no host network listener. Do not mount the Docker socket in API to simplify setup.

## Manual workflow and states

1. Open **System → Updates → Check for updates**. Review version/date/release notes/checksum.
2. Verify host runner online and sufficient disk space in updater, Docker and backup storage.
3. Click Update. Enter an encryption passphrase (at least 12 characters), save it in an external
   password manager, and type `UPDATE`. It is held in request/task memory only, never persisted.
4. API returns 202. The page polls the persisted journal and reconnects across API restart.
5. Runner installs only after all artifact checks and the full encrypted backup complete.

States: `IDLE → CHECKING → AVAILABLE → DOWNLOADING → VALIDATING → BACKING_UP → READY →
INSTALLING → MIGRATING → RESTARTING → VERIFYING → SUCCESS`. Failures retain the failed stage;
same-schema recovery uses `ROLLING_BACK → ROLLED_BACK`. Interrupted jobs are diagnosed on
runner startup and **never replayed automatically**.
An unclaimed `READY` handoff expires after 15 minutes, so restarting a long-offline runner
cannot unexpectedly install an old request. The administrator must request installation again.

Update state is an atomic fsync-backed **filesystem journal**, like backup artifact metadata,
not a database table. It must survive a failed database migration. No schema migration is
introduced by this phase; latest revision remains `0014_backups`. Shared state is durable host
storage and contains no passphrase. Keep it across container rebuilds. A lock serializes
preparation and installation. Only one active job is accepted.

Default Compose supplies a non-root writable named `updates`/`cloud_updates` volume for
release-check state. The opt-in Cloud host bridge replaces the API's updater mount with the
dedicated shared host directory. Existing database/backup volumes are unchanged. Default
Cloud keeps its internal-only API networking; release checks need the opt-in outbound bridge
or an explicitly reviewed equivalent outbound HTTPS route.

The API reuses Phase 12 pg_dump snapshot/encryption/retention. An additional encrypted
`recovery.mmbak` is pinned in the update job directory, so deleting/retaining normal backups
cannot remove rollback material. The previous image IDs are retained with per-job image tags;
the previous checkout and all validated releases are retained. There is no automatic prune.
Keep a separate external backup copy; local disk failure can destroy both installation and backup.

## Deployment and health

The runner uses operator-owned existing Compose files/env, a fixed project name and generated
**image/build-only** overrides. It checks mode, service list, unchanged environment (including
write enable), existing volumes/mounts, revision/version and shared journal binding. It does
not deploy incoming topology, change PostgreSQL, modify env, remove containers with volumes,
or start worker/sync on Cloud. Existing images are retained before building new ones.

Only API/frontend are stopped. Migration is a bounded one-shot container; even if its Docker
CLI times out, that named migration container is stopped. No application restart is attempted
after an uncertain migration failure. On success API/frontend are started with Compose health
waiting and the runner checks HTTP health/database health, canonical version, Alembic revision,
application mode and unchanged write flag. Hardware responses are not a health requirement.
See [Compose health waiting](https://docs.docker.com/reference/cli/docker/compose/up/).

Disk checks include shared/private release storage and a configurable reserve; Docker layer
storage can be on another filesystem. Ensure Docker and backup volumes have free space too.
A build/backup failure leaves the old application running. Subprocess output is discarded
because build/config exceptions can include secrets; the UI receives fixed safe errors.

After success, `/opt/modbus-monitor-update/private/active.json` identifies the active job and
its `next.json` override (or `previous.json` after rollback). Use that override for subsequent
operator-managed restarts; plain `compose up --build` against the old checkout would revert
the images. Example (substitute the inspected UUID; do not evaluate untrusted shell text):

```bash
docker compose --project-name modbus-cloud --env-file /opt/modbus-monitor/.env.cloud \
  -f /opt/modbus-monitor/docker-compose.cloud.production.yml \
  -f /opt/modbus-monitor/deploy/update/cloud.compose.yml \
  -f /opt/modbus-monitor-update/private/JOB_UUID/next.json up -d --no-build --no-deps api frontend
```

## Rollback and controlled recovery

- Failure before stopping services: `FAILED`; existing application remains running.
- Failure after stop **without attempting a new migration**: restart retained previous images
  against the unchanged schema, verify health/version/mode/write flag, then `ROLLED_BACK`.
- If a new migration was attempted (even if Alembic still shows the old revision): stop ingress,
  `FAILED`, `recovery_required=true`. Do not assume failed DDL was entirely transactional. No
  downgrade or automatic point-in-time database restore is performed.
- Failure verifying rollback: `FAILED`, operator recovery. Never claim `ROLLED_BACK` without health.

For migration recovery, stop the runner and keep API/frontend/migration stopped. Retain the
failed DB for investigation. Recover with the prior release and **Phase 12 offline restore**
(`docs/backup-restore.md`): copy the pinned encrypted backup to a usable backup directory,
validate it using the old release, explicitly prepare `RESTORE`, stop all DB clients, restore
through staging while preserving the replaced database, verify, then reconcile before resuming
Edge/Cloud synchronization. When API cannot start, the updater's offline recovery entry point
registers the pinned copy as a new upload, calls the same Phase 12 archive/dump validation,
and then the existing staging-database restore. It never requires a running API or a password
on the command line. Run it with the **retained previous image**, all clients/runner stopped:

```bash
docker compose --project-name modbus-cloud --env-file /opt/modbus-monitor/.env.cloud \
  -f /opt/modbus-monitor/docker-compose.cloud.production.yml \
  -f /opt/modbus-monitor/deploy/update/cloud.compose.yml \
  -f /opt/modbus-monitor-update/private/JOB_UUID/previous.json \
  run --rm --no-deps -e MODBUS_WRITES_ENABLED=false api \
  python -m app.update_recovery --job JOB_UUID --confirm RESTORE
```

This explicit operator command overrides writes only for the recovery process. It prompts for
the saved encryption passphrase, keeps the replaced database, expires interrupted commands
and sets the existing sync reconciliation fence. Inspect restored DB, then start previous images
with `previous.json`, `--no-deps --no-build`; use Phase 12 **verify → resume sync** separately.

The restore workflow requires physical writes disabled. **The updater does not change that
setting**: if an installation has writes enabled, the operator must first make a deliberate
safety decision and follow offline recovery prerequisites. Full DB restore loses changes since
the backup; compare retained DB/outbox/remote command state before reconciliation.
After verified recovery, archive the failed job/journal externally and remove only `status.json`
from the shared updater directory while runner/API are stopped, allowing a fresh manual check.
Do not erase retained images, encrypted recovery files or private deployment records beforehand.

## Edge/native manual procedure

Check release availability from System, but do not enable the Cloud runner on Edge.
Take/download a Phase 12 encrypted backup and retain passphrase externally. Stop the existing
native worker and sync using their actual operator-managed launch method; verify no second
instance exists. Stop API/frontend, retain prior source/images/venv and preserve `.env`, Edge ID,
DB and backup volumes. Validate the same release/checksums, install into a new release directory,
apply `alembic upgrade head` with no runtime DB clients, and restart API/frontend plus **exactly
one** worker and sync using the existing topology. Verify application/DB health and diagnostics;
do not issue test physical commands. Retain the old version and follow the same migration-aware
rollback rules. An Edge downtime window is required; only Cloud outages preserve running Edge.

## Rehearsal before production

Unit tests mock GitHub/deployment operations and use temporary storage; no physical hardware or
real release installation is involved. For a deployment rehearsal use an isolated Cloud Compose
project/database/volumes and a separate runner directory with simulation-only Edge fixtures.
Keep `MODBUS_WRITES_ENABLED=false`. Publish reviewed test versions in an explicitly selected
test repository, then exercise success, failed build, same-schema health rollback, migration
failure, runner interruption and UI reconnect. Check retained images, env hash and volumes.
Never run a release rehearsal against a real VPS or production Edge database.

The repository includes an opt-in disposable Docker rehearsal:

```bash
python tests/compose_update_smoke.py
```

It builds uniquely tagged API/frontend images and local release fixtures, creates a separate
Cloud Compose project/database, takes a real encrypted PostgreSQL backup, deliberately fails
health verification to check binary rollback, then completes a successful redeploy. It checks
version/revision, frontend, authenticated session, unchanged env and recovery backup. GitHub is
not contacted and no release is published. Only that generated test project's labelled volumes
and image tags are cleaned up. Normal unit tests use mocks for GitHub and deployment actions.

## API and configuration

- `GET /api/system/updates/status`: installed/latest version, runner readiness, last stage/error.
- `POST /api/system/updates/check`: manually refresh the stable release, no installation.
- `POST /api/system/updates/install`: `{version, confirmation: "UPDATE", passphrase}`; async 202.

`UPDATE_ENABLED=false`, `UPDATE_DIRECTORY=.local/updates`, `UPDATE_REPOSITORY=VardgesM/sunk`,
`UPDATE_DISK_RESERVE_MB=4096`. On production the opt-in override supplies the shared directory.
Host configuration contains deployment paths, project name and bounded command/health timeouts;
it is operator configuration, never accepted from release metadata or HTTP input.

## Implementation and verification (2026-10-06)

Implemented files:

- `server/app/updates/{schema,store,github,artifact,prepare,engine,compose}.py` and package marker:
  validated release protocol, atomic journal, preparation, deployment boundary and Cloud handler.
- `server/app/api/updates.py`, `server/app/updater.py`, `server/app/update_health.py`,
  `server/app/update_recovery.py`, `server/app/release.py`: ADMIN routes and explicit host/developer CLIs.
- `server/app/{main.py,core/config.py,services/auth.py}`: router, settings and authorization integration.
- `frontend/src/api/updates.ts`, `frontend/src/pages/UpdatesPage.tsx`, `frontend/src/App.tsx`,
  `frontend/src/pages/SystemPage.tsx`: System navigation, release information, confirmation and progress.
- `deploy/update/{cloud.compose.yml,host.example.json}`, `server/Dockerfile`, both existing Compose
  files and example environments: opt-in host bridge and persistent non-root writable journals.
- `tests/test_updates.py`, `tests/compose_update_smoke.py`, `frontend/src/test/updates.test.tsx`:
  safety, UI and isolated deployment verification.
- `README.md`, `docs/architecture.md`, `AGENTS.md`, and this document: operational/safety rules.

Validation performed locally; no VPS deployment, physical control, release publication or Git commit:

| Command/check | Result |
| --- | --- |
| `python -m pytest tests -q` | **654 passed, 21 skipped**, 112.82 s. The skipped PostgreSQL/sync tests require a separately supplied `TEST_DATABASE_URL`. |
| `python -m pytest tests/test_updates.py tests/test_backups.py tests/test_auth.py tests/test_system_info.py tests/test_diagnostics.py tests/test_migrations.py -q` | **184 passed**, 33.78 s. |
| `python -m pytest tests/test_updates.py -q` | **60 passed**, 3.35 s. |
| `npm --prefix frontend run test -- --maxWorkers=2` | **119 passed**, 17 files, 39.46 s. An earlier unlimited-parallel run timed out in an existing sync UI test; the bounded final run passed. |
| `npm --prefix frontend run typecheck` / `run lint` / `run build` | **Passed**. Vite retains the existing main-chunk size warning (about 567 kB); build succeeds. |
| Ruff against changed Python modules/tests, with `--config server/pyproject.toml` | **Passed**. |
| Alembic chain and offline upgrade/downgrade validation | **Passed** in the backend suite; head remains `0014_backups`. |
| Standalone and production Cloud + updater Compose config | **Passed**; no API/PostgreSQL public ports or Cloud worker/sync service introduced. |
| `python -X utf8 tests/compose_update_smoke.py` | **Passed**, exit 0: real image builds, PostgreSQL migrations/backup, injected health failure → verified `ROLLED_BACK`, subsequent redeploy → verified `SUCCESS`. Environment, encrypted recovery copy, session, API/frontend and Cloud mode verified; isolated resources cleaned up. |
| `git diff --check` | **Passed**. |

Remaining v1 limits: only production Cloud Compose has an installation handler; native Edge
installation stays manual. Database restore after any attempted new migration is explicitly
operator-controlled. Public GitHub Releases only; SHA-256 integrity is implemented, publisher
signing is not. Real production installation and a real published release have not been exercised.

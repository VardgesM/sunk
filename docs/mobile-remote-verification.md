# Local verification — 2026-11-15

No production VPS/Edge changes, physical writes or real Telegram requests were
performed. Tests used disposable PostgreSQL 17 on loopback port 55439, independent
Edge/Cloud schemas and an Android Pixel 7 API 36 emulator with MockWebServer.

Backend checks (Python/pytest):

- `tests/test_auth.py tests/test_configuration.py`: 106 passed initially.
- Main related regression run: 298 tests; 296 passed and two archival downgrade
  assertions still expected migration 0015. Updated only those expected head
  assertions for 0016; no applied migration was rewritten.
- `tests/test_mobile_configuration.py tests/test_remote_configuration_sync.py
  tests/test_archive_postgres.py tests/test_migrations.py tests/test_updates.py`:
  **79 passed**, including the two corrected assertions and the newly added
  concurrent enqueue/delivery case.
- After expanding widget/layout coverage and refining post-delivery permission
  revocation handling, `tests/test_remote_configuration_sync.py`: **5 passed**.
- Across these runs, **359 distinct backend tests passed** (299 related regression
  cases plus 60 updater cases; repeated runs are not counted twice).
- Ruff across every changed/new Python file: **all checks passed**.
- Real PostgreSQL `alembic upgrade head`, `downgrade 0015_configuration_archive`,
  `upgrade head`, `check`: all succeeded; no pending model/schema operations.

Verified remote operations include equipment CRUD, original Tag key context,
Automation/Alarm editing, Dashboard default changes, widget CRUD/layout,
CSRF/ADMIN restrictions, outdated-version rejection, expiry, archival deletion,
duplicate concurrent enqueue and delivery, atomic mutation/receipt rollback,
metadata-before-result ordering, user revocation and unchanged command creation.
New rules in integration tests stayed disabled; no Modbus transport was opened.

Android checks (Gradle):

- `:app:testDebugUnitTest`: **86 passed**.
- `:app:lintDebug`: **0 errors, 11 warnings** (existing dependency/SDK notices).
- `:app:assembleDebug`, `:app:assembleDebugAndroidTest`: succeeded.
- Emulator BoardFourTest: **5 passed**, preserving local editor behavior.
- RemoteEditingUiTest: **2 passed**, ADMIN queue save and VIEWER restrictions.
  The initial test fixture used a fixed result ID; corrected it to echo the
  submitted request UUID, matching the real backend.
- SessionRecoveryTest: **3 passed**, encrypted persistent login restoration,
  explicit logout and server-side revocation, damaged ciphertext failing closed.

APK metadata: applicationId `com.modbusmonitor.mobile`, versionName **0.1.2**,
versionCode **3**, debug signature. No production release, commit or push made.

Limits: no verification against the user's physical phone or production servers;
new APIs require Cloud and Edge upgrade in the documented order. Worker-only USB
discovery remains local. Offline logout cannot confirm remote revocation and
reports that limitation. Existing web Cloud editors remain read-only. Read-only
diagnostics, machine credentials, Modbus/write settings and the shared gateway
were not changed.

## Release preparation for backend 0.1.3

Additional checks after the canonical version bump (not a repetition of the complete suite):

- `pytest -q tests/test_updates.py tests/test_system_info.py tests/test_auth.py
  tests/test_mobile_configuration.py tests/test_remote_configuration_sync.py
  tests/test_archive_postgres.py tests/test_migrations.py`: **137 passed in 47.96 s**.
  PostgreSQL 17 ran in a separate disposable container; no skipped integration cases.
  The first attempt exposed a missing test-only `POSTGRES_PASSWORD`; the final run and
  new workflow supply it. No production credential is used.
- Ruff with `--config server/pyproject.toml` on all changed/new Python files: **passed**.
  Corrected six import-order warnings; previously applied migrations remain untouched.
- `npm ci --no-audit --no-fund` and `npm run build`: **passed** (including TypeScript).
  The existing Vite warning remains: main chunk approximately 608 kB before gzip.
  Frontend application source and lockfile are unchanged from 0.1.2.
- Pre-commit candidate archive: **286 server/frontend files**, correct canonical version
  and migration 0016, archive/per-file SHA-256 validation and unpack **passed**. Verified
  compatibility with the published **0.1.2 updater validator**, not only the new validator.
  All **15 existing migration files** match v0.1.2 (normalizing Git CRLF/LF only).
- Release workflow YAML and embedded Python validate locally. Actual GitHub Actions
  publication starts only after the maintainer pushes the reviewed matching tag.
- `git diff --check`: **passed**. Generated candidates, package metadata and logs remain in
  ignored local storage and must not be committed or used instead of the clean-tag release.

The real assets are built from a clean committed checkout by the tag workflow. No release
was published, no commit/push performed, and no VPS or physical Edge was changed here.

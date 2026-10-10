# Project rules

- No hardcoded devices, sensors, Modbus addresses, or Modbus registers.
- No hardcoded dashboards or widgets. Static navigation and empty pages are shell infrastructure only.
- All configurable runtime entities belong in PostgreSQL and must be managed through the application.
- Frontend never accesses Modbus directly.
- The Modbus worker is the only Modbus communication layer.
- API and worker share Python configuration and models, but are separate runtime processes.
- Every Modbus write operation will eventually require authorization and audit logging.
- Current values and historical values are separate concepts.
- Every tag value will eventually have a quality state: GOOD, STALE, BAD, or COMM_ERROR.
- Prefer simple solutions over unnecessary infrastructure.
- Update documentation when architectural decisions change.
- Use type hints, small modules, explicit error handling, and migrations for schema changes.
- Never commit credentials or local environment files.
- Phase 7 adds Automation through persistent, verified commands; physical writes are disabled by default.
- No schedules or arbitrary scripts. Phase 10 adds local authentication and built-in role permissions.
- All physical control actions must go through the persistent command pipeline. Only the worker command processor may execute Modbus writes.
- Verify writes by read-back. Never replay an uncertain physical write or restart-interrupted command.
- Freeze command mode and configuration versions at enqueue; reject changed targets at execution.
- Existing physical sensors must not be made writable or used for write tests.
- Select one telemetry source mode per worker; never fall back from real Modbus to simulated samples.
- Reuse one client per configured transport and serialize each RTU bus. Reject duplicate enabled serial-port aliases.
- Connection tests and serial discovery run only in the worker; API processes only exchange diagnostic state through PostgreSQL.
- A database advisory lease permits one worker per database. Stop transport work when ownership is lost.
- Decode register bytes/words before applying scale and offset once; keep decoding independent of scheduling.
- Label source provenance in current/history state. Legacy samples with unknown source must not be labeled real.
- Keep typed history separate from latest values; policy operates on decoded engineering values.
- Store value-free quality transitions; never turn a retained failed reading into a successful historical sample.
- Isolate history write failures with savepoints, bound query results, and perform retention in periodic batches.
- Tags with retained history cannot be deleted (HTTP 409); do not silently erase historical records.
- Only the worker acquires values. The API may maintain quality/staleness but never generate samples.
- Simulation is development-only and explicitly enabled through environment settings; never depend on tag names.
- Current values are a single typed row per tag. Preserve previous successful values on communication errors.
- Commit PostgreSQL NOTIFY with the row change. Notifications are transient; reconnecting clients must resnapshot.
- Merge snapshots/live events using per-tag revisions; do not regress to an older value.
- Tag deletion explicitly removes its derived current state in the same transaction; configuration FKs remain restrictive.
- Store addresses as zero-based protocol offsets. Never automatically interpret vendor 40001 notation.
- Use restrictive foreign keys. Referenced configuration deletion must return HTTP 409, never cascade.
- Validate PATCH against the complete merged record; enforce configuration invariants in schemas and database constraints.
- Location mutations must prevent cycles, including concurrent reparenting through the API.
- Use new Alembic revisions; never rewrite an already-applied migration.
- SQLite is only an isolated test harness. PostgreSQL remains the sole runtime configuration store.

- Automation may only request control actions through the existing persistent command pipeline. Automation must never perform direct Modbus writes.
- Automation requires fresh GOOD values with matching source provenance. Preserve consumed edges across restarts; restart uncompleted FOR timers.
- Keep automation configuration relational, log executions and retain linked command history. Rules with execution history cannot be deleted.

- Alarms report abnormal conditions independently from Automation; they never perform control actions.
- Secrets such as Telegram bot tokens must never be committed, logged, returned by APIs, or stored in frontend code.
- Alarm events retain history; invalid telemetry cannot clear a valid open threshold alarm.
- Telegram is explicitly opt-in; automated tests mock HTTP and must never send real notifications.

- Auto RTU identity belongs in Connection configuration; resolved COM/path belongs in worker runtime.
- USB discovery/probing is worker-only, read-only, bounded and based solely on configured readable Tags/slaves.
- Never choose an ambiguous adapter arbitrarily or probe a port reserved by another Connection.
- Share canonical physical-port locks across detection, polling, tests and command write/read-back.

- Dashboard widgets must use existing system APIs and command infrastructure. They must never directly access Modbus or duplicate Automation/Alarm logic.
- Dashboard Tag bindings remain relational and restrictive; layout is structured per breakpoint. Physical confirmation cannot be disabled by widget configuration.

- Authorization must always be enforced by the backend.
- Frontend permission checks are UX only.
- Passwords and authentication secrets must never be logged or returned by APIs.
- Automation and worker operations must not depend on interactive user sessions.

- Cloud must never communicate directly with Modbus.
- Loss of Cloud connectivity must never stop local Automation.
- Remote physical actions must use the existing persistent Command pipeline.
- PostgreSQL must never be exposed publicly for Edge/Cloud synchronization.
- Synchronization must exclude users, password hashes, sessions and notification secrets.

- Production secrets and database/certificate backups must never be committed.
- The independent shared gateway owns public 80/443 and certificates; application services publish no ports.
- PostgreSQL stays on its internal network. API/frontend join the external web network; trust proxy headers only from the gateway.
- Application deployment/update/rollback must never restart, recreate or overwrite the shared gateway or its certificate volumes.
- Production Cloud must not include a hardware/Automation worker service, even behind an optional profile.
- First production commissioning is read-only: physical writes are disabled on both Edge and Cloud.

- Current-state synchronization must not create an unbounded durable backlog.
- Historical telemetry is durable and must never be silently coalesced.
- Realtime current state must not be blocked by historical catch-up.
- Older synchronized state must never overwrite newer Tag state.

- Backup download, restore and configuration transfer are ADMIN-only with backend authorization and CSRF.
- Full database backups contain sensitive data and must be encrypted; never persist or log backup passphrases.
- Validate restores in a separate database before replacement; retain the old database and never replay unfinished commands.
- Configuration imports are transactional and must not silently overwrite existing entities or enable physical connections/rules.
- Point-in-time Edge/Cloud restores require reconciliation before synchronization resumes.

- Updates are explicitly requested by an ADMIN; deployment runs outside the API without a Docker socket in application containers.
- Preserve environment/write settings, persistent volumes, encrypted backup and previous release before deployment.
- Never auto-downgrade migrations or claim rollback success after an unverified database change. Native Edge service lifecycles must not be guessed.

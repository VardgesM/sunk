# Remembered Android login and remote configuration

Android uses `POST /api/auth/mobile/login`. Its opaque HttpOnly session has no
time-based expiry (`auth_sessions.expires_at IS NULL`). The token is still hashed
in PostgreSQL. The APK stores cookies encrypted with Android Keystore and never
stores the password. Closing the app does not log out. Logout revokes the server
session and erases the phone copy. Disabled accounts, password changes/resets,
and explicit administrative revocation still invalidate access, including WebSocket.
An offline logout erases the phone copy but cannot confirm server revocation;
the APK reports this honestly. Resetting the account password revokes all sessions.

`POST /api/auth/mobile/remember` upgrades a **still valid**, authenticated old APK
session using the existing CSRF protection. It cannot revive an expired session.
Browser `/api/auth/login` keeps its existing bounded lifetime. Browser logins do
not evict remembered mobile sessions. Older servers remain usable by the APK,
but show a notice that their old login expiry still applies.

## Remote editing, not Cloud configuration ownership

Cloud ADMIN receives the separate `remote_configure` capability. Existing Cloud
CRUD remains read-only; unchanged web clients do not accidentally mutate mirrors.
The Android editors send requests through:

1. `GET /api/sync/configuration/context?path=tags/123`: original editable Edge
   fields, Cloud reference IDs, owning Edge and expected configuration timestamp.
2. `POST /api/sync/configuration/requests`: UUID `request_id`, method, allowlisted
   relative `path`, `payload`, optional `edge_id`, and `expected_updated_at` for
   existing objects. A 202 response means queued, **not saved**.
3. Edge retrieves the durable request through existing authenticated sync.
   The Edge applies the normal CRUD validation under the configuration lifecycle
   lock. Mutation, audit and idempotency receipt commit together.
4. Metadata synchronizes before the successful receipt. The APK polls
   `GET /api/sync/configuration/requests/{id}` until SUCCESS/FAILED/EXPIRED/CANCELLED;
   `SYNCING` means waiting for the mirrored record. The list endpoint returns the
   latest 50 requests, so closing the app does not lose the result.

Supported resources: Locations, Connections, Devices, Tags, Automation rules,
Alarm rules, Dashboards, widgets and layout. IDs are translated through existing
per-Edge mappings. References cannot cross installations. With several Edges,
select the destination for new root objects. Tag keys and Dashboard names/slugs/
default flags come from original metadata, not Cloud display decoration.

Only ADMIN can submit or inspect these requests. CSRF remains required. User
enabled/ADMIN state is rechecked before delivery. Changing permissions cannot
undo a request already delivered and applied; inspect its recorded result.
Edge requires matching installation identity, explicit supported capability and
unchanged target/reference versions. Stale edits are rejected rather than merged.
Expired requests are never applied. Duplicate delivery returns the same durable
receipt, never executes CRUD twice. No arbitrary URL, shell command, environment
setting, backup operation or user credential can be submitted through this API.

`REMOTE_CONFIGURATION_ENABLED=true` on Edge advertises `configuration-v1`.
Set false to reject remote configuration. Cloud's
`REMOTE_CONFIGURATION_MAX_AGE_SECONDS=300` controls delivery expiry (30–900).
After 30 seconds the APK stops waiting and directs the user to request status;
it does not replay an uncertain save. A delivered request with no result remains
DELIVERED until Edge reconnects; do not assume it failed or resend it.

Edits to enabled rules retain existing confirmation and runtime semantics. No
Modbus write is executed by the API or sync client. Manual/Automation control
still goes through the existing command processor and read-back verification.
`MODBUS_WRITES_ENABLED` is unchanged. Worker-only serial discovery/test actions
remain local; the APK can edit saved RTU configuration remotely, but cannot scan
Cloud hardware or invent a new USB identity.

## Upgrade order

These changes require backend **0.1.3** on Cloud and Edge, and Android **0.1.2 /
versionCode 3**. An APK alone cannot enable editing on an older Cloud. No production
services are automatically updated. See [release notes](releases/0.1.3.md) and the
[GitHub release publication workflow](update.md#tag-workflow-recommended).

1. Take the normal encrypted backups and preserve environment files.
2. Update **Cloud first**, apply Alembic `upgrade head` through new revision
   `0016_mobile_remote_configuration`, restart API using the existing deployment
   procedure. Do not touch the independent gateway or volumes.
3. Update Edge, stop its API/worker/sync according to the installation's documented
   lifecycle, apply the same migration, restart exactly one worker and sync client.
   Keep physical write configuration unchanged. Wait for capability heartbeat and
   configuration metadata to synchronize.
4. Install the new APK. A valid old session is upgraded; an already expired session
   needs one login. ADMIN editors now show Cloud → Edge and request results.
5. Verify with a disabled rule or harmless Dashboard text/layout change before
   editing operational configuration. Never test writes against physical sensors.

Migration adds only nullable mobile expiry, Edge capabilities and configuration
request/result fields to the existing remote queue. Existing command/acknowledgement
records and older Edge result payloads remain readable. Downgrade refuses to erase
retained configuration request history; use controlled backup recovery if needed.
Never delete database volumes to upgrade.

# Dynamic dashboards (Phase 9)

Dashboard definitions are PostgreSQL configuration, never source-code sensor examples. A fresh installation has no dashboards. Create one on **Dashboard**, choose its name/unique lowercase slug, and optionally mark it default. The selector opens the default (or first existing dashboard). Rename/settings also changes the default. Dashboard deletion explicitly deletes its widgets, bindings and layouts in one transaction; it does not delete Tags, samples, alarms or commands.

## Model and API

- `dashboards`: name, slug (unique), description, is_default, revision and UTC timestamps. A partial unique index permits at most one default; PostgreSQL transaction advisory locking serializes default and layout mutations.
- `dashboard_widgets`: dashboard FK, type, title, validated widget-specific JSON configuration, UTC timestamps.
- `dashboard_widget_tags`: restrictive widget/Tag FKs, composite primary key, ordered bindings. Tag references are relational, never hidden inside JSON. A referenced Tag cannot be deleted (409); remove/change the binding first.
- `dashboard_widget_layouts`: widget FK + breakpoint composite key; integer x/y/w/h with database bounds constraints. Layout is not an opaque JSON document.

Routes: GET/POST `/api/dashboards`; GET/PATCH/DELETE `/api/dashboards/{id}`; POST `/api/dashboards/{id}/widgets`; PATCH/DELETE `/api/dashboard-widgets/{id}`. Dashboard GET includes widgets, bindings and all layouts. PATCH validates the complete merged record. JSON settings reject unknown fields, nonfinite values and invalid ranges. Limits: 100 widgets/dashboard, 8 Tags/chart; list APIs paginate (maximum 500/page).

PATCH `/api/dashboards/{id}/layout` accepts `{revision, layouts: [{widget_id, breakpoint, x, y, w, h}, ...]}`. It atomically saves exactly one layout per widget/breakpoint; foreign widget IDs, duplicates, missing items and invalid bounds are rejected. A stale revision returns 409; reload before retrying. Settings replace a widget's configuration object, rather than recursively merging individual settings.

## Editing and layout

**Edit dashboard layout** enables add, edit, remove, drag and resize. Drag by the title bar and resize at the lower-right corner. Save/discard layout before editing widget settings. **Save layout** sends one batch, not requests per mouse movement. Widget settings/addition/removal are saved immediately. Controls cannot execute while editing. Finish editing locks the layout.

React Grid Layout 2 provides responsive drag/resize. Container widths >=1000px use `lg` (12 columns), >=600px `md` (6), smaller `sm` (1). Each has a separately persisted layout. Phone widgets always span one column; tall content scrolls inside the card. Widget settings also expose numeric layout fields for keyboard editing. Normal-mode widgets do not move. Unsaved layout changes are local; save before switching/reloading/leaving the page.

## Widget types

- **Value**: one Tag, decimals, unit/quality/update display options. Bad quality always remains visible, even when quality display was disabled. The displayed retained value is explicitly labeled last known.
- **Gauge**: one numeric Tag, min/max, decimals, optional display-unit label, optional upper warning/critical thresholds. A horizontal gauge clamps its indicator to the configured range; the exact value stays visible. Threshold labels are visual only, create no alarms and perform no conversion. Invalid quality disables the gauge indication.
- **Line Chart**: 1-8 numeric Tags with identical units. Default range in hours, legend and optional refresh (0=manual; otherwise >=30s). Viewer ranges include 1/6/24 hours, 7 days, the configured default and custom local start/end. Queries use UTC and the existing bounded/downsampled history API (1000 points/Tag). ECharts lines preserve invalid-quality/bucket gaps; timestamps display locally. History fetching is independent from WebSocket samples.
- **Boolean Status**: one boolean Tag with editable ON/OFF labels and explicit quality.
- **Switch / Control**: enabled writable boolean coil Tag.
- **Numeric Setpoint**: enabled writable numeric holding-register Tag.
- **Alarm List**: selected severities, active-only option, maximum rows; existing Alarm REST APIs plus existing WebSocket invalidations. Acknowledge uses the existing lifecycle; no second alarm engine.
- **Text / Label**: plain text only, safely escaped by React. No HTML or executable scripts.

## Live data and control safety

One existing shared LiveStore/WebSocket connection serves the page and all widgets, using snapshot/revision merging and reconnect resnapshot. Tag metadata is loaded once per dashboard load/reload, current values use the shared snapshot, and widgets subscribe by Tag ID. Charts query their own history ranges. Widget rendering failures are isolated. Missing/incompatible Tags show configuration errors instead of breaking the page.

Dashboard control reuses ManualControl and the Phase 6 command APIs unchanged: request -> persisted command -> worker -> write -> read-back -> actual value/command event. It never optimistically changes actual state. Physical confirmation is always mandatory, regardless of widget settings. The configurable confirmation flag additionally covers simulator commands. Disabled physical writes/offline worker disable control; server and worker still revalidate safety, enabled configuration, value limits and frozen configuration versions. Future authorization belongs in these same APIs. Dashboards contain no Modbus, automation evaluation or alarm evaluation logic.

## Verification

`tests/test_dashboards.py` covers API, defaults, bindings, compatibility, layout persistence/conflicts and restrictive deletion. Frontend tests cover builder forms, layout saving, live values, gauge/status, charts and alarms. `python tests/compose_dashboards_smoke.py` runs a disposable simulator-only PostgreSQL/API/worker/frontend project with Telegram and physical writes disabled, checks real WebSocket/current/history/command/alarm flow, browser mobile/desktop layout, and restart persistence; it removes its project/volume and fixtures afterwards.

See [Phase 9 verification results](verification-phase9.md) for exact commands and integration coverage.

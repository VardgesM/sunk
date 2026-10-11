# Responsive data views

Tags, Devices, Connections, Locations and Commands share a presentation layer.
Existing APIs, query parameters, live stores, permissions and action handlers
remain responsible for data and business behavior.

- `ResponsiveDataView` renders a table at MUI `md` (900 px) and above, and a
  semantic list of cards below it. Only one presentation mounts at a time;
  changing layouts does not create duplicate runtime fetchers or live stores.
- `MobileDataCard` gives each item a full, wrapping heading, primary value/status,
  context and actions. `DetailFields` uses description lists; `DataDetails` adds
  keyboard/touch-accessible disclosure for technical information.
- `RowActions` uses a labelled MUI menu with 44 px targets and destructive-action
  text styling. It delegates to existing handlers. Delete confirmation and
  dependency errors stay in `ManagementPage`; command cancellation is unchanged.
- `FilterPanel` shows the existing controls on desktop and lets mobile users
  expand them. Applied filters and Reset remain visible even when collapsed.
  Tags retain Apply semantics; Commands retain immediate filtering.
- `StatusBadge` keeps original status text and adds consistent visual cues.
  Tags continue using `LiveValue` and the shared WebSocket store. No new socket,
  endpoint, background job or dependency is introduced.

Desktop tables preserve all previous columns. Their scroll region is keyboard
focusable; wide desktop tables may still scroll inside the page. On mobile,
long names, keys and errors wrap instead of widening the document.

## Verification

Run `npm run test`, `npm run typecheck`, `npm run lint` and `npm run build`.
`dataViews.test.tsx` covers card/table breakpoints, permissions, menus, filters,
existing actions, quality/live updates and empty/error states. Existing suites
continue testing configuration forms and command controls.

Browser review should use isolated mocked HTTP/WebSocket fixtures at 360x800,
390x844, 768x1024, 1024x768 and 1440x900. Include long unbroken names, errors,
zero/false values, open details, filters and action menus. Verify no document
overflow, reachable actions and preserved desktop fields. Never connect this
review to physical equipment or issue real commands.

Feature editors, dashboard widgets, Automation, Alarms, history charts and System
content are outside this data-view phase; their layouts need separate review.

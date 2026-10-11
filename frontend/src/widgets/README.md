# Widgets

Dashboard widget instances, settings, Tag bindings and breakpoint layouts come from the existing Dashboard API. No sensor-specific content is seeded in the frontend.

## Responsive viewing and editing

- The builder retains its container-width breakpoints: `lg >= 1000`, `md >= 600`, `sm < 600`, with 12/6/1 grid columns. These measure available Dashboard width, not the screen or sidebar.
- Normal phone viewing uses single-column cards with content-driven heights. Alarm lists come first; other widgets follow saved phone `y`, then `x`, then widget ID. This derived order never calls the layout API.
- Tablet/desktop viewing and all edit modes use the existing saved grid. Opening a dashboard or resizing the window does not save configuration. Only explicit Save layout writes positions; widget settings/add/remove retain their existing immediate-save behavior.
- Very short saved desktop widgets can still scroll internally. Resize them in the builder when more space is needed. Phone viewing fits content without internal card scrolling.
- Editing exposes touch-sized settings/removal actions and disables equipment controls. Existing role permissions and physical-write confirmations remain authoritative through the existing control component/API.

## Operational information

- A compact summary reuses the Alarm indicator and shared live connection state. The indicator counts all active alarms, while each Alarm List retains its configured severity filters and row limit.
- Edge/Cloud mode reads the existing System sync status every five seconds (one in-flight request at a time). It shows connection state and offline Edge names, without UUIDs, queues or diagnostics. Standalone makes no sync-status request. This describes connectivity, not sensor health.
- Value, Gauge and Boolean widgets share textual quality badges. Invalid quality always shows a retained-value warning, including when Show quality is unchecked. A failed gauge does not display a fake zero reading. Last-update timestamps use browser-local time.
- Alarm lists show open alarms before cleared ones and CRITICAL before WARNING/INFO within each group. Ordering is presentation only; acknowledgement still uses the existing API and permissions.
- Charts retain the existing historical REST queries, time ranges, refresh policy and quality gaps. Their 300px plotting area resizes to its card; labels, scrollable legend and contained tooltip adapt to narrow widths. Full names remain available in the widget editor and chart tooltip. Historical data is never generated from live values.
- All current-value subscriptions use the shared live store. No widget creates its own WebSocket or metadata request. Control widgets retain their existing runtime/command queries.

## Verification

`src/test/dashboards.test.tsx` covers saved-layout compatibility, view-only mobile ordering, explicit layout saving, quality, missing Tags, roles, control confirmation, chart data and connectivity. Run `npm run test`, `npm run typecheck`, `npm run lint`, and `npm run build`. Responsive review should include 360×800, 390×844, 768×1024, 1024×768 and 1440×900 with long names and invalid telemetry.

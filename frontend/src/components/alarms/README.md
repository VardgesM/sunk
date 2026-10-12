# Alarm event presentation

- `AlarmEventList` separates open events from cleared history. The existing Active/History tabs, server filters and 100-event pagination remain unchanged. Open events on the loaded page are ordered by unacknowledged state, severity, then activation time; this is not a global sort across pages.
- Cards use one column below the shared `md` data-view breakpoint and two columns above it. Severity and lifecycle state always have text labels. Full names and clear reasons wrap; secondary information is available in Details.
- Values are **values at activation**, not current telemetry. The event API does not provide live readings or Device names. No additional per-card requests are made.
- Search is client-side and limited to the loaded page. Severity, lifecycle state and Tag filters still use the existing API parameters. Reset also returns to the first page.
- Acknowledge retains the existing permission gate and API call. Cloud displays the existing queued-for-Edge message; cards never optimistically change event state. Focus moves to the results heading because filtering may remove the acknowledged card.
- The page continues using `useAlarmRefresh` and the shared live store, including its reconnect refresh and polling fallback. Cards do not subscribe separately.
- Rule editing and Telegram delivery behavior are unchanged.

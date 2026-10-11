# Application shell

`App.tsx` keeps the existing routes and permission guards. `AppShell` owns the
sticky header, responsive drawer and shared page container. `AppNavigation`
renders the grouped destinations from `navigation.ts`; `tokens.ts` contains
shared shell sizes. Feature pages keep their own content and permissions.

- MUI `lg` (1200 px) and above: persistent 264 px sidebar.
- Below `lg`, including 1024 px: temporary drawer with a backdrop, focus trap,
  Escape/close button and automatic dismissal on navigation or breakpoint change.
- Page padding: 16 px on phones, 24 px from `sm`, 32 px from `lg`; content is
  capped at 1600 px. The sticky header occupies normal flow, so wrapped titles
  do not cover page content. Wide tables retain their own scroll containers.
- Active links use `aria-current`, bold text and a leading border. Tag detail
  routes keep Tags selected. System subpages select their exact destination.
- Account information, password change and logout are available from one menu.
  On phones its trigger is a labelled 44 px icon button; the menu shows the full
  username and role. Navigation controls also have at least 44 px touch targets.
- A keyboard skip link and route-change focus target lead to the main content.
  Dismissing a mobile drawer restores focus to the menu button.
- Users, Audit, Backup & Restore and Updates use their existing permission
  keys. Frontend visibility never replaces backend authorization.
- History stays in Tag details; dashboard editing stays in Dashboard. No new
  routes, API calls, stores or WebSocket connections are introduced by the shell.
- Existing alarm summary and API status appear in the navigation footer;
  source/simulation warnings remain above page content. Diagnostics stay in System.

## Verification

```sh
npm run test -- --maxWorkers=1 --testTimeout=20000
npm run typecheck
npm run lint
npm run build
```

The navigation tests isolate lazy feature pages; the existing page suites verify
their workflows. For visual review use actual pages with mocked HTTP/WebSocket
data at 360x800, 390x844, 768x1024, 1024x768 and 1440x900. Check long usernames,
nested routes, roles, drawer scrolling/closing, focus, header overlap and document
width. Do not connect this review to physical equipment or issue real commands.

UI Phase 2 adds shared responsive data views for Tags, Devices, Connections,
Locations and Commands (see `../components/data/README.md`). These pages switch
to cards below MUI `md`; the navigation drawer independently uses `lg`.
Forms, charts, dashboard widgets and other pages may need further mobile work.
The Automation status row only gains wrapping, so long status labels cannot
expand the entire document on phones.

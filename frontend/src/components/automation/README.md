# Automation presentation

This folder formats existing Automation API data. It does not evaluate rules, acquire telemetry, enqueue commands or change API contracts.

- `RuleCard` shows configured conditions and actions in the API's order. Numeric strings are never converted to JS numbers; boolean values display as ON/OFF. Names and units come from the existing shared Tag metadata request; unavailable metadata falls back to Tag IDs.
- ALL/ANY have plain-language explanations. The original mode, priority, duration, cooldown, hysteresis and runtime timestamps remain in Details. Original status/result values are always visible next to explanations.
- `condition_state` is an aggregate reported by the worker, including hysteresis. The API supplies neither its evaluation timestamp nor individual condition truth. It can remain unchanged during ERROR/DISABLED, so those states do not display it as a valid condition result. No browser-side condition evaluation or live freshness claim is made. Missing runtime is "Not reported", not invented IDLE.
- IDLE is a normal waiting state. ACTIVE alone does not prove successful control: the existing separate execution result is displayed. If the backend provides an error, its full text can be expanded; no specific IDLE/error cause is guessed.
- The existing three-second list refresh, single Tag metadata load, CRUD requests, enable PATCH and execution endpoint remain. Filters search only the loaded rules (the existing API client limit is 500); they do not add server queries.
- Cards use one column below MUI `md` (900px), two above it. Editor/history dialogs become fullscreen below `sm` (600px). Draft condition/action deletion requires confirmation; actual rule deletion retains its confirmation and server restrictions. Saving preserves field types, order and seconds-to-milliseconds conversion.
- Execution cards retain original snapshots, timestamps, results and links to command history. Current Tag names/units label historical snapshots; historical names/units are not included in that endpoint. History loading failures are distinct from an empty history.
- Configuration controls still require `configure`. VIEWER/OPERATOR retain read-only rule/history access. The backend remains the authorization authority.

Tests: `npm run test -- src/test/automation.test.tsx`, `npm run typecheck`, `npm run lint`, `npm run build`. Browser review uses mocked API responses at 360×800, 390×844, 768×1024, 1024×768 and 1440×900; no real rules or equipment are changed.

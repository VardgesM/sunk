# Automation / Conditions (Phase 7)

The worker evaluates configured rules and requests commands. It never imports PyModbus or calls
transport methods. `enqueue_command` is shared with the manual API; the existing command processor
performs all writes, read-back verification, current/history persistence and WebSocket publication.
Automation has no scripts, expressions or schedules. Alarms/notifications are separate subsystems.
Phase 10 requires ADMIN for rule changes; worker execution does not depend on interactive sessions.

## Configuration

Rules have a name, description, enabled flag (default false), integer priority, ALL/ANY mode,
optional FOR duration and cooldown in milliseconds. Each condition references a Tag, typed numeric
or boolean comparison value, operator, numeric hysteresis and sort order. Conditions use >, >=, <,
<=, == or !=; boolean Tags support only ==/!=. SET_TAG_VALUE actions reference writable coils or
holding-register Tags and typed requested values. There must be at least one condition and action;
a rule cannot target the same Tag twice. The editor obtains all Tag options from the API.

The API validates the complete merged PATCH, including references, type compatibility, writable
register type, representability and configured min/max. Disabling a rule remains possible if a target
was subsequently disabled or made non-writable. Execution revalidates all targets and configuration
versions. Rule edits/disable invalidate queued automation commands, which fail without writing.
Rules with retained executions cannot be deleted (409); disable them instead. Referenced Tags also
cannot be deleted. Configuration remains normalized in PostgreSQL; JSON is limited to runtime
comparison latches and diagnostic execution snapshots.

## Quality and source

All referenced inputs must be effectively enabled, have a typed value, quality GOOD, and a source
timestamp no older than `poll_interval_ms * STALE_MULTIPLIER`. This freshness check does not rely
on the API stale task being available. Simulator workers accept simulator samples; Modbus workers
accept real Modbus samples. Unknown or mismatched provenance is unusable.

Conservatively, an invalid input makes the entire rule unknown, even in ANY mode. BAD, COMM_ERROR,
STALE, DISABLED, missing or stale-but-GOOD inputs reset an incomplete FOR timer and show ERROR.
They do not re-arm an already consumed true edge. For valid inputs ALL requires every condition;
ANY requires at least one. Recovery does not replay a consumed edge. Stateful actions may instead
request a new corrective command after the conditions qualify again and a fresh usable output
reading proves a mismatch (see desired-state reconciliation below).

## Edge, duration and hysteresis

A new enabled rule may trigger from its first valid true observation. Continuously true state triggers
once. A valid false aggregate re-arms the rule. Stateful output reconciliation is separate from this
edge trigger; it does not periodically replay the action. A true state must persist for FOR milliseconds before
a command is requested. With no duration it is eligible on the first observation. Input updates are
sampled by the engine (about 250 ms); transitions occurring entirely between observations cannot be
observed. Choose polling intervals appropriate to the process.

Numeric >/>= conditions latch when their comparison becomes true. With hysteresis H > 0 they remain
true until value <= threshold - H. Numeric </<= conditions remain true until value >= threshold + H.
H=0 uses the original comparison exactly. Equality/inequality and booleans do not accept hysteresis.
Example: >30 with H=2 sets true above 30 and re-arms at 28 or lower. Latches apply independently to
each condition, including during FOR, and the rule aggregates the latched states with ALL/ANY.
Hysteresis never automatically creates an opposite action: use a separate explicit reset rule.

Consumed edges, latches, cooldown and results are persisted. On worker restart, incomplete FOR timers
restart from the first fresh observation, since continuity during downtime is unproven. An already
triggered true edge is not replayed; a successful unchanged rule can reconcile a fresh output mismatch
after a new FOR observation period. After editing or enabling an existing rule, it must observe a
valid false state before becoming eligible; this avoids executing an edited configuration immediately.

## Cooldown, conflicts and failures

Cooldown starts when **all** linked commands succeed, from the last command completion timestamp.
A false/true edge during cooldown may execute when both FOR and cooldown have elapsed. Remaining true
never triggers periodically. While an earlier execution is pending, no further execution of that rule
is created. Failed/skipped executions consume the edge: correct the cause and observe false/true to
retry. No autonomous retry of failed physical actions is added; normal command retry rules apply.

Rules evaluate in descending priority, then ascending rule ID. A qualified active higher-priority
rule reserves its complete target batch even when already matched, cooling down, waiting for a
command, or unable to read an output. A lower rule overlapping a reserved target is blocked as a
whole and does not reserve its other targets. Competitors are evaluated together even when only a
lower rule's input changed. This extends the existing deterministic reservation to desired-state
maintenance; otherwise two continuously true conflicting rules could toggle an output indefinitely.
Any pending command (manual or automation, same or different value) blocks the entire action batch.
A lower rule's initial blocked edge is still SKIPPED and consumed as before. A previously successful
lower rule can resume reconciliation after the higher rule ceases to qualify. This is not a safety
interlock or global arbitration of manual commands.
Command creation and execution links are atomic per rule. Physical execution of multiple actions
cannot be atomic: successful actions are not undone when another action fails. The execution log
reports SUCCESS, PARTIAL_FAILURE or FAILED after commands complete, or SKIPPED for a conflict.
It records trigger time, comparison snapshot, errors and command IDs; detailed I/O stays in commands.

## Desired-state reconciliation

`SET_TAG_VALUE` is the only supported action kind, and represents an idempotent maintained value.
There are no pulse/toggle/one-shot actions and no safe way to infer side-effect register semantics
from a vendor address. Do not configure such registers as maintained SET_TAG_VALUE outputs; they
require an explicit separate action type before they can be supported.

While the condition remains qualified, a successful, unchanged rule compares **actual current Tag
values**, not the last sent command, with its desired values. Both initial activation and correction
require every target to be enabled and readable with GOOD quality, matching source (simulator or its
configured Modbus protocol), a correctly typed value and an age between zero and
`poll_interval_ms * STALE_MULTIPLIER`. Samples must postdate target/device/connection configuration;
after worker recovery they must also be read after that recovery. Correction requires a sample newer
than the prior successful execution completion. Retained values under COMM_ERROR, BAD, STALE,
DISABLED, unknown source, missing values and future timestamps cannot authorize writes.

Example: ON/GOOD -> COMM_ERROR -> OFF/GOOD. Nothing is written during COMM_ERROR. Once a fresh
OFF reading arrives, eligible automation enqueues a **new** ON command through `enqueue_command`.
The existing processor performs the write and read-back. When the output is ON, there are no further
commands or repeated success log entries. Numeric comparisons reuse command verification tolerance,
including type/scale/offset; float rounding must not cause repeated setpoint writes.

Only mismatched targets receive commands. All targets must be usable and the whole batch must be
free of pending/in-flight commands. Already-matched initial activation records a SUCCESS execution
with no commands and an `already_desired` snapshot reason. Corrections record the normal execution
and command links, with actual/desired/revision and `reconciliation` in the snapshot. Physical
multi-output changes remain sequential, not atomic.

FOR still applies to the input condition. Restart or invalid input resets its observation timer even
for a consumed edge; target communication loss alone does not pretend the input became false.
Cooldown remains measured from the last successful command-batch completion. A mismatch during
cooldown waits for expiry; time-based evaluation ensures it is reconsidered without needing a new
condition edge. There is no new periodic write schedule and no cooldown reset on every poll.

A FAILED/PARTIAL_FAILURE, CANCELLED/EXPIRED command, interrupted write, or SKIPPED initial execution
is **not automatically retried by reconciliation**. Its consumed edge and execution history survive
restart. Inspect the cause and use the existing valid false/true re-arm path. This bounds corrective
attempts and leaves transient retries/read-back-only retries to the existing command processor.
Editing/enabling a rule still requires a valid false/true observation: previous-version success does
not authorize changed actions. No database runtime flags should be manually reset to bypass this.

Manual control is not a new override mode: while a stateful rule remains enabled and qualified,
a fresh manually changed output can be corrected back to the rule's desired value after its command
finishes. Disable the relevant automation rules before manual maintenance. No automatic manual-hold
feature is introduced by this fix. A false condition ends ownership; the engine does not latch a
desired value through a range where no rule is currently true.

## Physical safety

`MODBUS_WRITES_ENABLED=false` blocks automation just as manual physical commands. Detection records
a FAILED execution with a clear reason and creates no physical command. The rule does not repeatedly
try while its input stays true. Rule enablement plus the worker master switch is the explicit control
configuration; it is not authentication. Simulator commands remain available through the same queue.
No example rules are installed into the real database. Do not test automation on existing sensors.

## API and UI

- GET/POST `/api/automation/rules`
- GET/PATCH/DELETE `/api/automation/rules/{id}`
- PATCH with `{ "enabled": false }` or true enables/disables a rule.
- GET `/api/automation/rules/{id}/executions?limit=50` (maximum 200)

Rule responses include nested conditions/actions and runtime state. Numeric values are decimal strings
so browsers do not lose precision; booleans stay booleans. All stored times are UTC; UI displays local
time. The Automation page refreshes rule status every three seconds and provides a responsive editor,
delete confirmation and execution history with command links. Existing command/current-value WebSocket
updates are unchanged. No new broker or realtime protocol is introduced.

The worker refreshes rule configuration using WORKER_CONFIG_REFRESH_SECONDS. Each evaluation reads
only referenced current values, tracks their revisions and skips unchanged rules unless FOR/cooldown
requires another time check. Action target revisions/freshness are also observed; changes evaluate
their owning rules and competing rules sharing outputs. Unrelated rules remain skipped. Configuration changes are version-checked again under the rule lock.

## Verification

`python -m pytest tests/test_automation.py tests/test_automation_reconciliation.py` covers validation, edge state, quality, ALL/ANY, operators,
FOR, hysteresis, cooldown, priority, multiple actions, simulator verification and restart behavior.
`python tests/compose_automation_smoke.py` creates a disposable Compose project, uses manual simulator
commands to set deterministic inputs, checks ON/OFF and multi-condition rules, history/WebSocket,
mobile browser UI and migrations, then deletes only that project's containers and volume. Physical
hardware is never targeted. Build API/worker/frontend images before running it.

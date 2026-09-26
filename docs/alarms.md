# Alarms and Telegram (Phase 8)

Alarms describe abnormal conditions for operators; Automation requests equipment control through
commands. The alarm engine never creates control commands or calls PyModbus. Existing polling,
Automation, command verification and history remain separate worker tasks.

## Conditions and lifecycle

Rules select a database Tag, typed comparison, severity (INFO/WARNING/CRITICAL), enabled state,
FOR duration, hysteresis and notification flag. Numeric operators: >, >=, <, <=, ==, !=.
Boolean operators: == and !=, with a JSON boolean comparison. Numeric values use NUMERIC/Decimal.
Rules are disabled by default; configuration refresh uses WORKER_CONFIG_REFRESH_SECONDS (2s).
The evaluator scans referenced inputs every 250ms but only evaluates rules with changed inputs,
configuration or pending FOR timers. It uses the existing worker database lease.

Only enabled Tag/Device/Connection with fresh GOOD telemetry from the selected source is usable.
Freshness is at most poll_interval_ms * STALE_MULTIPLIER; future timestamps are rejected.
BAD, STALE, COMM_ERROR, DISABLED, missing or wrong-source readings reset pending FOR timers.
They **do not clear an existing alarm**: missing evidence is not evidence of recovery.
There are no dedicated communication alarms in this phase.

NORMAL means no open event. A condition true continuously for FOR milliseconds creates ACTIVE.
A false reading before activation resets FOR, even within the future hysteresis band.
Zero/null duration activates immediately. Uncompleted timers restart after worker restart;
already ACTIVE/ACKNOWLEDGED events survive and do not generate duplicate activation notifications.

Acknowledgement changes ACTIVE -> ACKNOWLEDGED and records its UTC timestamp; it does not change
measurements or control equipment. The next valid clearing reading changes either open state to
CLEARED. Cleared/acknowledged events cannot be acknowledged again (409). A later activation is a
new event. All events retain the name, Tag name, unit, condition, severity and triggering typed value.
Acknowledgement identity is not recorded yet because authentication is not implemented.

Hysteresis applies **after activation**, for numeric inequalities only. For > or >= threshold T and
H > 0, the alarm remains open while value > T-H and clears at value <= T-H. For < or <= it stays
open while value < T+H and clears at value >= T+H. H=0 uses the exact configured operator.
Equality/inequality and boolean conditions require H=0. Example: >35 with H=2 clears at <=33.

Editing any rule (including disabling) explicitly closes its open episode with reason
`Rule configuration changed` and resets FOR; enabling/revising may create a new episode when
its condition is satisfied. No notification is sent for configuration closure or normal clearing.
Rules and Tags referenced by event history cannot be deleted (409); disable them instead.

## APIs and live events

- GET/POST /api/alarms/rules; GET/PATCH/DELETE /api/alarms/rules/{id}.
- PATCH {"enabled": false} disables a rule. PATCH validates the merged configuration.
- GET /api/alarms/events?active=true&severity=CRITICAL&tag_id=1&rule_id=2
- Additional filters: state=ACTIVE|ACKNOWLEDGED|CLEARED, from/to timezone-aware ISO dates.
- Results newest first, default limit=100, max=500, offset pagination.
- POST /api/alarms/events/{id}/acknowledge; GET /api/alarms/summary (all open/critical counts).

PostgreSQL `alarm_events_changed` NOTIFY contains only the event ID and commits atomically with the
row. The existing listener publishes `{"type":"alarm_event","data":{...EventRead}}` with id,
rule_id, tag_id, state, revision, severity, value_numeric (exact decimal string) or value_boolean,
condition and UTC lifecycle timestamps. Notifications are transient invalidations of persisted state.
The shared frontend WebSocket invalidates alarm REST snapshots (coalescing bursts); reconnect also
resnapshots. A 15s fallback refresh handles missed notifications. No second socket or transport.
The Alarms page has active/history, severity/state/Tag filters, acknowledgement and rule management.
The shell count includes ACTIVE and ACKNOWLEDGED; CRITICAL is spelled out, not only colored.

## Telegram setup

1. Create a bot with Telegram BotFather. Start it in the target chat or add it to the destination.
2. Set secrets **only in the worker environment** (native worker reads local ignored .env):

   ```dotenv
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=your-private-token
   TELEGRAM_TIMEOUT_SECONDS=5
   TELEGRAM_TIMEZONE=Asia/Yerevan
   ```

3. Restart the worker for environment changes. In Alarms -> Telegram save the numeric chat ID
   (negative IDs allowed for groups) or @channelusername. This non-secret destination is stored
   in PostgreSQL using PATCH /api/notifications/telegram/destination.
4. Click **Send test message** or POST /api/notifications/telegram/test. The API returns 202 and a
   delivery ID. This is queued, not a success claim. GET /api/notifications/telegram/deliveries
   (optionally event_id) reports PENDING/SENDING/SENT/FAILED/SKIPPED. The UI refreshes results;
   an offline worker leaves the message pending. Fix configuration then explicitly test again.
5. Enable Telegram notifications on chosen alarm rules. No production examples are auto-created.

Compose passes the token only to the worker, not API/frontend. Never commit .env, log tokens,
return them in APIs, or put them in browser code. Do not publish `docker compose config` output;
use `docker compose config --quiet` for validation. HTTP exceptions/Telegram response bodies are
not logged or returned because they can include sensitive information. Plain-text messages avoid
untrusted HTML/Markdown interpretation. HTTP redirects are refused.

The sender uses Telegram's official [sendMessage API](https://core.telegram.org/bots/api#sendmessage)
with chat_id and text (limited to 4000 characters). Activation message includes severity, rule,
Tag, trigger value, unit, threshold and readable activation time.
TELEGRAM_TIMEZONE selects an IANA display zone (default UTC). Example: `26.09.2026 19:10:52 (Asia/Yerevan)`.
Database/API timestamps remain UTC; existing queued messages retain their original formatted text. One unique outbox row per event/kind
is inserted in the activation transaction. Destination/message are frozen at enqueue.
Telegram disabled or missing configuration produces SKIPPED. Pending messages expire after five
minutes rather than delivering old alarms unexpectedly after a long outage.

The separate sender makes **one attempt**, with a configurable socket timeout (1?15s). Failures
are FAILED without retry; an ambiguous timeout may already have delivered the message. SENDING
records after restart are marked FAILED and never automatically resent. This chooses duplicate
avoidance over guaranteed delivery: Telegram offers no application idempotency key. Delivery
failures never stop telemetry, Automation or alarm evaluation. Activation is notified once;
clearing notifications are intentionally omitted (optional in this phase).

## Verification

Unit tests mock HTTP and never send real Telegram messages. `tests/compose_alarms_smoke.py` starts
a disposable simulator stack, verifies numeric/boolean episodes, FOR/hysteresis, acknowledge,
clear/reactivation, browser UI and cross-process PostgreSQL/WebSocket events; Telegram is forced
off. It removes only its own project/volume. Actual Telegram verification requires explicit
TELEGRAM_ENABLED=true plus a destination/token. No physical writes are needed to test Alarms.

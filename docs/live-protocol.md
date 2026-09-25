# Live telemetry protocol v1

`GET /api/tags/values` returns an array ordered by tag ID. Filters: `tag_id`, `device_id`, `enabled`
(effective tag/device/connection state), `quality`. Pagination: `limit` (1–500, default 100),
`after_tag_id`. `GET /api/tags/{id}/value` returns one snapshot, or 404 for an unknown tag. An existing
tag with no reading has null typed fields/quality/timestamps and revision 0.

Connect to `/api/ws/live` using ws/wss matching the page. The initial message is
`{"type":"ready","version":1,"listener_ready":true}`. Listener readiness describes the PostgreSQL
event bridge, not device/worker health; inspect each row's quality independently.

Value events have this shape (illustration only; no runtime configuration is seeded):

```json
{
  "type": "tag_value",
  "data": {
    "tag_id": 123, "key": "configured_key", "name": "Configured name",
    "device_id": 45, "data_type": "float32", "unit": null,
    "enabled": true, "effective_enabled": true,
    "value_numeric": 24.7, "value_numeric_exact": "24.7",
    "value_boolean": null, "value_text": null, "raw_value": "24.7",
    "quality": "GOOD", "error": null, "source": "simulator",
    "source_timestamp": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00", "revision": 8
  }
}
```

The `data` schema also defines REST responses. Numeric values remain numbers; `value_numeric_exact`
protects large integer/decimal display in JavaScript. `source_timestamp` is last success;
`updated_at` also advances on quality/error changes.

Other messages:

- `{"type":"tag_deleted","tag_id":123}` removes cached state.
- `{"type":"stream_status","ready":false}` reports a disconnected database listener.
- `{"type":"resync_required"}` requests a fresh REST snapshot after recovery/queue overflow.
- `{"type":"heartbeat","listener_ready":true,"timestamp":"..."}` follows 15 seconds of socket inactivity.

There are no client commands/subscription messages in v1. Multiple clients receive all tag updates;
each API process listens independently. One telemetry worker is supported. Intermediate updates may
be coalesced: this is latest-state delivery, not an event history or guaranteed sample stream.

Recovery: snapshot first, connect, then resnapshot on `ready` to close the initial gap. Repeat after
reconnect/resync. Merge live messages while loading snapshots, reject lower revisions, preserve
in-flight deletion events. The included client uses backoff (1–30 seconds), a 45-second message
watchdog, per-tag subscriptions, and full cleanup on unmount. Quality is never inferred from socket color.

| Quality | Meaning |
| --- | --- |
| GOOD | Successful typed reading. |
| STALE | Last GOOD source time is older than multiplier × this tag's poll interval; value retained. |
| BAD | Invalid configuration/decoded source result; previous value may remain. |
| COMM_ERROR | Acquisition failed; previous successful value/time retained if available. |
| DISABLED | Tag, device or connection disabled; no acquisition. |

Default stale multiplier is 3; the API checks every second. STALE never hides explicit errors/disabled
state. LISTEN/NOTIFY sends only tag IDs and has no durable backlog; PostgreSQL rows are authoritative.

`source` is an additive nullable field: simulator, modbus_rtu or modbus_tcp. It identifies the retained
sample, not the worker's current mode; failures preserve it with the prior successful value.
Unknown/legacy values remain null. `/api/system/runtime` independently reports current worker mode.

## Phase 6 command events

The same WebSocket also emits `{"type":"command_status","data":<CommandRead>}` after transactional
`commands_changed` PostgreSQL notifications. Data includes the command's positive revision. Command
clients load REST snapshots, merge higher revisions, and refetch on ready/resync after reconnect.
Intermediate statuses may coalesce; GET `/api/commands/{id}` remains authoritative. Decimal command
values are exact strings, boolean values remain booleans. See [commands](commands.md).

# Historical telemetry

`tag_current_values` remains one latest state per tag. `tag_history` is an independent append-only
sample/quality table, except periodic retention deletes. PostgreSQL is the only runtime store.
Simulation produces the same decoded engineering value used by both paths: scale/offset is applied
once before policy evaluation. Real Modbus returns the same Reading contract.

## Policies

All settings belong to Tag configuration and can be edited through the Tags form. Poll interval is
how often a source is read; history interval is how often a reading is retained. History never slows
the configured polling schedule intentionally. `history_enabled=false` prevents all new historical
writes, including quality markers, while live current values continue updating.

| Mode | GOOD sample storage |
| --- | --- |
| every_sample | Every successful sample. Interval/threshold are not required or consulted. |
| fixed_interval | First sample, then the first success at least history_interval_ms after the last stored GOOD row. Interval must be positive and >= poll_interval_ms. |
| on_change | First sample, then changes relative to the last stored row, not the previous polled sample. Numeric absolute delta must be >= threshold and > 0; booleans/text use inequality. |

Numeric on_change requires a finite non-negative threshold. For last stored 22.5 and threshold 0.2,
22.55 and 22.61 are skipped, 22.7 reaches the boundary and is stored. With threshold zero, identical
values are skipped. Boolean on_change needs no threshold. Text equality is supported by the writer's
typed representation; this phase does not introduce a text Modbus datatype.

The first success following a stored non-GOOD marker is always saved, regardless of interval or
threshold, documenting recovery. Fixed interval then starts from that recovery record. Timing uses
UTC recorded_at (storage decision time); source_timestamp separately identifies acquisition time.
Policies consult the latest indexed database row when necessary, so a worker restart needs no warmup
or inferred baseline. Every-sample success does not query previous history. One worker is supported.

## Quality and failures

- GOOD: save the typed engineering value, source timestamp and optional raw diagnostic.
- STALE, BAD, COMM_ERROR, DISABLED: save a value-free marker only when the last stored quality differs.
- Repeated failures do not accumulate repeated markers. Retained current values never become fake
  historical failure readings. The API stale sweep may append STALE; it cannot append sensor samples.
- Current upsert, history savepoint, and NOTIFY are in one short transaction. History SQL failures are
  logged and rolled back to the savepoint; current state can still commit. PostgreSQL history statements
  use a 1s statement timeout and 250ms lock timeout. Connection loss may prevent the outer commit too.
- There is no durable history retry queue. A failed history write can lose that sample/marker, and the
  next reading is evaluated against the last committed record. History is not a guaranteed audit trail.

Charts use null gaps for non-GOOD markers, never the last retained current value. They do not synthesize
missing readings or extrapolate across trailing outages. Lines between GOOD samples are visual
interpolation, especially with on_change; they are not evidence of additional measurements. Disabling
history also disables outage recording, so that interval is unobserved.

## Retention and deletion

Positive `history_retention_days` expires rows with recorded_at strictly older than now minus that
many days; NULL retains indefinitely. Retention still applies when history or the tag is disabled.
The worker runs maintenance at startup and every `HISTORY_CLEANUP_SECONDS` (default 3600).
It pages tag policies and deletes at most 5000 rows per transaction, up to 20 batches per tag per pass.
Large backlogs expire over subsequent passes. Cleanup logs nonzero counts, logs/retries failures, and
runs independently of acquisition. In-flight configuration changes take effect on the next scan.

Tags with retained history cannot be deleted (409). This protects historical data; configuration FKs
remain restrictive. No implicit purge, cascade, or archive subsystem is added.

## Query API

`GET /api/tags/{id}/history?from=2026-09-16T00:00:00Z&to=2026-09-17T00:00:00Z&max_points=1000`

- Range is **[from, to)** on recorded_at, not source_timestamp; explicit timestamps require timezone
  offsets and are normalized to UTC. Default is the 24 hours ending at `to` (or now).
- Range must be positive, at most 366 days. `limit` defaults 1000, maximum 5000.
- `order=asc` (default) or `desc`, with id as a stable raw-row timestamp tie-breaker.
- Optional `max_points` is 1–2000; effective cap is min(limit, max_points).
- Unknown tag: 404. Empty existing tag: 200 with empty points. Invalid range: 422.
- Response includes tag id/key/name/unit/data_type, normalized from_timestamp/to_timestamp,
  count (returned points), total_count (matching stored rows), downsampled, truncated, and points.
- Raw points contain recorded_at, source_timestamp, typed fields, quality, numeric exact-string
  companion, first_timestamp/last_timestamp, sample_count=1, has_invalid. Numeric JSON stays numeric.
- Without max_points, excess raw rows are omitted and truncated=true. Request a smaller range or
  max_points for a complete range summary. No full table is loaded into Python or the browser.

## Downsampling

If total_count exceeds the effective cap, SQL divides the requested range into equal-width time
buckets anchored to `from`. Empty buckets are omitted. Each occupied bucket returns numeric minimum,
maximum, average, first/last recorded timestamps and sample_count. The representative numeric value
is average at the first timestamp. This deterministic strategy keeps output bounded while retaining
extrema in the response; it is not scientific compression. SQL aggregates process matching rows in
PostgreSQL, so very large dense ranges can still cost database CPU despite bounded response size.

A bucket containing any non-GOOD row sets has_invalid and has no representative value. Its quality
is the lexically first non-GOOD quality, not a claimed severity ranking. Numeric statistics cover only
numeric samples in that bucket. Mixed-type buckets have no representative numeric value. Boolean
buckets yield a boolean only if every sample is GOOD and identical; mixed states become gaps, never
fractional booleans. Request a shorter range to see transitions. Text is not numerically aggregated.

Raw numeric values remain PostgreSQL NUMERIC. JSON carries value_numeric_exact for precision-sensitive
consumers; chart coordinates and averages displayed in JavaScript use approximate IEEE-754 numbers.

## Interface

Click a tag name to open `/tags/:id`. Metadata and current live values remain visible beside an
independent historical chart. Presets cover 1h, 6h, 24h, 7d, 30d, plus custom local start/end inputs.
Requests use UTC; labels/tooltips use browser-local time. Charts refresh on range selection or the
Refresh button, never every WebSocket event. Numeric data uses lines; boolean data uses steps.
Inside zoom/pan and a slider adjust the displayed range without refetching; choose a narrower query
range for finer bucket resolution. Text types show a clear non-chartable message.

The reusable ECharts component uses modular imports, SVG rendering, ResizeObserver and disposal on
unmount, following the [Apache ECharts container guidance](https://echarts.apache.org/handbook/en/concepts/chart-size/).
No dashboard builder or multi-tag comparison UI is introduced.

## Storage volume

One-second every_sample history creates **86,400 rows per tag per day**: 100 tags produce 8.64 million
daily rows before any extra quality markers. At a rough 150–300 bytes per row including index overhead,
that is about 13–26 MB per tag/day (1.3–2.6 GB for 100 tags/day), excluding WAL, backups, and bloat.
Actual footprint varies with raw/text length and PostgreSQL storage; measure deployed data rather
than treating this estimate as a capacity limit. Fixed_interval and on_change are recommended for
many high-frequency tags. User-selected policies are never silently changed.

## Source provenance

Points include nullable `source` (simulator, modbus_rtu, modbus_tcp). Legacy and value-free quality
rows have unknown source. SQL buckets identify a source only when every row has the same non-null
source. A successful source switch inserts a value-free BAD boundary so charts do not silently join
simulated and real measurements. The chart identifies sources present in its result.

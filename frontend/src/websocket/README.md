# WebSocket

`liveStore.ts` owns a shared, reference-counted API WebSocket connection and REST snapshots.
Per-tag subscriptions update affected cells only. Reconnects request a fresh snapshot and merge
records by revision. The browser never connects to a Modbus device or worker.

See [protocol and recovery](../../../docs/live-protocol.md).

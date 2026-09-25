import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CurrentValue } from '../types/telemetry';
import { parseLiveEvent } from '../types/telemetry';
import { LiveStore } from '../websocket/liveStore';
import { loadCurrentValues } from '../api/telemetry';

const value: CurrentValue = {
  tag_id: 1, key: 'test', name: 'Test', device_id: 1, data_type: 'float32', unit: null,
  enabled: true, effective_enabled: true, value_numeric: 1, value_numeric_exact: '1',
  value_boolean: null, value_text: null, raw_value: '1', quality: 'GOOD',
  source_timestamp: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-01T00:00:00+00:00',
  error: null, revision: 1,
};

class FakeSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn(() => this.onclose?.());
  event(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

async function flush() { for (let i = 0; i < 10; i++) await Promise.resolve(); }
afterEach(() => { vi.useRealTimers(); });

describe('live state and reconnect', () => {
  it('loads REST before connecting and shares a socket until the final release', async () => {
    const snapshot = vi.fn().mockResolvedValue([value]);
    const socket = new FakeSocket();
    const connect = vi.fn(() => socket as unknown as WebSocket);
    const store = new LiveStore(snapshot, connect);
    const release = store.retain(), releaseSecond = store.retain();
    expect(connect).not.toHaveBeenCalled();
    await flush();
    expect(store.getValue(1)?.value_numeric).toBe(1);
    expect(connect).toHaveBeenCalledTimes(1);
    socket.event({ type: 'ready', version: 1, listener_ready: true }); await flush();
    expect(snapshot).toHaveBeenCalledTimes(2);
    expect(store.getStatus().state).toBe('Live');
    release(); expect(socket.close).not.toHaveBeenCalled();
    releaseSecond(); expect(socket.close).toHaveBeenCalledTimes(1);
    expect(store.getStatus().state).toBe('Disconnected');
  });

  it('updates only subscribers for the affected tag and ignores older revisions', async () => {
    const socket = new FakeSocket();
    const store = new LiveStore(vi.fn().mockResolvedValue([value]), () => socket as unknown as WebSocket);
    const release = store.retain(); await flush();
    const affected = vi.fn(), other = vi.fn();
    store.subscribe(1, affected); store.subscribe(2, other);
    socket.event({ type: 'tag_value', data: { ...value, revision: 3, value_numeric: 4, quality: 'STALE' } });
    socket.event({ type: 'tag_value', data: { ...value, revision: 2 } });
    expect(store.getValue(1)?.value_numeric).toBe(4);
    expect(store.getValue(1)?.quality).toBe('STALE');
    expect(affected).toHaveBeenCalledTimes(1); expect(other).not.toHaveBeenCalled();
    release();
  });

  it('preserves a newer live update when a slower recovery snapshot completes', async () => {
    let finish!: (values: CurrentValue[]) => void;
    const snapshot = vi.fn().mockResolvedValueOnce([value]).mockImplementationOnce(() => new Promise<CurrentValue[]>((resolve) => { finish = resolve; }));
    const socket = new FakeSocket();
    const store = new LiveStore(snapshot, () => socket as unknown as WebSocket);
    const release = store.retain(); await flush();
    socket.event({ type: 'ready', version: 1, listener_ready: true });
    socket.event({ type: 'tag_value', data: { ...value, revision: 2, value_numeric: 5 } });
    finish([value]); await flush();
    expect(store.getValue(1)?.value_numeric).toBe(5);
    release();
  });

  it('reconnects and snapshots again, recovering deletions missed while offline', async () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const snapshot = vi.fn().mockResolvedValue([value]);
    const store = new LiveStore(snapshot, () => {
      const socket = new FakeSocket(); sockets.push(socket); return socket as unknown as WebSocket;
    });
    const release = store.retain(); await flush();
    sockets[0].event({ type: 'ready', version: 1, listener_ready: true }); await flush();
    sockets[0].close(); expect(store.getStatus().state).toBe('Reconnecting');
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(2);
    snapshot.mockResolvedValue([]);
    sockets[1].event({ type: 'ready', version: 1, listener_ready: true }); await flush();
    expect(store.getValue(1)).toBeUndefined();
    expect(store.getStatus().state).toBe('Live');
    release();
    await vi.advanceTimersByTimeAsync(60000);
    expect(sockets).toHaveLength(2);
  });

  it('recovers when the API PostgreSQL listener reconnects without closing the socket', async () => {
    const snapshot = vi.fn().mockResolvedValue([value]);
    const socket = new FakeSocket();
    const store = new LiveStore(snapshot, () => socket as unknown as WebSocket);
    const release = store.retain(); await flush();
    socket.event({ type: 'ready', version: 1, listener_ready: false }); await flush();
    expect(store.getStatus().state).toBe('Reconnecting');
    socket.event({ type: 'stream_status', ready: true }); await flush();
    expect(store.getStatus().state).toBe('Live');
    expect(snapshot).toHaveBeenCalledTimes(3);
    release();
  });

  it('requests a fresh snapshot on overflow and does not resurrect an in-flight deletion', async () => {
    let finish!: (values: CurrentValue[]) => void;
    const snapshot = vi.fn().mockResolvedValueOnce([value]).mockImplementationOnce(() => new Promise<CurrentValue[]>((resolve) => { finish = resolve; }));
    const socket = new FakeSocket();
    const store = new LiveStore(snapshot, () => socket as unknown as WebSocket);
    const release = store.retain(); await flush();
    socket.event({ type: 'resync_required' }); socket.event({ type: 'tag_deleted', tag_id: 1 });
    finish([value]); await flush();
    expect(store.getValue(1)).toBeUndefined(); release();
  });

  it('reports malformed events and reconnects instead of applying unchecked data', async () => {
    const socket = new FakeSocket();
    const store = new LiveStore(vi.fn().mockResolvedValue([]), () => socket as unknown as WebSocket);
    const release = store.retain(); await flush();
    socket.event({ type: 'tag_value', data: { tag_id: 1, value: 'wrong' } });
    expect(socket.close).toHaveBeenCalled(); expect(store.getValue(1)).toBeUndefined();
    release();
  });

  it('retains false/zero values and all explicit quality states during parsing', () => {
    for (const quality of ['GOOD', 'STALE', 'BAD', 'COMM_ERROR', 'DISABLED']) {
      const event = parseLiveEvent(JSON.stringify({ type: 'tag_value', data: { ...value, value_boolean: false, value_numeric: null, quality } }));
      expect(event.type === 'tag_value' && event.data.value_boolean).toBe(false);
    }
  });

  it('loads typed REST snapshots through the API client', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify([value]), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    expect(await loadCurrentValues(new AbortController().signal)).toEqual([value]);
    expect(fetch).toHaveBeenCalledWith('/api/tags/values?limit=500&after_tag_id=0', expect.any(Object));
  });
});

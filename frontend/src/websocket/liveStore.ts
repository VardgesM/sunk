import type { Command } from '../types/commands';
import { loadCurrentValues } from '../api/telemetry';
import { parseLiveEvent, type CurrentValue } from '../types/telemetry';

type Listener = () => void;
export interface LiveStatus { state: 'Connecting' | 'Live' | 'Reconnecting' | 'Disconnected'; error: string | null }

function openSocket(): WebSocket {
  const url = new URL('/api/ws/live', window.location.href);
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return new WebSocket(url);
}

export class LiveStore {
  private alarmListeners = new Set<() => void>();
  subscribeAlarms = (callback: () => void): (() => void) => {
    this.alarmListeners.add(callback);
    return () => { this.alarmListeners.delete(callback); };
  };
  private commandListeners = new Set<(command: Command | null) => void>();
  subscribeCommands = (callback: (command: Command | null) => void): (() => void) => {
    this.commandListeners.add(callback);
    return () => { this.commandListeners.delete(callback); };
  };
  private values = new Map<number, CurrentValue>();
  private listeners = new Map<number, Set<Listener>>();
  private statusListeners = new Set<Listener>();
  private status: LiveStatus = { state: 'Disconnected', error: null };
  private users = 0;
  private generation = 0;
  private socket?: WebSocket;
  private abort?: AbortController;
  private reconnect?: ReturnType<typeof setTimeout>;
  private watchdog?: ReturnType<typeof setTimeout>;
  private snapshotRetry?: ReturnType<typeof setTimeout>;
  private attempts = 0;
  private listenerReady = false;
  private syncing = false;
  private syncAgain = false;
  private deleted = new Set<number>();

  constructor(private snapshot = loadCurrentValues, private createSocket = openSocket) {}

  getValue = (id: number): CurrentValue | undefined => this.values.get(id);
  getStatus = (): LiveStatus => this.status;
  subscribeStatus = (callback: Listener): (() => void) => {
    this.statusListeners.add(callback);
    return () => { this.statusListeners.delete(callback); };
  };
  subscribe(id: number, callback: Listener): () => void {
    const callbacks = this.listeners.get(id) ?? new Set<Listener>();
    callbacks.add(callback); this.listeners.set(id, callbacks);
    return () => { callbacks.delete(callback); if (!callbacks.size) this.listeners.delete(id); };
  }
  private setStatus(state: LiveStatus['state'], error: string | null = null) {
    if (this.status.state === state && this.status.error === error) return;
    this.status = { state, error }; this.statusListeners.forEach((callback) => callback());
  }
  private merge(value: CurrentValue) {
    const old = this.values.get(value.tag_id);
    if (old && old.revision > value.revision || this.deleted.has(value.tag_id)) return;
    this.values.set(value.tag_id, value);
    this.listeners.get(value.tag_id)?.forEach((callback) => callback());
  }
  private remove(id: number) {
    this.values.delete(id); this.listeners.get(id)?.forEach((callback) => callback());
  }

  retain(): () => void {
    this.users += 1;
    if (this.users === 1) {
      const generation = ++this.generation;
      this.setStatus('Connecting');
      // Initial REST snapshot first. A second snapshot after ready closes the connection gap.
      void this.sync(generation).finally(() => { if (generation === this.generation) this.connect(generation); });
    }
    let released = false;
    return () => {
      if (released) return;
      released = true; this.users -= 1;
      if (this.users === 0) this.stop();
    };
  }

  private async sync(generation: number): Promise<void> {
    if (this.syncing) { this.syncAgain = true; return; }
    this.syncing = true;
    clearTimeout(this.snapshotRetry);
    const before = new Map(this.values);
    const controller = new AbortController(); this.abort = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const snapshot = await this.snapshot(controller.signal);
      if (generation !== this.generation) return;
      snapshot.forEach((value) => this.merge(value));
      const identifiers = new Set(snapshot.map((value) => value.tag_id));
      before.forEach((value, id) => {
        if (!identifiers.has(id) && this.values.get(id) === value) this.remove(id);
      });
      // Values created by live events during the snapshot must survive its older view.
      this.deleted.forEach((id) => this.remove(id)); this.deleted.clear();
      if (this.listenerReady) { this.attempts = 0; this.setStatus('Live'); }
    } catch (reason) {
      if (generation !== this.generation) return;
      this.setStatus('Reconnecting', reason instanceof Error ? reason.message : 'Snapshot failed');
      clearTimeout(this.snapshotRetry);
      this.snapshotRetry = setTimeout(() => { void this.sync(generation); }, 3000);
    } finally {
      clearTimeout(timeout);
      if (generation === this.generation) {
        this.syncing = false;
        if (this.syncAgain) { this.syncAgain = false; void this.sync(generation); }
      }
    }
  }

  private connect(generation: number) {
    let socket: WebSocket;
    try { socket = this.createSocket(); }
    catch (reason) { this.retry(generation, reason instanceof Error ? reason.message : 'Connection failed'); return; }
    this.socket = socket;
    const watch = (milliseconds: number) => {
      clearTimeout(this.watchdog);
      this.watchdog = setTimeout(() => socket.close(), milliseconds);
    };
    watch(10000);
    socket.onopen = () => { if (generation === this.generation) watch(45000); };
    socket.onmessage = (message) => {
      if (generation !== this.generation || socket !== this.socket) return;
      watch(45000);
      try {
        const event = parseLiveEvent(String(message.data));
        if (event.type === 'alarm_event') this.alarmListeners.forEach(callback => callback());
        else if (event.type === 'command_status') this.commandListeners.forEach((callback) => callback(event.data));
        else if (event.type === 'tag_value') this.merge(event.data);
        else if (event.type === 'tag_deleted') { this.deleted.add(event.tag_id); this.remove(event.tag_id); }
        else if (event.type === 'resync_required') { this.commandListeners.forEach((callback) => callback(null)); this.alarmListeners.forEach(callback => callback()); void this.sync(generation); }
        else {
          const ready = event.type === 'stream_status' ? event.ready : event.listener_ready;
          const restored = !this.listenerReady && ready;
          this.listenerReady = ready;
          if (!ready) this.setStatus('Reconnecting', 'Waiting for PostgreSQL live updates');
          if (restored || event.type === 'ready') { this.commandListeners.forEach((callback) => callback(null)); this.alarmListeners.forEach(callback => callback()); void this.sync(generation); }
        }
      } catch (reason) {
        this.setStatus('Reconnecting', reason instanceof Error ? reason.message : 'Invalid live message');
        socket.close();
      }
    };
    socket.onerror = () => socket.close();
    socket.onclose = (event) => {
      if (event?.code === 4401) { window.dispatchEvent(new Event('auth-expired')); return; }
      if (generation !== this.generation || socket !== this.socket) return;
      clearTimeout(this.watchdog); this.listenerReady = false;
      this.retry(generation);
    };
  }
  private retry(generation: number, error: string | null = null) {
    this.setStatus('Reconnecting', error);
    clearTimeout(this.reconnect);
    this.reconnect = setTimeout(() => {
      if (generation === this.generation) this.connect(generation);
    }, Math.min(30000, 1000 * 2 ** this.attempts++));
  }
  reset() { this.stop(); }
  private stop() {
    this.generation += 1; this.abort?.abort();
    clearTimeout(this.reconnect); clearTimeout(this.watchdog); clearTimeout(this.snapshotRetry);
    if (this.socket) {
      this.socket.onopen = this.socket.onmessage = this.socket.onclose = this.socket.onerror = null;
      this.socket.close(); this.socket = undefined;
    }
    this.syncing = false; this.syncAgain = false; this.listenerReady = false; this.attempts = 0;
    this.values.clear(); this.deleted.clear(); this.setStatus('Disconnected');
  }
}

export const liveStore = new LiveStore();

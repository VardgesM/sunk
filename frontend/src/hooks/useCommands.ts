import { useCallback, useEffect, useState } from 'react';
import { getCommands } from '../api/commands';
import type { Command } from '../types/commands';
import { liveStore } from '../websocket/liveStore';

export function mergeCommands(rows: Command[], changes: Command[]): Command[] {
  const merged = new Map(rows.map((row) => [row.id, row]));
  changes.forEach((row) => { if ((merged.get(row.id)?.revision ?? 0) <= row.revision) merged.set(row.id, row); });
  return [...merged.values()].sort((a, b) => b.id - a.id).slice(0, 100);
}

export function useCommands(query = '') {
  const [rows, setRows] = useState<Command[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((value) => value + 1), []);
  const matches = useCallback((row: Command) => {
    const filters = new URLSearchParams(query);
    return ['status', 'tag_id', 'device_id'].every((key) => !filters.get(key) || String(row[key as keyof Command]) === filters.get(key));
  }, [query]);
  useEffect(() => liveStore.retain(), []);
  useEffect(() => {
    const controller = new AbortController();
    let current: Command[] = [];
    const unsubscribe = liveStore.subscribeCommands((command) => {
      if (!command) { reload(); return; }
      current = mergeCommands(current, [command]);
      setRows((old) => mergeCommands(old, [command]).filter(matches));
    });
    getCommands(query, controller.signal).then((snapshot) => {
      if (!controller.signal.aborted) { setRows(mergeCommands(snapshot, current).filter(matches)); setError(''); setLoading(false); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'Could not load commands'); setLoading(false); }
    });
    return () => { controller.abort(); unsubscribe(); };
  }, [query, refresh, reload, matches]);
  return { rows: rows.filter(matches), error, loading, reload };
}

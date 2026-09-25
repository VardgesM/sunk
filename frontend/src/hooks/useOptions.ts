import { useEffect, useState } from 'react';
import type { CrudApi } from '../api/configuration';
import type { Entity } from '../types/configuration';

export function useOptions<T extends Entity>(api: CrudApi<T>, revision = 0) {
  const [rows, setRows] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError('');
      try { setRows(await api.all(controller.signal)); }
      catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load options'); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [api, revision]);
  return { rows, loading, error };
}

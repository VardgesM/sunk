import { useEffect, useState } from 'react';
import { request } from '../api/client';

export function useRuntime<T>(path: string) {
  const [result, setResult] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const data = await request<T>(path, { signal: controller.signal });
        if (!controller.signal.aborted) setResult({ data });
      } catch (error) {
        if (!controller.signal.aborted) setResult({ error: error instanceof Error ? error.message : 'Runtime unavailable' });
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 5000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path]);
  return result;
}

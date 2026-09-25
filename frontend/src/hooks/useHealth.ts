import { useEffect, useState } from 'react';
import { getHealth } from '../api/client';

type HealthState = { status: 'checking' | 'ok' | 'error'; message: string };

export function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ status: 'checking', message: 'Checking API' });
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function check() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      try {
        await getHealth(controller.signal);
        if (!disposed) setState({ status: 'ok', message: 'API online' });
      } catch (error: unknown) {
        if (!disposed) setState({ status: 'error', message: error instanceof Error ? error.message : 'API unavailable' });
      } finally {
        clearTimeout(timeout);
        if (!disposed) timer = setTimeout(() => { void check(); }, 15000);
      }
    }
    void check();
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
  }, []);
  return state;
}

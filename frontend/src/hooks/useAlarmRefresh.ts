import { useEffect, useState } from 'react';
import { liveStore } from '../websocket/liveStore';
// REST is authoritative. Event bursts are coalesced; reconnect also invalidates snapshots.
export function useAlarmRefresh(): number {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const release = liveStore.retain();
    const unsubscribe = liveStore.subscribeAlarms(() => {
      if (timer) return;
      timer = setTimeout(() => { timer = undefined; setRevision(v => v + 1); }, 100);
    });
    const interval = setInterval(() => setRevision(v => v + 1), 15000);
    return () => { clearTimeout(timer); clearInterval(interval); unsubscribe(); release(); };
  }, []);
  return revision;
}

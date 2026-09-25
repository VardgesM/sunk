import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { liveStore } from '../websocket/liveStore';

export function useLiveStatus() {
  useEffect(() => liveStore.retain(), []);
  return useSyncExternalStore(liveStore.subscribeStatus, liveStore.getStatus);
}

export function useTagValue(tagId: number) {
  const subscribe = useCallback((callback: () => void) => liveStore.subscribe(tagId, callback), [tagId]);
  const get = useCallback(() => liveStore.getValue(tagId), [tagId]);
  return useSyncExternalStore(subscribe, get);
}

import { useEffect, useState } from 'react';
import { Stack, Typography } from '@mui/material';
import { request } from '../api/client';
import { useAuth } from '../auth/context';
import StatusBadge from '../components/data/StatusBadge';

interface SyncSummary {
  mode: string; last_sync_at: string | null; error: string | null;
  edges: { name: string; enabled: boolean; state: string }[];
}

// The existing System endpoint, with only operational connectivity shown here.
// No runtime diagnostics, queue contents, configuration or identifiers are fetched separately.
export default function DashboardConnectivity() {
  const mode = useAuth().user?.application_mode;
  const [result, setResult] = useState<{ data: SyncSummary; checked: number }>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (mode !== 'edge' && mode !== 'cloud') return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const data = await request<SyncSummary>('/sync/status', { signal: controller.signal });
        if (!controller.signal.aborted) { setResult({ data, checked: Date.now() }); setFailed(false); }
      } catch { if (!controller.signal.aborted) setFailed(true); }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), 5000); }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [mode]);
  if (mode !== 'edge' && mode !== 'cloud') return null;
  if (failed || !result) return <Typography variant="body2">Connectivity: {failed ? 'unavailable' : 'loading...'}</Typography>;
  if (result.data.mode === 'edge') {
    const connected = !result.data.error && result.data.last_sync_at && result.checked - Date.parse(result.data.last_sync_at) < 30000;
    return <Stack direction="row" gap={1} alignItems="center"><Typography variant="body2">Cloud sync</Typography><StatusBadge label={connected ? 'CONNECTED' : 'DISCONNECTED'} /></Stack>;
  }
  const edges = result.data.edges.filter(edge => edge.enabled);
  const offline = edges.filter(edge => edge.state !== 'ONLINE');
  return <Stack spacing={0.5}>
    <Typography variant="body2">{!edges.length ? 'No enabled Edge installations' : `Edge: ${edges.length - offline.length} / ${edges.length} ONLINE`}</Typography>
    {!!offline.length && <Typography variant="body2" color="warning.dark" sx={{ overflowWrap: 'anywhere' }}>{offline.map(edge => `${edge.name}: ${edge.state}`).join(' · ')}</Typography>}
  </Stack>;
}

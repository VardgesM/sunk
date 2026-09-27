import Can from '../auth/Can';
import { useEffect, useState } from 'react';
import { Alert, Button, Stack, Typography } from '@mui/material';
import { alarmsApi } from '../api/alarms';
import { useAlarmRefresh } from '../hooks/useAlarmRefresh';
import type { AlarmEvent } from '../types/alarms';
import type { WidgetConfig } from '../types/dashboards';

export default function AlarmWidget({ config }: { config: WidgetConfig }) {
  const revision = useAlarmRefresh();
  const [refresh, setRefresh] = useState(0);
  const [rows, setRows] = useState<AlarmEvent[]>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    // Each severity is filtered server-side, then the bounded results are merged.
    Promise.all((config.severities ?? ['INFO', 'WARNING', 'CRITICAL']).map(severity => alarmsApi.events(`severity=${severity}${config.active_only !== false ? '&active=true' : ''}`)))
      .then(results => { if (!cancelled) { setRows(results.flat().sort((a,b) => b.id - a.id).slice(0, config.maximum_rows ?? 10)); setError(''); } })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Alarms unavailable'); });
    return () => { cancelled = true; };
  }, [config, revision, refresh]);
  async function acknowledge(id: number) {
    setBusy(true);
    try { await alarmsApi.acknowledge(id); setRefresh(v => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : 'Acknowledge failed'); }
    finally { setBusy(false); }
  }
  return <Stack spacing={1}>{error && <Alert severity="error">{error}</Alert>}
    {!rows && !error && <Typography role="status">Loading alarms...</Typography>}
    {rows?.length === 0 && <Typography>No matching alarms</Typography>}
    {rows?.map(row => <Stack key={row.id} spacing={.5} sx={{ borderBottom: 1, borderColor: 'divider', pb: 1 }}>
      <Typography fontWeight={700}>{row.severity}: {row.name}</Typography>
      <Typography>{row.tag_name} - {row.state}</Typography>
      <Typography variant="caption">{new Date(row.activated_at).toLocaleString()}</Typography>
      {row.state === 'ACTIVE' && <Can permission="acknowledge"><Button disabled={busy} onClick={() => void acknowledge(row.id)}>Acknowledge</Button></Can>}
    </Stack>)}
  </Stack>;
}

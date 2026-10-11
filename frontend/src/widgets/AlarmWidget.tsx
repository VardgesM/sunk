import Can from '../auth/Can';
import { useEffect, useState } from 'react';
import { Alert, Button, Chip, Stack, Typography } from '@mui/material';
import { alarmsApi } from '../api/alarms';
import { useAlarmRefresh } from '../hooks/useAlarmRefresh';
import type { AlarmEvent } from '../types/alarms';
import type { WidgetConfig } from '../types/dashboards';

const severityOrder = { CRITICAL: 0, WARNING: 1, INFO: 2 };
function alarmOrder(a: AlarmEvent, b: AlarmEvent) {
  return Number(a.state === 'CLEARED') - Number(b.state === 'CLEARED') || severityOrder[a.severity] - severityOrder[b.severity] || b.id - a.id;
}

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
      .then(results => { if (!cancelled) { setRows(results.flat().sort(alarmOrder).slice(0, config.maximum_rows ?? 10)); setError(''); } })
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
    {rows?.length === 0 && <Typography color="text.secondary">No matching {config.active_only !== false ? 'active ' : ''}alarms</Typography>}
    {rows?.map(row => <Stack key={row.id} component="section" aria-label={`${row.severity}: ${row.name}`} spacing={1} sx={{ border: 1, borderInlineStartWidth: 4, borderColor: row.state === 'CLEARED' ? 'divider' : row.severity === 'CRITICAL' ? 'error.main' : row.severity === 'WARNING' ? 'warning.main' : 'info.main', borderRadius: 1, p: 1.5, minWidth: 0, overflowWrap: 'anywhere' }}>
      <Stack direction="row" flexWrap="wrap" gap={1}><Chip size="small" label={row.severity} color={row.severity === 'CRITICAL' ? 'error' : row.severity === 'WARNING' ? 'warning' : 'info'} /><Chip size="small" label={row.state} variant="outlined" /></Stack>
      <Typography fontWeight={700}>{row.name}</Typography>
      <Typography variant="body2">{row.tag_name}</Typography>
      <Typography variant="caption" color="text.secondary">Activated: <time dateTime={row.activated_at}>{new Date(row.activated_at).toLocaleString()}</time></Typography>
      {row.state === 'ACTIVE' && <Can permission="acknowledge"><Button disabled={busy} onClick={() => void acknowledge(row.id)}>Acknowledge</Button></Can>}
    </Stack>)}
  </Stack>;
}

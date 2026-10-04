import { Fragment, useEffect, useState } from 'react';
import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material';
import { getSystemDiagnostics, type SystemDiagnostics as Diagnostics } from '../api/runtime';

function timestamp(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : 'UNKNOWN';
}

function age(value: string | null | undefined, checkedAt: string): string {
  if (!value) return 'UNKNOWN';
  const seconds = Math.round((Date.parse(checkedAt) - Date.parse(value)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return timestamp(value);
  const [divisor, unit] = seconds >= 86400 ? [86400, 'day'] as const
    : seconds >= 3600 ? [3600, 'hour'] as const
    : seconds >= 60 ? [60, 'minute'] as const : [1, 'second'] as const;
  return new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(-Math.floor(seconds / divisor), unit);
}

function uptime(seconds: number | null | undefined): string {
  if (seconds == null) return 'UNKNOWN';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor(seconds % 86400 / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}

export default function SystemDiagnostics() {
  const [data, setData] = useState<Diagnostics>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void getSystemDiagnostics(controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(String(reason));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  const rows: [string, string | number][] = data ? [
    ['Database', data.database_status ?? 'UNKNOWN'],
    ['Database query latency', data.database_latency_ms == null ? 'UNKNOWN' : `${data.database_latency_ms} ms`],
    ['Telemetry freshness', data.telemetry_status ?? 'UNKNOWN'],
    ['Last successful telemetry', age(data.last_telemetry_at, data.checked_at)],
    ['Synchronization', data.sync_status ?? 'UNKNOWN'],
    ['Pending sync', data.pending_sync_count ?? 'UNKNOWN'],
    ['Last successful sync', age(data.last_sync_at, data.checked_at)],
    ['Backup status', data.backup_status ?? 'UNKNOWN'],
    ['Last successful backup', timestamp(data.last_backup_at)],
    ['Disk free (backup storage)', data.disk_free_bytes == null ? 'UNKNOWN' : `${(data.disk_free_bytes / 1024 ** 3).toFixed(1)} GiB`],
    ['API hostname', data.hostname ?? 'UNKNOWN'],
    ['API uptime', uptime(data.uptime_seconds)],
  ] : [];

  return <Paper component="section" aria-labelledby="diagnostics-heading" variant="outlined" sx={{ p: 2 }}>
    <Stack spacing={1}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography id="diagnostics-heading" component="h2" variant="h6">Diagnostics</Typography>
        <Button disabled={loading} onClick={() => {
          setLoading(true); setError(''); setData(undefined); setRefresh(value => value + 1);
        }}>Refresh diagnostics</Button>
      </Stack>
      {loading ? <Typography role="status">Loading diagnostics...</Typography>
        : error ? <Alert severity="error">Unable to load diagnostics: {error}</Alert>
        : <>
          <Typography variant="caption">Snapshot: {timestamp(data?.checked_at)}. Refresh to update.</Typography>
          <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 1, overflowWrap: 'anywhere' }}>
            {rows.map(([label, value]) => <Fragment key={label}>
              <Typography component="dt" variant="body2" color="text.secondary">{label}</Typography>
              <Typography component="dd" variant="body2" sx={{ m: 0 }}>{value}</Typography>
            </Fragment>)}
          </Box>
          <Typography variant="caption">API host/container metrics. Cloud cannot report the Edge outbox size or last completed Edge sync cycle.</Typography>
        </>}
    </Stack>
  </Paper>;
}

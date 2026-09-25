import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Chip, Stack, Typography } from '@mui/material';
import { useRuntime } from '../hooks/useRuntime';
import { getTest, testConnection, type DeviceStatus, type SystemRuntime, type TestResult, type TransportStatus } from '../api/runtime';

export function SourceMode() {
  const { data, error } = useRuntime<SystemRuntime>('/system/runtime');
  if (!data || error || !data.alive) return <Alert severity="warning" sx={{ mb: 2 }}>Telemetry worker unavailable — source mode unknown</Alert>;
  if (data.mode === 'simulator') return <Alert severity="warning" sx={{ mb: 2 }}>SIMULATION MODE — development values, no device communication</Alert>;
  if (data.mode === 'disabled') return <Alert severity="info" sx={{ mb: 2 }}>Telemetry collection is disabled</Alert>;
  return <Chip label={data.writes_enabled ? 'Modbus — physical writes enabled' : 'Modbus — read only (writes disabled)'} size="small" sx={{ mb: 2 }} />;
}

export function ConnectionState({ id }: { id: number }) {
  const { data, error } = useRuntime<TransportStatus>(`/connections/${id}/status`);
  return <Stack spacing={.5}><Chip size="small" label={data?.state ?? 'UNKNOWN'} />
    <Typography variant="caption">Last communication: {data?.last_success ? new Date(data.last_success).toLocaleString() : 'not yet verified'}</Typography>
    {(error || data?.last_error) && <Typography variant="caption" color="error">{error || data?.last_error}</Typography>}
  </Stack>;
}

export function DeviceState({ id }: { id: number }) {
  const { data, error } = useRuntime<DeviceStatus>(`/devices/${id}/status`);
  return <Chip size="small" label={error ? 'UNKNOWN' : data?.state ?? 'UNKNOWN'} title={error ?? (data?.last_success ? new Date(data.last_success).toLocaleString() : 'No successful read')} />;
}

export function TestConnection({ id, name }: { id: number; name: string }) {
  const [result, setResult] = useState<TestResult>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { controller.current?.abort(); clearTimeout(timer.current); }, []);
  async function run() {
    controller.current?.abort(); clearTimeout(timer.current);
    const request = new AbortController(); controller.current = request;
    setBusy(true); setError(''); setResult(undefined);
    async function poll(next: TestResult) {
      if (request.signal.aborted) return;
      setResult(next);
      if (next.state !== 'PENDING') { setBusy(false); return; }
      timer.current = setTimeout(() => {
        getTest(id, request.signal).then(poll).catch(failed);
      }, 1000);
    }
    function failed(reason: unknown) {
      if (request.signal.aborted) return;
      setBusy(false); setError(reason instanceof Error ? reason.message : 'Transport test failed');
    }
    testConnection(id, request.signal).then(poll).catch(failed);
  }
  return <Stack spacing={1} sx={{ minWidth: 160 }}>
    <Button disabled={busy} onClick={() => void run()} aria-label={`Test ${name}`}>{busy ? 'Testing…' : 'Test transport'}</Button>
    {error && <Alert severity="error">{error}</Alert>}
    {result && <Typography variant="caption">{result.state}: {result.message ?? 'Waiting for worker'}{result.latency_ms !== null ? ` (${Math.round(result.latency_ms)} ms)` : ''}</Typography>}
  </Stack>;
}

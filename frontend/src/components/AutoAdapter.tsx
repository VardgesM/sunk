import { useEffect, useState } from 'react';
import { Alert, Button, Stack, Typography } from '@mui/material';
import { discoverSerial, type SerialPorts, type SerialAdapter } from '../api/runtime';
function adapterLabel(port: SerialAdapter): string {
  const hex = (value: number | null | undefined) => value == null ? '?' : value.toString(16).toUpperCase().padStart(4, '0');
  return `${port.product || port.description} ? ${port.device} ? ${port.manufacturer || 'Manufacturer unknown'} ? VID ${hex(port.vid)} / PID ${hex(port.pid)} ? Serial ${port.serial_number || 'not provided'}`;
}
export default function AutoAdapter({ select }: { select: (port: SerialAdapter) => void }) {
  const [result, setResult] = useState<SerialPorts>(); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; void discoverSerial().then(v => { if (active) setResult(v); }).catch(e => { if (active) setError(String(e)); }); return () => { active = false; }; }, []);
  const ports = result?.ports.filter(p => p.vid != null && p.pid != null) ?? [];
  return <Stack spacing={1}>
    <Button disabled={busy} onClick={() => { setBusy(true); setError(''); void discoverSerial().then(setResult).catch(e => setError(String(e))).finally(() => setBusy(false)); }}>Refresh adapters</Button>
    {error && <Alert severity="warning">{error}</Alert>}
    {result?.error && <Alert severity="warning">{result.error}</Alert>}
    {!result && !error && <Typography>Loading worker adapters?</Typography>}
    {result && !ports.length && <Typography>No USB adapters visible to worker. Check USB connection, drivers or container device mapping. Manual mode remains available.</Typography>}
    {ports.map(p => <Button key={p.device} sx={{ textAlign: 'left', justifyContent: 'flex-start', overflowWrap: 'anywhere' }} onClick={() => select(p)}>{adapterLabel(p)}</Button>)}
    <Typography variant="caption">Choose the adapter once. The displayed port is its current location; Auto mode stores USB identity, not a COM number. Enumeration refreshes periodically on the worker.</Typography>
  </Stack>;
}

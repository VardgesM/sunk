import { useState } from 'react';
import { Alert, Button, Stack, Typography } from '@mui/material';
import { discoverSerial, type SerialPorts } from '../api/runtime';

export default function SerialDiscovery({ select }: { select: (port: string) => void }) {
  const [result, setResult] = useState<SerialPorts>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  return <Stack spacing={1}>
    <Button disabled={busy} onClick={() => { setBusy(true); setError(''); discoverSerial().then(setResult).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Discovery failed')).finally(() => setBusy(false)); }}>Discover serial ports</Button>
    {error && <Alert severity="warning">{error}. Manual port entry remains available.</Alert>}
    {result && <>
      <Typography variant="body2">Ports visible to worker host: {result.worker_host}</Typography>
      {result.error && <Alert severity="warning">{result.error}</Alert>}
      {!result.ports.length && <Typography variant="body2">No ports discovered. Container ports differ from host ports; you can still enter a port manually.</Typography>}
      {result.ports.map((port) => <Button key={port.device} onClick={() => select(port.device)}>{port.device} — {port.description}</Button>)}
    </>}
  </Stack>;
}

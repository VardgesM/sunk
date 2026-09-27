import Can from '../auth/Can';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Alert, Button, Chip, MenuItem, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@mui/material';
import { useCommands } from '../hooks/useCommands';
import { commandStatuses, commandValue } from '../types/commands';
import { cancelCommand } from '../api/commands';

export default function CommandsPage() {
  const [params] = useSearchParams();
  const [commandId, setCommandId] = useState(params.get('command_id') || '');
  const [status, setStatus] = useState('');
  const [device, setDevice] = useState('');
  const [tag, setTag] = useState('');
  const [error, setError] = useState('');
  const query = new URLSearchParams();
  if (commandId) query.set('command_id', commandId);
  if (status) query.set('status', status);
  if (device) query.set('device_id', device);
  if (tag) query.set('tag_id', tag);
  const commands = useCommands(query.toString());
  return <Stack spacing={2}>
    <Typography variant="h4" component="h1">Commands</Typography>
    <Typography>Latest 100 matching commands. Requested values are separate from verified actual values.</Typography>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
      <TextField select label="Status" value={status} onChange={(event) => setStatus(event.target.value)} sx={{ minWidth: 180 }}><MenuItem value="">All</MenuItem>{commandStatuses.map((state) => <MenuItem key={state} value={state}>{state}</MenuItem>)}</TextField>
      <TextField label="Command ID" value={commandId} onChange={(event) => setCommandId(event.target.value)} />
      <TextField label="Device ID" value={device} onChange={(event) => setDevice(event.target.value)} />
      <TextField label="Tag ID" value={tag} onChange={(event) => setTag(event.target.value)} />
      <Button onClick={commands.reload}>Refresh</Button>
    </Stack>
    {(commands.error || error) && <Alert severity="error">{commands.error || error}</Alert>}
    {commands.loading ? <Typography role="status">Loading commands…</Typography> : !commands.rows.length ? <Typography>No commands match these filters.</Typography> : <TableContainer>
      <Table size="small"><TableHead><TableRow>{['ID', 'Created', 'Tag / Device', 'Requested', 'Verified', 'Status', 'Source / Mode / User', 'Attempts', 'Error / Action'].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
        <TableBody>{commands.rows.map((row) => <TableRow key={row.id}>
          <TableCell>{row.id}</TableCell><TableCell>{new Date(row.created_at).toLocaleString()}</TableCell>
          <TableCell><Link to={`/tags/${row.tag_id}`}>{row.tag_name}</Link><br />{row.device_name}</TableCell>
          <TableCell>{commandValue(row.requested_value)}</TableCell><TableCell>{commandValue(row.verified_value)}</TableCell>
          <TableCell><Chip size="small" label={row.status} /></TableCell><TableCell>{row.source} / {row.telemetry_mode}<br />{row.requested_by_username ?? (row.source === 'automation' ? 'Automation' : 'Legacy / system')}</TableCell><TableCell>{row.attempt_count}</TableCell>
          <TableCell>{row.error_message}{row.status === 'QUEUED' && <Can permission="command"><Button onClick={() => { void cancelCommand(row.id).then(commands.reload).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Cancellation failed')); }}>Cancel</Button></Can>}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </TableContainer>}
  </Stack>;
}

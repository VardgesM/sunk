import Can from '../auth/Can';
import { usePermission } from '../auth/context';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { useCommands } from '../hooks/useCommands';
import { commandStatuses, commandValue, type Command } from '../types/commands';
import { cancelCommand } from '../api/commands';
import ResponsiveDataView from '../components/data/ResponsiveDataView';
import MobileDataCard, { DetailFields } from '../components/data/MobileDataCard';
import RowActions from '../components/data/RowActions';
import StatusBadge from '../components/data/StatusBadge';
import FilterPanel from '../components/data/FilterPanel';
import { shellLayout } from '../layout/tokens';

const timestamp = (value: string | null) => value ? new Date(value).toLocaleString() : 'Not available';
const requester = (row: Command) => row.requested_by_username ?? (row.source === 'automation' ? 'Automation' : 'Legacy / system');

export default function CommandsPage() {
  const [params] = useSearchParams();
  const [commandId, setCommandId] = useState(params.get('command_id') || '');
  const [status, setStatus] = useState('');
  const [device, setDevice] = useState('');
  const [tag, setTag] = useState('');
  const [error, setError] = useState('');
  const canCommand = usePermission('command');
  const query = new URLSearchParams();
  if (commandId) query.set('command_id', commandId);
  if (status) query.set('status', status);
  if (device) query.set('device_id', device);
  if (tag) query.set('tag_id', tag);
  const commands = useCommands(query.toString());
  function cancel(id: number) {
    void cancelCommand(id).then(commands.reload).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Cancellation failed'));
  }
  const activeFilters = [commandId && `Command: ${commandId}`, status && `Status: ${status}`, device && `Device: ${device}`, tag && `Tag: ${tag}`].filter(Boolean) as string[];
  return <Stack spacing={2} sx={{ minWidth: 0, overflowWrap: 'anywhere', '& .MuiButton-root': { minHeight: shellLayout.touchTarget }, '& .MuiAlert-message': { minWidth: 0 } }}>
    <Typography variant="h4" component="h1">Commands</Typography>
    <Typography>Latest 100 matching commands. Requested values are separate from verified actual values.</Typography>
    <FilterPanel active={activeFilters} onReset={() => { setCommandId(''); setStatus(''); setDevice(''); setTag(''); }}>
      <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, '& .MuiFormControl-root': { minWidth: 0 } }}>
        <TextField select label="Status" value={status} onChange={(event) => setStatus(event.target.value)}><MenuItem value="">All</MenuItem>{commandStatuses.map((state) => <MenuItem key={state} value={state}>{state}</MenuItem>)}</TextField>
        <TextField label="Command ID" value={commandId} onChange={(event) => setCommandId(event.target.value)} />
        <TextField label="Device ID" value={device} onChange={(event) => setDevice(event.target.value)} />
        <TextField label="Tag ID" value={tag} onChange={(event) => setTag(event.target.value)} />
        <Button variant="outlined" onClick={commands.reload}>Refresh</Button>
      </Box>
    </FilterPanel>
    {(commands.error || error) && <Alert severity="error">{commands.error || error}</Alert>}
    {commands.loading ? <Typography role="status">Loading commands…</Typography> : !commands.rows.length ? !commands.error && <Typography>{query.size ? 'No commands match these filters.' : 'No commands yet.'}</Typography> : <ResponsiveDataView label="Commands" rows={commands.rows} columns={[
      { label: 'ID', minWidth: 48, render: row => row.id },
      { label: 'Created', render: row => timestamp(row.created_at) },
      { label: 'Tag / Device', minWidth: 180, render: row => <><Link to={`/tags/${row.tag_id}`}>{row.tag_name}</Link><br />{row.device_name}</> },
      { label: 'Requested', render: row => commandValue(row.requested_value) },
      { label: 'Verified', render: row => commandValue(row.verified_value) },
      { label: 'Status', render: row => <StatusBadge label={row.status} /> },
      { label: 'Source / Mode / User', render: row => <>{row.source} / {row.telemetry_mode}<br />{requester(row)}</> },
      { label: 'Attempts', render: row => row.attempt_count },
      { label: 'Error / Action', render: row => <>{row.error_message}{row.status === 'QUEUED' && <Can permission="command"><Button onClick={() => cancel(row.id)}>Cancel</Button></Can>}</> },
    ]} card={row => <MobileDataCard name={row.tag_name} status={<StatusBadge label={row.status} />}
      primary={<Typography variant="h6" component="p">Requested: {commandValue(row.requested_value)}</Typography>}
      details={<DetailFields fields={[
        ['Command ID', row.id], ['Request ID', row.request_id], ['Previous value', commandValue(row.previous_value)],
        ['Started', timestamp(row.started_at)], ['Expires', timestamp(row.expires_at)], ['Source / mode', `${row.source} / ${row.telemetry_mode}`],
        ['Requested by', requester(row)], ['Attempts', row.attempt_count],
      ]} />}
      actions={<><Button component={Link} to={`/tags/${row.tag_id}`}>Tag details</Button><RowActions name={`command ${row.id}`} actions={row.status === 'QUEUED' && canCommand ? [{ label: 'Cancel command', run: () => cancel(row.id) }] : []} /></>}>
      <DetailFields fields={[
        ['Verified / read-back', commandValue(row.verified_value)], ['Device', row.device_name], ['Requested at', timestamp(row.created_at)],
        ...(row.completed_at ? [['Completed', timestamp(row.completed_at)] as [string, string]] : []),
      ]} />
      {row.error_message && <Alert severity="error">{row.error_message}</Alert>}
    </MobileDataCard>} />}
  </Stack>;
}

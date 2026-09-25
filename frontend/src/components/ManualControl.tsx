import { useRef, useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { createCommand, cancelCommand } from '../api/commands';
import type { SystemRuntime } from '../api/runtime';
import type { Tag } from '../types/configuration';
import { activeCommand, commandValue, type Command } from '../types/commands';
import { useCommands } from '../hooks/useCommands';
import { useRuntime } from '../hooks/useRuntime';
import { LiveValue } from './LiveValues';

export default function ManualControl({ tag }: { tag: Tag }) {
  const { data: runtime } = useRuntime<SystemRuntime>('/system/runtime');
  const commands = useCommands(`tag_id=${tag.id}`);
  const [submitted, setSubmitted] = useState<Command>();
  const observed = commands.rows[0];
  const latest = submitted && (!observed || submitted.id > observed.id || submitted.id === observed.id && submitted.revision > observed.revision) ? submitted : observed;
  const [value, setValue] = useState('');
  const [on, setOn] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{ value: string | boolean; id: string } | null>(null);
  const physical = runtime?.mode === 'modbus';
  const available = tag.enabled && runtime?.alive && (runtime.mode === 'simulator' || physical && runtime.writes_enabled);
  const boolean = tag.register_type === 'coil';
  async function send() {
    const requested = boolean ? on : value;
    if (!pending.current || pending.current.value !== requested) pending.current = { value: requested, id: crypto.randomUUID() };
    setBusy(true); setError(''); setConfirm(false);
    try { const result = await createCommand(tag.id, requested, pending.current.id, physical); setSubmitted(result); pending.current = null; commands.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Command request failed'); }
    finally { setBusy(false); }
  }
  async function cancel() {
    if (!latest) return;
    try { await cancelCommand(latest.id); commands.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Cancellation failed'); }
  }
  return <Stack spacing={2}>
    <Typography variant="h6">Manual control</Typography>
    {!available && <Alert severity="warning">Writes unavailable: physical writes are disabled, configuration is disabled, or the worker is offline.</Alert>}
    {runtime?.mode === 'simulator' && <Alert severity="info">Simulated control — no physical device write.</Alert>}
    <Typography>Actual: <LiveValue tagId={tag.id} field="value" control /> {tag.unit}</Typography>
    <LiveValue tagId={tag.id} field="quality" />
    {boolean ? <TextField select label="Requested state" value={on ? 'on' : 'off'} onChange={(event) => setOn(event.target.value === 'on')}>
      <MenuItem value="off">OFF</MenuItem><MenuItem value="on">ON</MenuItem>
    </TextField> : <TextField label="Requested value" value={value} onChange={(event) => setValue(event.target.value)} helperText={`Engineering value${tag.unit ? ` (${tag.unit})` : ''}. Actual changes only after a real read-back.`} slotProps={{ htmlInput: { inputMode: 'decimal' } }} />}
    <Button variant="contained" disabled={!available || busy || activeCommand(latest) || !boolean && !value.trim()} onClick={() => physical ? setConfirm(true) : void send()}>Apply</Button>
    {(error || commands.error) && <Alert severity="error">{error || commands.error}</Alert>}
    {latest && <Stack spacing={1}>
      <Typography>Requested: {commandValue(latest.requested_value)}</Typography>
      <Typography role="status">Status: {latest.status}</Typography>
      <Typography>Verified: {commandValue(latest.verified_value)}</Typography>
      {latest.error_message && <Alert severity="error">{latest.error_message}</Alert>}
      {latest.status === 'QUEUED' && <Button onClick={() => void cancel()}>Cancel queued command</Button>}
    </Stack>}
    <Dialog open={confirm} onClose={() => setConfirm(false)} fullWidth maxWidth="sm">
      <DialogTitle>Confirm physical write</DialogTitle>
      <DialogContent>Write {boolean ? on ? 'ON' : 'OFF' : value} {tag.unit} to {tag.name} ({tag.key})? This changes a physical device. Verification failure does not undo the write.</DialogContent>
      <DialogActions><Button onClick={() => setConfirm(false)}>Back</Button><Button disabled={!available || busy} onClick={() => void send()}>Confirm write</Button></DialogActions>
    </Dialog>
  </Stack>;
}

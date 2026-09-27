import { usePermission } from '../auth/context';
import Can from '../auth/Can';
import { useEffect, useState } from 'react';
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { alarmsApi } from '../api/alarms';
import { tagsApi } from '../api/configuration';
import type { AlarmEvent, AlarmRule, Delivery } from '../types/alarms';
import type { Tag } from '../types/configuration';
import AlarmEditor from '../components/AlarmEditor';
import { useAlarmRefresh } from '../hooks/useAlarmRefresh';
const time = (value: string | null) => value ? new Date(value).toLocaleString() : '?';

export default function AlarmsPage() {
  const admin = usePermission('configure');
  const live = useAlarmRefresh();
  const [tab, setTab] = useState(0); const [revision, refresh] = useState(0);
  const [events, setEvents] = useState<AlarmEvent[]>([]); const [rules, setRules] = useState<AlarmRule[]>([]);
  const [tags, setTags] = useState<Tag[]>([]); const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [chat, setChat] = useState(''); const [severity, setSeverity] = useState(''); const [state, setState] = useState(''); const [tag, setTag] = useState('');
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState(''); const [success, setSuccess] = useState(''); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<AlarmRule | 'new' | null>(null); const [deleting, setDeleting] = useState<AlarmRule | null>(null);
  useEffect(() => { let active = true; void Promise.all([tagsApi.all(), admin ? alarmsApi.destination() : Promise.resolve({ chat_id: '' })]).then(([items, destination]) => { if (active) { setTags(items); setChat(destination.chat_id); } }).catch(reason => { if (active) setError(String(reason)); }); return () => { active = false; }; }, [admin]);
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ offset: String(offset) });
    if (tab === 0) query.set('active', 'true');
    if (severity) query.set('severity', severity); if (state) query.set('state', state); if (tag) query.set('tag_id', tag);
    void Promise.all([alarmsApi.events(query.toString()), alarmsApi.rules(), admin ? alarmsApi.deliveries() : Promise.resolve([])]).then(([rows, config, sent]) => { if (active) { setEvents(rows); setRules(config); setDeliveries(sent); setError(''); } }).catch(reason => { if (active) setError(String(reason)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [live, revision, tab, severity, state, tag, offset, admin]);
  async function action(fn: () => Promise<unknown>, message: string) { setBusy(true); setError(''); try { await fn(); setSuccess(message); refresh(v => v + 1); } catch (reason) { setError(String(reason)); } finally { setBusy(false); } }
  return <Stack spacing={2}>
    <Typography variant="h4" component="h1">Alarms</Typography>
    <Typography>Alarms report abnormal conditions. They never control equipment. Acknowledgement does not clear the condition.</Typography>
    {error && <Alert severity="error">{error}</Alert>}{success && <Alert onClose={() => setSuccess('')} severity="success">{success}</Alert>}
    <Tabs value={tab} variant="scrollable" allowScrollButtonsMobile onChange={(_, value: number) => { setTab(value); setOffset(0); setState(''); }}><Tab label="Active alarms" /><Tab label="History" /><Tab label="Alarm rules" />{admin && <Tab label="Telegram" />}</Tabs>
    {loading && <Typography role="status">Loading alarms?</Typography>}
    {tab < 2 && <>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField select label="Severity filter" value={severity} onChange={e => { setSeverity(e.target.value); setOffset(0); }} sx={{ minWidth: 150 }}><MenuItem value="">All severities</MenuItem>{['INFO', 'WARNING', 'CRITICAL'].map(v => <MenuItem key={v} value={v}>{v}</MenuItem>)}</TextField>
        <TextField select label="State filter" value={state} onChange={e => { setState(e.target.value); setOffset(0); }} sx={{ minWidth: 180 }}><MenuItem value="">All states</MenuItem>{(tab === 0 ? ['ACTIVE', 'ACKNOWLEDGED'] : ['ACTIVE', 'ACKNOWLEDGED', 'CLEARED']).map(v => <MenuItem key={v} value={v}>{v}</MenuItem>)}</TextField>
        <TextField select label="Tag filter" value={tag} onChange={e => { setTag(e.target.value); setOffset(0); }} sx={{ minWidth: 170 }}><MenuItem value="">All Tags</MenuItem>{tags.map(t => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}</TextField>
      </Stack>
      {!loading && !events.length && <Typography>No alarms match these filters.</Typography>}
      {events.map(event => <Box key={event.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}><Chip label={event.severity} color={event.severity === 'CRITICAL' ? 'error' : event.severity === 'WARNING' ? 'warning' : 'info'} /><Chip label={event.state} /><Typography fontWeight={700}>{event.name}</Typography></Stack>
        <Typography>{event.tag_name}: trigger value {event.value_boolean === null ? event.value_numeric : event.value_boolean ? 'ON' : 'OFF'} {event.unit} ? Condition {event.condition}</Typography>
        <Typography variant="body2">Activated: {time(event.activated_at)} ? Acknowledged: {time(event.acknowledged_at)} ? Cleared: {time(event.cleared_at)}</Typography>
        {event.acknowledged_by_username && <Typography>Acknowledged by: {event.acknowledged_by_username}</Typography>}
        {event.clear_reason && <Typography variant="body2">{event.clear_reason}</Typography>}
        {event.state === 'ACTIVE' && <Can permission="acknowledge"><Button disabled={busy} onClick={() => void action(() => alarmsApi.acknowledge(event.id), 'Alarm acknowledged')}>Acknowledge</Button></Can>}
      </Box>)}
      <Stack direction="row"><Button disabled={!offset} onClick={() => setOffset(v => Math.max(0, v - 100))}>Previous</Button><Button disabled={events.length < 100} onClick={() => setOffset(v => v + 100)}>Next</Button></Stack>
    </>}
    {tab === 2 && <><Can permission="configure"><Button variant="contained" onClick={() => setEditor('new')} disabled={!tags.length}>New alarm rule</Button></Can>{!rules.length && <Typography>No alarm rules configured.</Typography>}{rules.map(rule => <Box key={rule.id} sx={{ border: 1, borderColor: 'divider', p: 2, borderRadius: 1 }}><Typography fontWeight={700}>{rule.name} ? {rule.severity} ? {rule.enabled ? 'Enabled' : 'Disabled'}</Typography><Typography>{tags.find(t => t.id === rule.tag_id)?.name ?? `Tag ${rule.tag_id}`} {rule.operator} {String(rule.value)} ? FOR {(rule.for_duration_ms ?? 0) / 1000}s</Typography><Can permission="configure"><Button onClick={() => setEditor(rule)}>Edit</Button></Can><Can permission="configure"><Button disabled={busy} onClick={() => void action(() => alarmsApi.edit(rule.id, { enabled: !rule.enabled }), 'Rule updated')}>{rule.enabled ? 'Disable' : 'Enable'}</Button></Can><Can permission="configure"><Button color="error" onClick={() => setDeleting(rule)}>Delete</Button></Can></Box>)}</>}
    {admin && tab === 3 && <>
      <Alert severity="info">Telegram requires TELEGRAM_ENABLED=true and TELEGRAM_BOT_TOKEN in the worker environment. Tokens are never entered in this page. Deliveries are attempted once; uncertain deliveries are not resent.</Alert>
      <TextField label="Telegram chat ID" value={chat} onChange={e => setChat(e.target.value)} helperText="Numeric chat ID or @channelusername. Start the bot or add it to the destination first." />
      <Stack direction="row" spacing={1}><Can permission="configure"><Button disabled={busy || !chat} onClick={() => void action(() => alarmsApi.configure(chat), 'Destination saved')}>Save destination</Button></Can><Can permission="configure"><Button disabled={busy} onClick={() => void action(() => alarmsApi.test(), 'Test queued. Check its delivery result below; queued does not mean sent.')}>Send test message</Button></Can><Button onClick={() => refresh(v => v + 1)}>Refresh results</Button></Stack>
      {!deliveries.length && <Typography>No notification deliveries.</Typography>}
      {deliveries.map(d => <Typography key={d.id}>#{d.id} {d.kind} ? {d.status} ? {time(d.created_at)} {d.error && `? ${d.error}`}</Typography>)}
    </>}
    {editor && <AlarmEditor rule={editor === 'new' ? undefined : editor} tags={tags} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); refresh(v => v + 1); setSuccess('Alarm rule saved'); }} />}
    <Dialog open={!!deleting} onClose={() => setDeleting(null)}><DialogTitle>Delete alarm rule?</DialogTitle><DialogContent>Rules with retained events cannot be deleted. Disable them instead.</DialogContent><DialogActions><Can permission="configure"><Button onClick={() => setDeleting(null)}>Cancel</Button></Can><Can permission="configure"><Button disabled={busy} color="error" onClick={() => { if (deleting) void action(() => alarmsApi.remove(deleting.id), 'Rule deleted').then(() => setDeleting(null)); }}>Delete</Button></Can></DialogActions></Dialog>
  </Stack>;
}

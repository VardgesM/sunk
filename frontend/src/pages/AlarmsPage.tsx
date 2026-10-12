import { useAuth, usePermission } from '../auth/context';
import Can from '../auth/Can';
import { useEffect, useState } from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { alarmsApi } from '../api/alarms';
import { tagsApi } from '../api/configuration';
import type { AlarmEvent, AlarmRule, Delivery } from '../types/alarms';
import type { Tag } from '../types/configuration';
import AlarmEditor from '../components/AlarmEditor';
import { useAlarmRefresh } from '../hooks/useAlarmRefresh';
import AlarmEventList from '../components/alarms/AlarmEventList';
import { alarmTime as time } from '../components/alarms/presentation';
import FilterPanel from '../components/data/FilterPanel';
import { shellLayout } from '../layout/tokens';

export default function AlarmsPage() {
  const admin = usePermission('configure');
  const cloud = useAuth().user?.application_mode === 'cloud';
  const live = useAlarmRefresh();
  const [tab, setTab] = useState(0); const [revision, refresh] = useState(0);
  const [events, setEvents] = useState<AlarmEvent[]>([]); const [rules, setRules] = useState<AlarmRule[]>([]);
  const [tags, setTags] = useState<Tag[]>([]); const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [chat, setChat] = useState(''); const [severity, setSeverity] = useState(''); const [state, setState] = useState(''); const [tag, setTag] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [eventsFailed, setEventsFailed] = useState(false);
  const [error, setError] = useState(''); const [success, setSuccess] = useState(''); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<AlarmRule | 'new' | null>(null); const [deleting, setDeleting] = useState<AlarmRule | null>(null);
  useEffect(() => { let active = true; void Promise.all([tagsApi.all(), admin ? alarmsApi.destination() : Promise.resolve({ chat_id: '' })]).then(([items, destination]) => { if (active) { setTags(items); setChat(destination.chat_id); } }).catch(reason => { if (active) setError(String(reason)); }); return () => { active = false; }; }, [admin]);
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ offset: String(offset) });
    if (tab === 0) query.set('active', 'true');
    if (severity) query.set('severity', severity); if (state) query.set('state', state); if (tag) query.set('tag_id', tag);
    void Promise.all([alarmsApi.events(query.toString()), alarmsApi.rules(), admin ? alarmsApi.deliveries() : Promise.resolve([])]).then(([rows, config, sent]) => { if (active) { setEvents(rows); setRules(config); setDeliveries(sent); setError(''); setEventsFailed(false); } }).catch(reason => { if (active) { setError(String(reason)); setEventsFailed(true); } }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [live, revision, tab, severity, state, tag, offset, admin]);
  async function action(fn: () => Promise<unknown>, message: string) { setBusy(true); setError(''); try { await fn(); setSuccess(message); refresh(v => v + 1); } catch (reason) { setError(String(reason)); } finally { setBusy(false); } }
  function changeFilter(setter: (value: string) => void, value: string) { setter(value); setOffset(0); setEvents([]); setLoading(true); }
  function resetFilters() { setSearch(''); if (severity || state || tag || offset) { setSeverity(''); setState(''); setTag(''); setOffset(0); setEvents([]); setLoading(true); } }
  const needle = search.trim().toLocaleLowerCase();
  const visibleEvents = events.filter(event => !needle || [event.name, event.tag_name, event.condition, event.clear_reason ?? ''].some(value => value.toLocaleLowerCase().includes(needle)));
  const activeFilters = [severity && `Severity: ${severity}`, state && `State: ${state}`, tag && `Tag: ${tags.find(item => item.id === Number(tag))?.name ?? tag}`, needle && `Search: ${search.trim()}`].filter(Boolean) as string[];
  const selectProps = { MenuProps: { PaperProps: { sx: { maxWidth: 'calc(100vw - 32px)', '& .MuiMenuItem-root': { whiteSpace: 'normal', overflowWrap: 'anywhere', minHeight: { xs: 44, sm: 44 } } } } } };
  return <Stack spacing={2} sx={{ minWidth: 0, overflowWrap: 'anywhere', '& .MuiButton-root': { minHeight: shellLayout.touchTarget }, '& .MuiAlert-message': { minWidth: 0, overflowWrap: 'anywhere' } }}>
    <Typography variant="h4" component="h1">Alarms</Typography>
    <Typography color="text.secondary">Review abnormal conditions and acknowledge open alarms. Alarms never control equipment.</Typography>
    {error && <Alert severity="error">{error}</Alert>}{success && <Alert onClose={() => setSuccess('')} severity="success">{success}</Alert>}
    <Tabs aria-label="Alarm sections" value={tab} variant="scrollable" allowScrollButtonsMobile onChange={(_, value: number) => { setTab(value); setOffset(0); setState(''); setEvents([]); setLoading(true); }} sx={{ minWidth: 0 }}><Tab label="Active alarms" /><Tab label="History" /><Tab label="Alarm rules" />{admin && <Tab label="Telegram" />}</Tabs>
    {loading && tab >= 2 && <Typography role="status">Loading alarms…</Typography>}
    {tab < 2 && <>
      <FilterPanel active={activeFilters} onReset={resetFilters}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, gap: 2, '& .MuiFormControl-root': { minWidth: 0 }, '& .MuiSelect-select': { whiteSpace: 'normal', overflowWrap: 'anywhere' } }}>
          <TextField label="Search alarms" value={search} onChange={e => setSearch(e.target.value)} helperText="Search names, Tags, conditions and clear reasons on this page." />
          <TextField select label="Severity filter" value={severity} onChange={e => changeFilter(setSeverity, e.target.value)} slotProps={{ select: selectProps }}><MenuItem value="">All severities</MenuItem>{['INFO', 'WARNING', 'CRITICAL'].map(v => <MenuItem key={v} value={v}>{v}</MenuItem>)}</TextField>
          <TextField select label="State filter" value={state} onChange={e => changeFilter(setState, e.target.value)} slotProps={{ select: selectProps }}><MenuItem value="">All states</MenuItem>{(tab === 0 ? ['ACTIVE', 'ACKNOWLEDGED'] : ['ACTIVE', 'ACKNOWLEDGED', 'CLEARED']).map(v => <MenuItem key={v} value={v}>{v}</MenuItem>)}</TextField>
          <TextField select label="Tag filter" value={tag} onChange={e => changeFilter(setTag, e.target.value)} slotProps={{ select: selectProps }}><MenuItem value="">All Tags</MenuItem>{tags.map(t => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}</TextField>
        </Box>
      </FilterPanel>
      <AlarmEventList events={visibleEvents} history={tab === 1} loading={loading} failed={eventsFailed} filtered={!!activeFilters.length || offset > 0} busy={busy}
        onAcknowledge={event => action(() => alarmsApi.acknowledge(event.id), cloud ? 'Acknowledgement queued for Edge; waiting for confirmation' : 'Alarm acknowledged')} />
      <Stack direction="row" justifyContent="space-between" alignItems="center" component="nav" aria-label="Alarm pages">
        <Button disabled={!offset || loading} onClick={() => { setOffset(v => Math.max(0, v - 100)); setEvents([]); setLoading(true); }}>Previous</Button>
        <Typography variant="body2" color="text.secondary">Page {offset / 100 + 1}</Typography>
        <Button disabled={events.length < 100 || loading} onClick={() => { setOffset(v => v + 100); setEvents([]); setLoading(true); }}>Next</Button>
      </Stack>
    </>}
    {tab === 2 && <><Can permission="configure"><Button variant="contained" onClick={() => setEditor('new')} disabled={!tags.length}>New alarm rule</Button></Can>{!rules.length && <Typography>No alarm rules configured.</Typography>}{rules.map(rule => <Box key={rule.id} sx={{ border: 1, borderColor: 'divider', p: 2, borderRadius: 1 }}><Typography fontWeight={700}>{rule.name} | {rule.severity} | {rule.enabled ? 'Enabled' : 'Disabled'}</Typography><Typography>{tags.find(t => t.id === rule.tag_id)?.name ?? `Tag ${rule.tag_id}`} {rule.operator} {String(rule.value)} | FOR {(rule.for_duration_ms ?? 0) / 1000}s</Typography><Can permission="configure"><Button onClick={() => setEditor(rule)}>Edit</Button></Can><Can permission="configure"><Button disabled={busy} onClick={() => void action(() => alarmsApi.edit(rule.id, { enabled: !rule.enabled }), 'Rule updated')}>{rule.enabled ? 'Disable' : 'Enable'}</Button></Can><Can permission="configure"><Button color="error" onClick={() => setDeleting(rule)}>Delete</Button></Can></Box>)}</>}
    {admin && tab === 3 && <>
      <Alert severity="info">Telegram requires TELEGRAM_ENABLED=true and TELEGRAM_BOT_TOKEN in the worker environment. Tokens are never entered in this page. Deliveries are attempted once; uncertain deliveries are not resent.</Alert>
      <TextField label="Telegram chat ID" value={chat} onChange={e => setChat(e.target.value)} helperText="Numeric chat ID or @channelusername. Start the bot or add it to the destination first." />
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}><Can permission="configure"><Button disabled={busy || !chat} onClick={() => void action(() => alarmsApi.configure(chat), 'Destination saved')}>Save destination</Button></Can><Can permission="configure"><Button disabled={busy} onClick={() => void action(() => alarmsApi.test(), 'Test queued. Check its delivery result below; queued does not mean sent.')}>Send test message</Button></Can><Button onClick={() => refresh(v => v + 1)}>Refresh results</Button></Stack>
      {!deliveries.length && <Typography>No notification deliveries.</Typography>}
      {deliveries.map(d => <Typography key={d.id}>#{d.id} {d.kind} | {d.status} | {time(d.created_at)} {d.error && `| ${d.error}`}</Typography>)}
    </>}
    {editor && <AlarmEditor rule={editor === 'new' ? undefined : editor} tags={tags} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); refresh(v => v + 1); setSuccess('Alarm rule saved'); }} />}
    <Dialog open={!!deleting} onClose={() => setDeleting(null)}><DialogTitle>Delete alarm rule?</DialogTitle><DialogContent>Rules with retained events cannot be deleted. Disable them instead.</DialogContent><DialogActions><Can permission="configure"><Button onClick={() => setDeleting(null)}>Cancel</Button></Can><Can permission="configure"><Button disabled={busy} color="error" onClick={() => { if (deleting) void action(() => alarmsApi.remove(deleting.id), 'Rule deleted').then(() => setDeleting(null)); }}>Delete</Button></Can></DialogActions></Dialog>
  </Stack>;
}

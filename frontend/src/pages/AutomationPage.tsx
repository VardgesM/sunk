import Can from '../auth/Can';
import { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import { automationApi } from '../api/automation';
import { tagsApi } from '../api/configuration';
import RuleEditor from '../components/RuleEditor';
import type { Tag } from '../types/configuration';
import type { Rule, RuleInput } from '../types/automation';
import RuleCard from '../components/automation/RuleCard';
import RuleHistory from '../components/automation/RuleHistory';
import FilterPanel from '../components/data/FilterPanel';
import { shellLayout } from '../layout/tokens';
const message = (e: unknown) => e instanceof Error ? e.message : 'Request failed';
const editable = ({ name, description, enabled, priority, condition_mode, for_duration_ms, cooldown_ms, conditions, actions }: Rule): RuleInput => ({ name, description, enabled, priority, condition_mode, for_duration_ms, cooldown_ms, conditions, actions });
export default function AutomationPage() {
  const [rows, setRows] = useState<Rule[]>([]); const [tags, setTags] = useState<Tag[]>([]);
  const [error, setError] = useState(''); const [success, setSuccess] = useState(''); const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<Rule | 'new' | null>(null); const [history, setHistory] = useState<Rule | null>(null); const [deleting, setDeleting] = useState<Rule | null>(null); const [busy, setBusy] = useState(false);
  const [tagError, setTagError] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [search, setSearch] = useState(''), [enabled, setEnabled] = useState(''), [status, setStatus] = useState('');
  const tagMap = useMemo(() => new Map(tags.map(tag => [tag.id, tag])), [tags]);
  const statuses = [...new Set(rows.map(rule => rule.runtime?.state ?? 'Not reported').concat(status ? [status] : []))].sort();
  const filtered = rows.filter(rule => rule.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
    && (!enabled || rule.enabled === (enabled === 'enabled')) && (!status || (rule.runtime?.state ?? 'Not reported') === status));
  const reload = async () => setRows(await automationApi.list());
  useEffect(() => { const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => { try { const rules = await automationApi.list(controller.signal); if (!controller.signal.aborted) { setRows(rules); setError(''); } } catch (e) { if (!controller.signal.aborted) setError(message(e)); } finally { if (!controller.signal.aborted) { setLoading(false); timer = setTimeout(() => { void refresh(); }, 3000); } } };
    void refresh(); void tagsApi.all(controller.signal).then(values => { if (!controller.signal.aborted) setTags(values); }).catch(e => { if (!controller.signal.aborted) setTagError(message(e)); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  const toggle = async (rule: Rule) => { setBusy(true); try { await automationApi.update(rule.id, { enabled: !rule.enabled }); await reload(); setSuccess('Rule updated'); } catch (e) { setError(message(e)); } finally { setBusy(false); } };
  return <Stack spacing={2} sx={{ minWidth: 0, '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
    <Stack direction="row" flexWrap="wrap" alignItems="center" gap={1}><Typography variant="h4" component="h1" sx={{ flex: 1 }}>Automation</Typography>
      <Can permission="configure"><Button variant="contained" onClick={() => setEditor('new')}>Create rule</Button></Can></Stack>
    <Typography color="text.secondary">Rules request equipment changes when their conditions match. Only fresh GOOD readings are used; commands still require read-back verification.</Typography>
    {error && <Alert severity="error">{error}</Alert>}{success && <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>}
    {tagError && <Alert severity="warning">Tag names and units are unavailable: {tagError}</Alert>}
    {!!rows.length && <FilterPanel active={[...(search ? [`Name: ${search}`] : []), ...(enabled ? [enabled === 'enabled' ? 'Enabled only' : 'Disabled only'] : []), ...(status ? [`Status: ${status}`] : [])]} onReset={() => { setSearch(''); setEnabled(''); setStatus(''); }}>
      <Stack direction={{ xs: 'column', md: 'row' }} gap={2}>
        <TextField fullWidth label="Search rules" value={search} onChange={event => setSearch(event.target.value)} />
        <TextField fullWidth select label="Enabled filter" value={enabled} onChange={event => setEnabled(event.target.value)}><MenuItem value="">All rules</MenuItem><MenuItem value="enabled">Enabled</MenuItem><MenuItem value="disabled">Disabled</MenuItem></TextField>
        <TextField fullWidth select label="Status filter" value={status} onChange={event => setStatus(event.target.value)} sx={{ '& .MuiSelect-select': { whiteSpace: 'normal', overflowWrap: 'anywhere' } }}><MenuItem value="">All statuses</MenuItem>{statuses.map(state => <MenuItem key={state} value={state}>{state}</MenuItem>)}</TextField>
      </Stack>
    </FilterPanel>}
    {loading && <Typography role="status">Loading rules...</Typography>}
    {!loading && !error && !rows.length && <Paper variant="outlined" sx={{ p: 3 }}><Typography variant="h6">No automation rules configured</Typography><Typography color="text.secondary">Rules describe when an equipment action should be requested.</Typography><Can permission="configure"><Typography sx={{ mt: 1 }}>Use Create rule to configure conditions and actions.</Typography></Can></Paper>}
    {!!rows.length && <Typography variant="caption" color="text.secondary">{filtered.length} of {rows.length} loaded rules. Status refreshes every 3 seconds.</Typography>}
    {!!rows.length && !filtered.length && <Typography>No rules match these filters.</Typography>}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2, alignItems: 'start' }}>
      {filtered.map(rule => <RuleCard key={rule.id} rule={rule} tags={tagMap} busy={busy} onEdit={() => setEditor(rule)} onHistory={() => setHistory(rule)} onToggle={() => void toggle(rule)} onDelete={() => { setDeleteError(''); setDeleting(rule); }} />)}
    </Box>
    {editor && <RuleEditor tags={tags} initial={editor === 'new' ? undefined : editable(editor)} onClose={() => setEditor(null)} onSave={async value => { if (editor === 'new') await automationApi.create(value); else await automationApi.update(editor.id, value); setEditor(null); setSuccess('Rule saved'); await reload(); }} />}
    {history && <RuleHistory rule={history} tags={tagMap} onClose={() => setHistory(null)} />}
    {deleting && <Dialog open fullWidth maxWidth="sm" onClose={() => setDeleting(null)} sx={{ '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}><DialogTitle sx={{ overflowWrap: 'anywhere' }}>Delete {deleting.name}?</DialogTitle><DialogContent>Rules with execution history cannot be deleted; disable them instead.{deleteError && <Alert severity="error" sx={{ mt: 2 }}>{deleteError}</Alert>}</DialogContent><DialogActions><Can permission="configure"><Button onClick={() => setDeleting(null)}>Cancel</Button></Can><Can permission="configure"><Button disabled={busy} color="error" onClick={() => { setBusy(true); void automationApi.remove(deleting.id).then(async () => { setDeleting(null); setSuccess('Rule deleted'); await reload(); }).catch(e => setDeleteError(message(e))).finally(() => setBusy(false)); }}>Confirm delete</Button></Can></DialogActions></Dialog>}
  </Stack>;
}

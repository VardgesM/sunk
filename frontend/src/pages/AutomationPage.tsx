import Can from '../auth/Can';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import { automationApi } from '../api/automation';
import { tagsApi } from '../api/configuration';
import RuleEditor from '../components/RuleEditor';
import type { Tag } from '../types/configuration';
import type { Execution, Rule, RuleInput } from '../types/automation';
const message = (e: unknown) => e instanceof Error ? e.message : 'Request failed';
const editable = ({ name, description, enabled, priority, condition_mode, for_duration_ms, cooldown_ms, conditions, actions }: Rule): RuleInput => ({ name, description, enabled, priority, condition_mode, for_duration_ms, cooldown_ms, conditions, actions });
function History({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const [rows, setRows] = useState<Execution[]>([]); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  useEffect(() => { const c = new AbortController(); void automationApi.executions(rule.id, c.signal).then(setRows).catch(e => { if (!c.signal.aborted) setError(message(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => c.abort(); }, [rule.id]);
  return <Dialog open fullWidth maxWidth="md" onClose={onClose}><DialogTitle>{rule.name}: executions</DialogTitle><DialogContent><Stack spacing={2}>
    {loading && <Typography role="status">Loading executions...</Typography>}{error && <Alert severity="error">{error}</Alert>}{!loading && !rows.length && <Typography>No executions yet.</Typography>}
    {rows.map(row => <Stack key={row.id} spacing={1} sx={{ borderBottom: '1px solid', borderColor: 'divider', pb: 2 }}><Typography>{new Date(row.triggered_at).toLocaleString()} ? {row.result}</Typography>
      {row.snapshot.map((c, i) => <Typography key={i}>Tag {c.tag_id}: {String(c.value)} {c.operator} {String(c.comparison)} ({c.quality})</Typography>)}
      <Typography>Commands: {row.command_ids.map(id => <Link key={id} to={`/commands?command_id=${id}`} style={{ marginRight: 8 }}>#{id}</Link>)}</Typography>{row.error && <Alert severity="error">{row.error}</Alert>}
    </Stack>)}
  </Stack></DialogContent><DialogActions><Button onClick={onClose}>Close</Button></DialogActions></Dialog>;
}
export default function AutomationPage() {
  const [rows, setRows] = useState<Rule[]>([]); const [tags, setTags] = useState<Tag[]>([]);
  const [error, setError] = useState(''); const [success, setSuccess] = useState(''); const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<Rule | 'new' | null>(null); const [history, setHistory] = useState<Rule | null>(null); const [deleting, setDeleting] = useState<Rule | null>(null); const [busy, setBusy] = useState(false);
  const reload = async () => setRows(await automationApi.list());
  useEffect(() => { const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => { try { const rules = await automationApi.list(controller.signal); if (!controller.signal.aborted) { setRows(rules); setError(''); } } catch (e) { if (!controller.signal.aborted) setError(message(e)); } finally { if (!controller.signal.aborted) { setLoading(false); timer = setTimeout(() => { void refresh(); }, 3000); } } };
    void refresh(); void tagsApi.all(controller.signal).then(setTags).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  const toggle = async (rule: Rule) => { setBusy(true); try { await automationApi.update(rule.id, { enabled: !rule.enabled }); await reload(); setSuccess('Rule updated'); } catch (e) { setError(message(e)); } finally { setBusy(false); } };
  return <Stack spacing={2}><Typography variant="h4" component="h1">Automation</Typography>
    <Typography>Rules evaluate fresh GOOD telemetry and request verified commands. Highest priority wins conflicts; no direct device writes.</Typography>
    <Can permission="configure"><Button variant="contained" onClick={() => setEditor('new')}>Create rule</Button></Can>
    {error && <Alert severity="error">{error}</Alert>}{success && <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>}
    {loading ? <Typography role="status">Loading rules...</Typography> : !rows.length && <Typography>No automation rules configured.</Typography>}
    {rows.map(rule => <Stack key={rule.id} spacing={1} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, p: 2 }}>
      <Typography variant="h6">{rule.name}</Typography><Typography>{rule.enabled ? 'Enabled' : 'Disabled'} ? Priority {rule.priority} ? {rule.condition_mode}</Typography>
      <Stack direction="row" spacing={1}><Chip label={rule.runtime?.state || 'IDLE'} /><Chip label={rule.runtime?.last_result || 'No executions'} /></Stack>
      <Typography>Last triggered: {rule.runtime?.last_triggered_at ? new Date(rule.runtime.last_triggered_at).toLocaleString() : 'Never'}</Typography>
      {rule.runtime?.error && <Alert severity="warning">{rule.runtime.error}</Alert>}
      <Stack direction="row" flexWrap="wrap"><Can permission="configure"><Button disabled={busy} onClick={() => { void toggle(rule); }}>{rule.enabled ? 'Disable' : 'Enable'}</Button></Can><Can permission="configure"><Button onClick={() => setEditor(rule)}>Edit</Button></Can><Button onClick={() => setHistory(rule)}>Executions</Button><Can permission="configure"><Button color="error" onClick={() => setDeleting(rule)}>Delete</Button></Can></Stack>
    </Stack>)}
    {editor && <RuleEditor tags={tags} initial={editor === 'new' ? undefined : editable(editor)} onClose={() => setEditor(null)} onSave={async value => { if (editor === 'new') await automationApi.create(value); else await automationApi.update(editor.id, value); setEditor(null); setSuccess('Rule saved'); await reload(); }} />}
    {history && <History rule={history} onClose={() => setHistory(null)} />}
    {deleting && <Dialog open onClose={() => setDeleting(null)}><DialogTitle>Delete {deleting.name}?</DialogTitle><DialogContent>Rules with execution history cannot be deleted; disable them instead.</DialogContent><DialogActions><Can permission="configure"><Button onClick={() => setDeleting(null)}>Cancel</Button></Can><Can permission="configure"><Button disabled={busy} color="error" onClick={() => { setBusy(true); void automationApi.remove(deleting.id).then(async () => { setDeleting(null); setSuccess('Rule deleted'); await reload(); }).catch(e => setError(message(e))).finally(() => setBusy(false)); }}>Confirm delete</Button></Can></DialogActions></Dialog>}
  </Stack>;
}

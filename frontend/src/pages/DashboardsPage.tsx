import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Checkbox, MenuItem, Paper, Snackbar, Stack, TextField, Typography } from '@mui/material';
import { Responsive, useContainerWidth, type ResponsiveLayouts } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { dashboardsApi } from '../api/dashboards';
import { tagsApi } from '../api/configuration';
import type { Tag } from '../types/configuration';
import type { Breakpoint, Dashboard, DashboardDetail, DashboardInput, Widget } from '../types/dashboards';
import { LiveConnectionStatus } from '../components/LiveValues';
import WidgetEditor from '../components/WidgetEditor';
import DashboardWidget from '../widgets/DashboardWidget';

function DashboardForm({ initial, onSave, onClose }: { initial?: Dashboard; onSave: (value: DashboardInput) => Promise<void>; onClose: () => void }) {
  const [form, setForm] = useState<DashboardInput>(initial ?? { name: '', slug: '', description: null, is_default: false });
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setError('');
    try { await onSave({ name: form.name, slug: form.slug, description: form.description, is_default: form.is_default }); }
    catch (e) { setError(e instanceof Error ? e.message : 'Dashboard could not be saved'); }
    finally { setBusy(false); }
  }
  return <Dialog open fullWidth maxWidth="sm" onClose={() => { if (!busy) onClose(); }}><DialogTitle>{initial ? 'Edit dashboard' : 'Create dashboard'}</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
    {error && <Alert severity="error">{error}</Alert>}
    <TextField label="Dashboard name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
    <TextField label="Slug" value={form.slug} onChange={e => setForm({ ...form, slug: e.target.value })} helperText="Lowercase letters, numbers and hyphens. Must be unique." required />
    <TextField label="Description" multiline value={form.description ?? ''} onChange={e => setForm({ ...form, description: e.target.value || null })} />
    <FormControlLabel label="Default dashboard" control={<Checkbox checked={form.is_default} onChange={e => setForm({ ...form, is_default: e.target.checked })} />} />
  </Stack></DialogContent><DialogActions><Button disabled={busy} onClick={onClose}>Cancel</Button><Button disabled={busy || !form.name.trim() || !form.slug.trim()} onClick={() => void save()}>Save dashboard</Button></DialogActions></Dialog>;
}

function Canvas({ dashboard, tags, reload, report }: { dashboard: DashboardDetail; tags: Tag[]; reload: () => Promise<void>; report: (message: string) => void }) {
  const [editing, setEditing] = useState(false), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<Widget | 'new'>(), [remove, setRemove] = useState<Widget>();
  const [error, setError] = useState('');
  const { width, containerRef, mounted } = useContainerWidth();
  const layouts = useMemo<ResponsiveLayouts<Breakpoint>>(() => Object.fromEntries(['lg','md','sm'].map(b => [b, dashboard.widgets.map(w => ({ ...w.layouts.find(l => l.breakpoint === b)!, i: String(w.id), minH: 2, maxH: 40 }))])), [dashboard]);
  const pending = useRef(layouts);
  const tagMap = useMemo(() => new Map(tags.map(t => [t.id,t])), [tags]);
  async function save() {
    setBusy(true); setError('');
    try {
      await dashboardsApi.layout(dashboard.id, dashboard.revision, (['lg','md','sm'] as const).flatMap(b => (pending.current[b] ?? layouts[b] ?? []).map(l => ({ widget_id: Number(l.i), breakpoint: b, x: l.x, y: l.y, w: l.w, h: l.h }))));
      await reload(); setDirty(false); report('Layout saved');
    } catch (e) { setError(e instanceof Error ? e.message : 'Layout could not be saved'); }
    finally { setBusy(false); }
  }
  return <Stack spacing={2}>
    <Stack direction="row" flexWrap="wrap" gap={1}>
      <Button onClick={() => setEditing(v => !v)} disabled={dirty || busy}>{editing ? 'Finish editing' : 'Edit dashboard layout'}</Button>
      {editing && <><Button onClick={() => setEditor('new')} disabled={dirty || busy}>Add widget</Button><Button disabled={!dirty || busy} onClick={() => void save()}>Save layout</Button><Button disabled={!dirty || busy} onClick={() => void reload().then(() => setDirty(false)).catch(e => setError(String(e)))}>Discard layout changes</Button></>}
    </Stack>
    {editing && <Alert severity="info">Drag the widget title to move; use its bottom-right handle to resize. Each screen width has its own layout. Save layout before editing widget settings. Settings and widget removal are saved immediately.</Alert>}
    {dirty && <Typography role="status">Unsaved layout changes</Typography>}
    {error && <Alert severity="error">{error}</Alert>}
    {!dashboard.widgets.length && <Alert severity="info">No widgets yet. Enter edit mode and add a widget.</Alert>}
    <Box ref={containerRef} sx={{ width: '100%', minWidth: 0 }}>
      {mounted && <Responsive<Breakpoint> width={width} breakpoints={{ lg: 1000, md: 600, sm: 0 }} cols={{ lg: 12, md: 6, sm: 1 }} layouts={layouts} rowHeight={40} margin={[12,12]} containerPadding={[0,0]}
        dragConfig={{ enabled: editing && !busy, handle: '.widget-handle', cancel: 'button' }} resizeConfig={{ enabled: editing && !busy }}
        onLayoutChange={(_layout, all) => { pending.current = all; }} onDragStop={() => setDirty(true)} onResizeStop={() => setDirty(true)}>
        {dashboard.widgets.map(widget => <Paper key={String(widget.id)} variant="outlined" sx={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          <Stack className="widget-handle" direction="row" alignItems="center" sx={{ p: 1, bgcolor: 'action.hover', cursor: editing ? 'move' : 'default', touchAction: editing ? 'none' : 'auto' }}>
            <Typography component="h2" fontWeight={700} sx={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{widget.title}</Typography>
            {editing && <><Button size="small" disabled={dirty || busy} onClick={() => setEditor(widget)} aria-label={`Edit ${widget.title}`}>Edit</Button><Button size="small" disabled={dirty || busy} onClick={() => setRemove(widget)} aria-label={`Remove ${widget.title}`}>Remove</Button></>}
          </Stack>
          <Box sx={{ p: 2, minHeight: 0, overflow: 'auto', flex: 1 }}><DashboardWidget widget={widget} tags={tagMap} editing={editing} /></Box>
        </Paper>)}
      </Responsive>}
    </Box>
    {editor && <WidgetEditor initial={editor === 'new' ? undefined : editor} tags={tags} nextY={Math.max(0, ...dashboard.widgets.flatMap(w => w.layouts.map(l => l.y + l.h)))} onClose={() => setEditor(undefined)} onSave={async value => {
      if (editor === 'new') await dashboardsApi.addWidget(dashboard.id, value); else await dashboardsApi.editWidget(editor.id, value);
      setEditor(undefined); await reload(); report('Widget saved');
    }} />}
    <Dialog open={!!remove} onClose={() => setRemove(undefined)}><DialogTitle>Remove widget?</DialogTitle><DialogContent>This removes only the widget. Tags and their data remain unchanged.</DialogContent><DialogActions><Button disabled={busy} onClick={() => setRemove(undefined)}>Cancel</Button><Button disabled={busy} color="error" onClick={() => { if (!remove) return; setBusy(true); void dashboardsApi.removeWidget(remove.id).then(reload).then(() => report('Widget removed')).catch(e => setError(String(e))).finally(() => { setBusy(false); setRemove(undefined); }); }}>Remove widget</Button></DialogActions></Dialog>
  </Stack>;
}

export default function DashboardsPage() {
  const [rows, setRows] = useState<Dashboard[]>(), [tags, setTags] = useState<Tag[]>();
  const [selected, setSelected] = useState<number>(), [dashboard, setDashboard] = useState<DashboardDetail>();
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [form, setForm] = useState<Dashboard | 'new'>(), [deleting, setDeleting] = useState(false), [busy, setBusy] = useState(false);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([dashboardsApi.all(controller.signal), tagsApi.all(controller.signal)]).then(([list, metadata]) => {
      if (!controller.signal.aborted) { setRows(list); setTags(metadata); setSelected(id => id !== undefined && list.some(r => r.id === id) ? id : (list.find(r => r.is_default) ?? list[0])?.id); setError(''); }
    }).catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Dashboard unavailable'); });
    return () => controller.abort();
  }, [generation]);
  useEffect(() => {
    if (selected === undefined) return;
    const controller = new AbortController();
    dashboardsApi.get(selected, controller.signal).then(row => { if (!controller.signal.aborted) setDashboard(row); }).catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Dashboard unavailable'); });
    return () => controller.abort();
  }, [selected, generation]);
  async function reload() {
    if (selected !== undefined) { const row = await dashboardsApi.get(selected); setDashboard(row); }
    setRows(await dashboardsApi.all()); setTags(await tagsApi.all());
  }
  return <Stack spacing={2}>
    <Stack direction="row" alignItems="center" flexWrap="wrap" gap={2}><Typography variant="h4" component="h1">Dashboards</Typography><LiveConnectionStatus /><Button onClick={() => setForm('new')}>Create dashboard</Button></Stack>
    {error && <Alert severity="error" action={<Button onClick={() => setGeneration(v => v + 1)}>Retry</Button>}>{error}</Alert>}
    {!rows && !error && <Typography role="status">Loading dashboards...</Typography>}
    {rows?.length === 0 && <Alert severity="info">No dashboards yet. Create your first dashboard.</Alert>}
    {!!rows?.length && <Stack direction="row" flexWrap="wrap" gap={1}>
      <TextField select label="Dashboard" value={selected ?? ''} onChange={e => { setDashboard(undefined); setSelected(Number(e.target.value)); }} sx={{ minWidth: 180 }}>
        {rows.map(row => <MenuItem key={row.id} value={row.id}>{row.name}{row.is_default ? ' (default)' : ''}</MenuItem>)}
      </TextField>
      {dashboard?.id === selected && <><Button onClick={() => setForm(dashboard)}>Rename / settings</Button><Button color="error" onClick={() => setDeleting(true)}>Delete dashboard</Button><Button onClick={() => void reload().catch(e => setError(String(e)))}>Reload dashboard</Button></>}
    </Stack>}
    {dashboard && dashboard.id === selected && tags && <><Typography>{dashboard.description}</Typography><Canvas key={`${dashboard.id}:${generation}`} dashboard={dashboard} tags={tags} reload={reload} report={setMessage} /></>}
    {form && <DashboardForm initial={form === 'new' ? undefined : form} onClose={() => setForm(undefined)} onSave={async value => {
      const result = form === 'new' ? await dashboardsApi.create(value) : await dashboardsApi.edit(form.id,value);
      setForm(undefined); setSelected(result.id); setDashboard(result); setGeneration(v => v + 1); setMessage('Dashboard saved');
    }} />}
    <Dialog open={deleting} onClose={() => { if (!busy) setDeleting(false); }}><DialogTitle>Delete dashboard?</DialogTitle><DialogContent>All widgets in this dashboard will be removed. Tags, commands and history remain unchanged.</DialogContent><DialogActions><Button disabled={busy} onClick={() => setDeleting(false)}>Cancel</Button><Button disabled={busy} color="error" onClick={() => { if (!selected) return; setBusy(true); void dashboardsApi.remove(selected).then(() => { setDashboard(undefined); setSelected(undefined); setGeneration(v => v + 1); setMessage('Dashboard deleted'); }).catch(e => setError(String(e))).finally(() => { setBusy(false); setDeleting(false); }); }}>Delete permanently</Button></DialogActions></Dialog>
    <Snackbar open={!!message} autoHideDuration={4000} message={message} onClose={() => setMessage('')} />
  </Stack>;
}

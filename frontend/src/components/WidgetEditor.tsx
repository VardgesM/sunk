import { useState } from 'react';
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { Widget, WidgetConfig, WidgetInput, WidgetLayout, WidgetType } from '../types/dashboards';

const labels: Record<WidgetType, string> = { value: 'Value', gauge: 'Gauge', chart: 'Line Chart', boolean: 'Boolean Status', switch: 'Switch / Control', setpoint: 'Numeric Setpoint', alarms: 'Alarm List', text: 'Text / Label' };
export default function WidgetEditor({ initial, tags, nextY, onSave, onClose }: {
  initial?: Widget; tags: Tag[]; nextY: number; onSave: (value: WidgetInput) => Promise<void>; onClose: () => void;
}) {
  const [type, setType] = useState<WidgetType>(initial?.type ?? 'value');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [ids, setIds] = useState<number[]>(initial?.tag_ids ?? []);
  const [config, setConfig] = useState<WidgetConfig>(initial?.configuration ?? {});
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [layouts, setLayouts] = useState<WidgetLayout[]>(initial?.layouts ?? [
    { breakpoint: 'lg', x: 0, y: nextY, w: 4, h: 6 }, { breakpoint: 'md', x: 0, y: nextY, w: 3, h: 6 }, { breakpoint: 'sm', x: 0, y: nextY, w: 1, h: 6 },
  ]);
  const candidates = tags.filter(tag => {
    if (type === 'switch') return tag.enabled && tag.writable && tag.data_type === 'bool' && tag.register_type === 'coil';
    if (type === 'setpoint') return tag.enabled && tag.writable && tag.data_type !== 'bool' && tag.register_type === 'holding_register';
    if (type === 'boolean') return tag.data_type === 'bool';
    if (type === 'chart' || type === 'gauge') return tag.data_type !== 'bool';
    return true;
  });
  function number(key: keyof WidgetConfig, label: string, fallback: number | null, helperText?: string) {
    return <TextField label={label} type="number" value={config[key] ?? fallback ?? ''} helperText={helperText} onChange={e => setConfig({ ...config, [key]: e.target.value === '' ? null : Number(e.target.value) })} />;
  }
  function toggle(key: keyof WidgetConfig, label: string, fallback = true) {
    return <FormControlLabel control={<Checkbox checked={Boolean(config[key] ?? fallback)} onChange={e => setConfig({ ...config, [key]: e.target.checked })} />} label={label} />;
  }
  async function save() {
    setError(''); setBusy(true);
    try { await onSave({ type, title, tag_ids: ['text', 'alarms'].includes(type) ? [] : ids, configuration: config, layouts }); }
    catch (e) { setError(e instanceof Error ? e.message : 'Widget could not be saved'); }
    finally { setBusy(false); }
  }
  return <Dialog open fullWidth maxWidth="sm" onClose={() => { if (!busy) onClose(); }}>
    <DialogTitle>{initial ? 'Edit widget' : 'Add widget'}</DialogTitle>
    <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField select label="Widget type" value={type} onChange={e => { const next = e.target.value as WidgetType; setType(next); setIds([]); setConfig({}); if (!initial) setLayouts(rows => rows.map(l => ({ ...l, h: ['chart', 'switch', 'setpoint'].includes(next) ? 12 : 6 }))); }}>
        {Object.entries(labels).map(([key,label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
      </TextField>
      <TextField label="Widget title" value={title} onChange={e => setTitle(e.target.value)} required />
      {!['text','alarms'].includes(type) && <TextField select label={type === 'chart' ? 'Tags' : 'Tag'} value={type === 'chart' ? ids : ids[0] ?? ''}
        slotProps={{ select: { multiple: type === 'chart' } }} onChange={e => { const value = e.target.value as unknown as number | number[]; setIds(Array.isArray(value) ? value.map(Number) : [Number(value)]); }}
        helperText={type === 'chart' ? 'Up to 8 numeric Tags with the same unit.' : 'Only compatible Tags are listed; the server validates configuration again.'}>
        {candidates.map(tag => <MenuItem key={tag.id} value={tag.id}>{tag.name} ({tag.key}) {tag.unit}</MenuItem>)}
      </TextField>}
      {type === 'value' && <>{number('decimals','Decimals',2)}{toggle('show_unit','Show unit')}{toggle('show_quality','Show quality')}{toggle('show_last_update','Show last update')}</>}
      {type === 'gauge' && <>{number('min','Gauge minimum',0)}{number('max','Gauge maximum',100)}{number('decimals','Decimals',2)}
        <TextField label="Display unit override" value={config.unit ?? ''} onChange={e => setConfig({ ...config, unit: e.target.value || null })} helperText="Label only; does not convert the value." />
        {number('warning_threshold','Warning threshold',null)}{number('critical_threshold','Critical threshold',null)}<Typography>Thresholds affect only this gauge. They do not create alarms.</Typography></>}
      {type === 'chart' && <>{number('range_hours','Default range (hours)',1)}{number('refresh_seconds','Refresh interval (seconds)',0,'0 = manual; automatic refresh must be at least 30 seconds.')}{toggle('legend','Show legend')}</>}
      {type === 'boolean' && <><TextField label="ON label" value={config.on_label ?? 'ON'} onChange={e => setConfig({ ...config, on_label: e.target.value })} /><TextField label="OFF label" value={config.off_label ?? 'OFF'} onChange={e => setConfig({ ...config, off_label: e.target.value })} /></>}
      {['switch','setpoint'].includes(type) && <>{toggle('confirmation_required','Confirm simulated commands too')}<Alert severity="info">Physical writes always require confirmation and enabled worker writes. Commands are verified by read-back.</Alert></>}
      {type === 'alarms' && <>{toggle('active_only','Active alarms only')}{number('maximum_rows','Maximum rows',10)}<TextField select label="Severities" value={config.severities ?? ['INFO','WARNING','CRITICAL']} slotProps={{ select: { multiple: true } }} onChange={e => setConfig({ ...config, severities: e.target.value as unknown as WidgetConfig['severities'] })}>{['INFO','WARNING','CRITICAL'].map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField></>}
      {type === 'text' && <TextField label="Text" multiline minRows={3} value={config.text ?? ''} onChange={e => setConfig({ ...config, text: e.target.value })} helperText="Plain text only. HTML and scripts are not executed." />}
      <Typography variant="subtitle2">Layout (also adjustable by dragging and resizing)</Typography>
      {layouts.map((layout, index) => <Stack key={layout.breakpoint} spacing={1}><Typography>{layout.breakpoint === 'lg' ? 'Desktop' : layout.breakpoint === 'md' ? 'Tablet' : 'Phone'}</Typography>
        <Stack direction="row" spacing={1}>{(['x','y','w','h'] as const).map(key => <TextField key={key} label={`${layout.breakpoint} ${key}`} type="number" size="small" value={layout[key]} disabled={layout.breakpoint === 'sm' && ['x','w'].includes(key)} onChange={e => setLayouts(rows => rows.map((l,i) => i === index ? { ...l, [key]: Number(e.target.value) } : l))} />)}</Stack>
      </Stack>)}
    </Stack></DialogContent>
    <DialogActions><Button disabled={busy} onClick={onClose}>Cancel</Button><Button disabled={busy || !title.trim()} onClick={() => void save()} variant="contained">Save widget</Button></DialogActions>
  </Dialog>;
}

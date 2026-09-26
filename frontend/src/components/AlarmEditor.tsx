import { useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { AlarmInput, AlarmRule } from '../types/alarms';
import { alarmsApi } from '../api/alarms';
export default function AlarmEditor({ rule, tags, onClose, onSaved }: { rule?: AlarmRule; tags: Tag[]; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState<AlarmInput>(rule ? { name: rule.name, description: rule.description, tag_id: rule.tag_id, operator: rule.operator, value: rule.value, severity: rule.severity, enabled: rule.enabled, for_duration_ms: rule.for_duration_ms, hysteresis: rule.hysteresis, notification_enabled: rule.notification_enabled } : { name: '', description: null, tag_id: tags[0]?.id ?? 0, operator: tags[0]?.data_type === 'bool' ? '==' : '>', value: tags[0]?.data_type === 'bool' ? true : '0', severity: 'WARNING', enabled: false, for_duration_ms: 0, hysteresis: '0', notification_enabled: false });
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const boolean = tags.find(tag => tag.id === value.tag_id)?.data_type === 'bool';
  const threshold = !boolean && !['==', '!='].includes(value.operator);
  const patch = (changes: Partial<AlarmInput>) => setValue(v => ({ ...v, ...changes }));
  async function save() {
    setBusy(true); setError('');
    try { if (rule) await alarmsApi.edit(rule.id, value); else await alarmsApi.create(value); onSaved(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Save failed'); }
    finally { setBusy(false); }
  }
  return <Dialog open fullWidth maxWidth="sm" onClose={busy ? undefined : onClose}><DialogTitle>{rule ? 'Edit alarm rule' : 'New alarm rule'}</DialogTitle>
    <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField label="Name" required value={value.name} onChange={e => patch({ name: e.target.value })} />
      <TextField label="Description" multiline value={value.description ?? ''} onChange={e => patch({ description: e.target.value || null })} />
      <TextField select label="Tag" value={value.tag_id} onChange={e => { const tag = tags.find(t => t.id === Number(e.target.value)); patch({ tag_id: Number(e.target.value), value: tag?.data_type === 'bool' ? true : '0', operator: tag?.data_type === 'bool' ? '==' : '>', hysteresis: '0' }); }}>{tags.map(t => <MenuItem key={t.id} value={t.id}>{t.name} ({t.key})</MenuItem>)}</TextField>
      <TextField select label="Operator" value={value.operator} onChange={e => patch({ operator: e.target.value as AlarmInput['operator'], hysteresis: '0' })}>{(boolean ? ['==', '!='] : ['>', '>=', '<', '<=', '==', '!=']).map(op => <MenuItem key={op} value={op}>{op}</MenuItem>)}</TextField>
      {boolean ? <TextField select label="Comparison value" value={String(value.value)} onChange={e => patch({ value: e.target.value === 'true' })}><MenuItem value="true">ON / true</MenuItem><MenuItem value="false">OFF / false</MenuItem></TextField> : <TextField label="Comparison value" value={value.value} onChange={e => patch({ value: e.target.value })} />}
      <TextField select label="Severity" value={value.severity} onChange={e => patch({ severity: e.target.value as AlarmInput['severity'] })}>{['INFO', 'WARNING', 'CRITICAL'].map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField>
      <TextField label="FOR (seconds)" type="number" value={(value.for_duration_ms ?? 0) / 1000} onChange={e => patch({ for_duration_ms: Number(e.target.value) * 1000 })} helperText="Condition must remain true on fresh GOOD telemetry." />
      {threshold && <TextField label="Hysteresis" value={value.hysteresis} onChange={e => patch({ hysteresis: e.target.value })} helperText="After activation: high alarm clears at threshold minus hysteresis; low alarm at threshold plus hysteresis." />}
      <FormControlLabel control={<Switch checked={value.enabled} onChange={(_, enabled) => patch({ enabled })} />} label="Enabled" />
      <FormControlLabel control={<Switch checked={value.notification_enabled} onChange={(_, notification_enabled) => patch({ notification_enabled })} />} label="Telegram on activation" />
      {rule && <Alert severity="info">Saving closes any open episode with a configuration-change reason. History is retained.</Alert>}
    </Stack></DialogContent><DialogActions><Button onClick={onClose} disabled={busy}>Cancel</Button><Button onClick={() => void save()} disabled={busy || !tags.length || !value.name.trim()} variant="contained">Save</Button></DialogActions></Dialog>;
}

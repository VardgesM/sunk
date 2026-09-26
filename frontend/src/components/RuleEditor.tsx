import { useState } from 'react';
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { Action, Condition, RuleInput, RuleValue } from '../types/automation';

function writableTags(tags: Tag[]) { return tags.filter(t => t.enabled && t.writable && ['coil', 'holding_register'].includes(t.register_type)); }
const empty: RuleInput = { name: '', description: null, enabled: false, priority: 0, condition_mode: 'ALL', for_duration_ms: null, cooldown_ms: null, conditions: [], actions: [] };
function ValueField({ label, value, boolean, onChange }: { label: string; value: RuleValue; boolean: boolean; onChange: (v: RuleValue) => void }) {
  return <TextField required fullWidth select={boolean} label={label} value={String(value)} onChange={e => onChange(boolean ? e.target.value === 'true' : e.target.value)}>{boolean && [<MenuItem key="true" value="true">ON / true</MenuItem>, <MenuItem key="false" value="false">OFF / false</MenuItem>]}</TextField>;
}
export default function RuleEditor({ initial, tags, onSave, onClose }: { initial?: RuleInput; tags: Tag[]; onSave: (r: RuleInput) => Promise<void>; onClose: () => void }) {
  const [rule, setRule] = useState<RuleInput>(initial || empty);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const targets = writableTags(tags);
  const set = (patch: Partial<RuleInput>) => setRule(r => ({ ...r, ...patch }));
  const condition = (i: number, patch: Partial<Condition>) => set({ conditions: rule.conditions.map((c, j) => j === i ? { ...c, ...patch } : c) });
  const action = (i: number, patch: Partial<Action>) => set({ actions: rule.actions.map((a, j) => j === i ? { ...a, ...patch } : a) });
  return <Dialog open fullWidth maxWidth="md" onClose={busy ? undefined : onClose}><DialogTitle>{initial ? 'Edit rule' : 'Create rule'}</DialogTitle>
    <form onSubmit={e => { e.preventDefault(); if (!rule.conditions.length || !rule.actions.length) { setError('Add at least one condition and action'); return; } setBusy(true); setError(''); void onSave(rule).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Save failed')).finally(() => setBusy(false)); }}>
      <DialogContent><Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}
        <Alert severity="info">Only fresh GOOD values are evaluated. Actions use the verified command queue. Physical writes require the worker master switch. Edited rules must observe false before they can trigger again.</Alert>
        <TextField required label="Rule name" value={rule.name} onChange={e => set({ name: e.target.value })} />
        <TextField label="Description" multiline value={rule.description || ''} onChange={e => set({ description: e.target.value || null })} />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField select label="Condition mode" value={rule.condition_mode} onChange={e => set({ condition_mode: e.target.value as 'ALL' | 'ANY' })}><MenuItem value="ALL">ALL / AND</MenuItem><MenuItem value="ANY">ANY / OR</MenuItem></TextField>
          <TextField type="number" label="Priority" value={rule.priority} onChange={e => set({ priority: Number(e.target.value) })} />
          <FormControlLabel control={<Checkbox checked={rule.enabled} onChange={e => set({ enabled: e.target.checked })} />} label="Enabled" />
        </Stack>
        <Typography variant="h6">WHEN</Typography>
        {rule.conditions.map((c, i) => { const boolean = tags.find(t => t.id === c.tag_id)?.data_type === 'bool'; return <Stack key={i} spacing={1} sx={{ border: '1px solid', borderColor: 'divider', p: 2 }}>
          <TextField select required label={`Condition ${i + 1} Tag`} value={c.tag_id} onChange={e => { const tag = tags.find(t => t.id === Number(e.target.value)); condition(i, { tag_id: Number(e.target.value), operator: tag?.data_type === 'bool' ? '==' : '>', value: tag?.data_type === 'bool' ? false : '0', hysteresis: '0' }); }}>{tags.map(t => <MenuItem key={t.id} value={t.id}>{t.name} ({t.key})</MenuItem>)}</TextField>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}><TextField select label={`Operator ${i + 1}`} value={c.operator} onChange={e => condition(i, { operator: e.target.value as Condition['operator'], hysteresis: '0' })}>{(boolean ? ['==', '!='] : ['>', '>=', '<', '<=', '==', '!=']).map(op => <MenuItem key={op} value={op}>{op}</MenuItem>)}</TextField>
            <ValueField label={`Comparison ${i + 1}`} value={c.value} boolean={boolean} onChange={value => condition(i, { value })} />
            {!boolean && !['==', '!='].includes(c.operator) && <TextField label={`Hysteresis ${i + 1}`} value={c.hysteresis} helperText="Reset distance in engineering units" onChange={e => condition(i, { hysteresis: e.target.value })} />}
          </Stack><Button onClick={() => set({ conditions: rule.conditions.filter((_, j) => j !== i) })}>Remove condition {i + 1}</Button>
        </Stack>; })}
        <Button disabled={!tags.length} onClick={() => { const t = tags[0]; set({ conditions: [...rule.conditions, { tag_id: t.id, operator: t.data_type === 'bool' ? '==' : '>', value: t.data_type === 'bool' ? false : '0', hysteresis: '0', sort_order: rule.conditions.length }] }); }}>Add condition</Button>
        <TextField type="number" label="FOR seconds" value={rule.for_duration_ms === null ? '' : rule.for_duration_ms / 1000} onChange={e => set({ for_duration_ms: e.target.value === '' ? null : Number(e.target.value) * 1000 })} helperText="Condition must remain true continuously" />
        <Typography variant="h6">THEN</Typography>
        {rule.actions.map((a, i) => <Stack key={i} spacing={1} sx={{ border: '1px solid', borderColor: 'divider', p: 2 }}>
          <TextField select required label={`Action ${i + 1} Tag`} value={a.target_tag_id} onChange={e => { const t = tags.find(t => t.id === Number(e.target.value)); action(i, { target_tag_id: Number(e.target.value), value: t?.data_type === 'bool' ? false : '0' }); }}>{targets.map(t => <MenuItem key={t.id} value={t.id}>{t.name} ({t.key})</MenuItem>)}</TextField>
          <ValueField label={`Requested ${i + 1}`} value={a.value} boolean={tags.find(t => t.id === a.target_tag_id)?.data_type === 'bool'} onChange={value => action(i, { value })} />
          <Button onClick={() => set({ actions: rule.actions.filter((_, j) => j !== i) })}>Remove action {i + 1}</Button>
        </Stack>)}
        <Button disabled={!targets.length} onClick={() => { const t = targets[0]; set({ actions: [...rule.actions, { target_tag_id: t.id, kind: 'SET_TAG_VALUE', value: t.data_type === 'bool' ? false : '0', sort_order: rule.actions.length }] }); }}>Add action</Button>
        {!targets.length && <Alert severity="warning">No enabled writable coil or holding-register Tags are available.</Alert>}
        <TextField type="number" label="Cooldown seconds" value={rule.cooldown_ms === null ? '' : rule.cooldown_ms / 1000} onChange={e => set({ cooldown_ms: e.target.value === '' ? null : Number(e.target.value) * 1000 })} helperText="Starts after all commands succeed; continuously true rules still run only once" />
      </Stack></DialogContent><DialogActions><Button disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy}>Save rule</Button></DialogActions>
    </form></Dialog>;
}

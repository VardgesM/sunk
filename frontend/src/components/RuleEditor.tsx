import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography, useMediaQuery, useTheme } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { Action, Condition, RuleInput, RuleValue } from '../types/automation';
import EditorSection from './automation/EditorSection';
import { conditionModes, operatorLabels } from './automation/presentation';
import { shellLayout } from '../layout/tokens';

function writableTags(tags: Tag[]) { return tags.filter(t => t.enabled && t.writable && ['coil', 'holding_register'].includes(t.register_type)); }
const empty: RuleInput = { name: '', description: null, enabled: false, priority: 0, condition_mode: 'ALL', for_duration_ms: null, cooldown_ms: null, conditions: [], actions: [] };
function ValueField({ label, value, boolean, onChange }: { label: string; value: RuleValue; boolean: boolean; onChange: (v: RuleValue) => void }) {
  return <TextField required fullWidth select={boolean} label={label} value={String(value)} onChange={e => onChange(boolean ? e.target.value === 'true' : e.target.value)}>{boolean && [<MenuItem key="true" value="true">ON / true</MenuItem>, <MenuItem key="false" value="false">OFF / false</MenuItem>]}</TextField>;
}
export default function RuleEditor({ initial, tags, onSave, onClose }: { initial?: RuleInput; tags: Tag[]; onSave: (r: RuleInput) => Promise<void>; onClose: () => void }) {
  const [rule, setRule] = useState<RuleInput>(initial || empty);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<{ kind: 'condition' | 'action'; index: number } | null>(null);
  const addCondition = useRef<HTMLButtonElement>(null), addAction = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const restoreAfterRemoval = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!removing && restoreAfterRemoval.current) {
      restoreAfterRemoval.current.focus();
      restoreAfterRemoval.current = null;
    }
  }, [removing]);
  const fullScreen = useMediaQuery(useTheme().breakpoints.down('sm'));
  const targets = writableTags(tags);
  const set = (patch: Partial<RuleInput>) => setRule(r => ({ ...r, ...patch }));
  const condition = (i: number, patch: Partial<Condition>) => set({ conditions: rule.conditions.map((c, j) => j === i ? { ...c, ...patch } : c) });
  const action = (i: number, patch: Partial<Action>) => set({ actions: rule.actions.map((a, j) => j === i ? { ...a, ...patch } : a) });
  return <><Dialog open fullScreen={fullScreen} fullWidth maxWidth="md" onClose={busy ? undefined : onClose} aria-labelledby="rule-editor-title"
    sx={{ '& .MuiButton-root': { minHeight: shellLayout.touchTarget }, '& .MuiSelect-select': { whiteSpace: 'normal', overflowWrap: 'anywhere' }, '& .MuiAlert-message': { minWidth: 0, overflowWrap: 'anywhere' } }}>
    <DialogTitle id="rule-editor-title">{initial ? 'Edit rule' : 'Create rule'}</DialogTitle>
    <Box component="form" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }} onSubmit={e => { e.preventDefault(); if (!rule.conditions.length || !rule.actions.length) { setError('Add at least one condition and action'); return; } setBusy(true); setError(''); void onSave(rule).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Save failed')).finally(() => setBusy(false)); }}>
      <DialogContent><Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}
        <EditorSection title="1. Basic information">
          <TextField required fullWidth label="Rule name" value={rule.name} onChange={e => set({ name: e.target.value })} />
          <TextField fullWidth label="Description" multiline value={rule.description || ''} onChange={e => set({ description: e.target.value || null })} />
          <FormControlLabel control={<Checkbox checked={rule.enabled} onChange={e => set({ enabled: e.target.checked })} />} label="Enabled" />
          <TextField fullWidth type="number" label="Priority" value={rule.priority} onChange={e => set({ priority: Number(e.target.value) })} helperText="Higher numbers are evaluated first. A conflicting lower-priority rule can be skipped." />
        </EditorSection>
        <EditorSection title="2. When">
        <Typography variant="body2" color="text.secondary">Only fresh GOOD readings can satisfy a rule.</Typography>
        <TextField fullWidth select label="Condition mode" value={rule.condition_mode} onChange={e => set({ condition_mode: e.target.value as 'ALL' | 'ANY' })}>
          <MenuItem value="ALL">{conditionModes.ALL} (ALL / AND)</MenuItem><MenuItem value="ANY">{conditionModes.ANY} (ANY / OR)</MenuItem>
        </TextField>
        {!rule.conditions.length && <Typography color="text.secondary">Add a condition to choose a Tag and a comparison.</Typography>}
        {rule.conditions.map((c, i) => { const tag = tags.find(t => t.id === c.tag_id); const boolean = tag?.data_type === 'bool'; return <Stack component="section" aria-label={`Condition ${i + 1}`} key={i} spacing={2} sx={{ borderTop: 1, borderColor: 'divider', pt: 2, minWidth: 0 }}>
          <Typography fontWeight={600}>Condition {i + 1}</Typography>
          <TextField fullWidth select required label={`Condition ${i + 1} Tag`} value={c.tag_id} onChange={e => { const tag = tags.find(t => t.id === Number(e.target.value)); condition(i, { tag_id: Number(e.target.value), operator: tag?.data_type === 'bool' ? '==' : '>', value: tag?.data_type === 'bool' ? false : '0', hysteresis: '0' }); }}>
            {!tag && <MenuItem value={c.tag_id} disabled>Tag #{c.tag_id} (unavailable)</MenuItem>}
            {tags.map(t => <MenuItem key={t.id} value={t.id} sx={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{t.name} ({t.key})</MenuItem>)}
          </TextField>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
            <TextField fullWidth select label={`Operator ${i + 1}`} value={c.operator} onChange={e => condition(i, { operator: e.target.value as Condition['operator'], hysteresis: '0' })}>{(boolean ? ['==', '!='] as const : ['>', '>=', '<', '<=', '==', '!='] as const).map(op => <MenuItem key={op} value={op}>{operatorLabels[op]} ({op})</MenuItem>)}</TextField>
            <ValueField label={`Comparison ${i + 1}${!boolean && tag?.unit ? ` (${tag.unit})` : ''}`} value={c.value} boolean={boolean} onChange={value => condition(i, { value })} />
          </Box>
          {!boolean && !['==', '!='].includes(c.operator) && <TextField fullWidth label={`Hysteresis ${i + 1}`} value={c.hysteresis} helperText={`Reset distance${tag?.unit ? ` (${tag.unit})` : ' in engineering units'}. Helps prevent repeated triggering near the threshold; does not add an opposite action.`} onChange={e => condition(i, { hysteresis: e.target.value })} />}
          <Button color="error" sx={{ alignSelf: 'flex-start' }} onClick={() => setRemoving({ kind: 'condition', index: i })}>Remove condition {i + 1}</Button>
        </Stack>; })}
        <Button ref={addCondition} disabled={!tags.length} onClick={() => { const t = tags[0]; set({ conditions: [...rule.conditions, { tag_id: t.id, operator: t.data_type === 'bool' ? '==' : '>', value: t.data_type === 'bool' ? false : '0', hysteresis: '0', sort_order: rule.conditions.length }] }); }}>Add condition</Button>
        </EditorSection>
        <EditorSection title="3. Then">
        <Typography variant="body2" color="text.secondary">Request these values through the existing command queue, in the configured order.</Typography>
        {!rule.actions.length && <Typography color="text.secondary">Add an action to choose a writable Tag.</Typography>}
        {rule.actions.map((a, i) => { const tag = tags.find(t => t.id === a.target_tag_id); return <Stack component="section" aria-label={`Action ${i + 1}`} key={i} spacing={2} sx={{ borderTop: 1, borderColor: 'divider', pt: 2, minWidth: 0 }}>
          <Typography fontWeight={600}>Action {i + 1}</Typography>
          <TextField fullWidth select required label={`Action ${i + 1} Tag`} value={a.target_tag_id} onChange={e => { const t = tags.find(t => t.id === Number(e.target.value)); action(i, { target_tag_id: Number(e.target.value), value: t?.data_type === 'bool' ? false : '0' }); }}>
            {!targets.some(t => t.id === a.target_tag_id) && <MenuItem value={a.target_tag_id} disabled>{tag?.name ?? `Tag #${a.target_tag_id}`} (unavailable for new actions)</MenuItem>}
            {targets.map(t => <MenuItem key={t.id} value={t.id} sx={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{t.name} ({t.key})</MenuItem>)}
          </TextField>
          <ValueField label={`Requested ${i + 1}${tag?.data_type !== 'bool' && tag?.unit ? ` (${tag.unit})` : ''}`} value={a.value} boolean={tag?.data_type === 'bool'} onChange={value => action(i, { value })} />
          <Button color="error" sx={{ alignSelf: 'flex-start' }} onClick={() => setRemoving({ kind: 'action', index: i })}>Remove action {i + 1}</Button>
        </Stack>; })}
        <Button ref={addAction} disabled={!targets.length} onClick={() => { const t = targets[0]; set({ actions: [...rule.actions, { target_tag_id: t.id, kind: 'SET_TAG_VALUE', value: t.data_type === 'bool' ? false : '0', sort_order: rule.actions.length }] }); }}>Add action</Button>
        {!targets.length && <Alert severity="warning">No enabled writable coil or holding-register Tags are available.</Alert>}
        </EditorSection>
        <EditorSection title="4. Execution behavior">
          <TextField fullWidth type="number" label="FOR seconds" value={rule.for_duration_ms === null ? '' : rule.for_duration_ms / 1000} onChange={e => set({ for_duration_ms: e.target.value === '' ? null : Number(e.target.value) * 1000 })} helperText="How long the combined condition must remain true before triggering. Blank means no delay." />
          <TextField fullWidth type="number" label="Cooldown seconds" value={rule.cooldown_ms === null ? '' : rule.cooldown_ms / 1000} onChange={e => set({ cooldown_ms: e.target.value === '' ? null : Number(e.target.value) * 1000 })} helperText="Starts after all commands succeed; continuously true rules still run only once." />
          <Alert severity="info">Physical writes require the worker master switch. Edited rules must observe false before they can trigger again. Saving this form does not send a manual command.</Alert>
        </EditorSection>
      </Stack></DialogContent><DialogActions sx={{ flexShrink: 0 }}><Button ref={cancel} disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" variant="contained" disabled={busy}>Save rule</Button></DialogActions>
    </Box></Dialog>
    {removing && <Dialog open fullWidth maxWidth="xs" onClose={() => setRemoving(null)} aria-labelledby="remove-rule-row-title" sx={{ '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
      <DialogTitle id="remove-rule-row-title">Remove {removing.kind} {removing.index + 1}?</DialogTitle>
      <DialogContent>This only changes the draft. The existing rule remains unchanged until you save.</DialogContent>
      <DialogActions><Button onClick={() => setRemoving(null)}>Keep {removing.kind}</Button><Button color="error" onClick={() => {
        const next = removing.kind === 'condition' ? addCondition.current : addAction.current;
        restoreAfterRemoval.current = next && !next.disabled ? next : cancel.current;
        if (removing.kind === 'condition') set({ conditions: rule.conditions.filter((_, index) => index !== removing.index) });
        else set({ actions: rule.actions.filter((_, index) => index !== removing.index) });
        setRemoving(null);
      }}>Remove {removing.kind}</Button></DialogActions>
    </Dialog>}
  </>;
}

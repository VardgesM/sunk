import { useId } from 'react';
import { Box, Button, Card, Stack, Typography } from '@mui/material';
import { usePermission } from '../../auth/context';
import type { Rule } from '../../types/automation';
import type { Tag } from '../../types/configuration';
import StatusBadge from '../data/StatusBadge';
import RowActions from '../data/RowActions';
import { DataDetails, DetailFields } from '../data/MobileDataCard';
import { shellLayout } from '../../layout/tokens';
import RuleError from './RuleError';
import { conditionModes, conditionSummary, displayTime, displayValue, reportedCondition, resultExplanation, stateExplanation, tagName } from './presentation';

export default function RuleCard({ rule, tags, busy, onEdit, onToggle, onDelete, onHistory }: {
  rule: Rule; tags: Map<number, Tag>; busy: boolean; onEdit: () => void; onToggle: () => void; onDelete: () => void; onHistory: () => void;
}) {
  const id = useId();
  const configure = usePermission('configure');
  const runtime = rule.runtime;
  const truth = reportedCondition(rule);
  return <Card component="article" aria-labelledby={id} variant="outlined" sx={{ p: { xs: 2, md: 2.5 }, minWidth: 0, overflowWrap: 'anywhere',
    '& .MuiButton-root': { minHeight: shellLayout.touchTarget }, '& ul': { m: 0, pl: 2.5 }, '& li + li': { mt: 0.75 } }}>
    <Stack spacing={2}>
      <Stack direction="row" flexWrap="wrap" gap={1} alignItems="flex-start">
        <Typography id={id} component="h2" variant="h6" sx={{ flex: '1 1 180px', minWidth: 0, lineHeight: 1.35 }}>{rule.name}</Typography>
        <StatusBadge label={rule.enabled ? 'Enabled' : 'Disabled'} />
      </Stack>
      <Box component="section" aria-label="When" sx={{ bgcolor: 'action.hover', p: 1.5, borderRadius: 1 }}>
        <Typography component="h3" variant="overline" fontWeight={700}>When</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{conditionModes[rule.condition_mode]}:</Typography>
        <Box component="ul">{rule.conditions.map((condition, index) => <Typography component="li" key={index} variant="body2">{conditionSummary(condition.tag_id, condition.operator, condition.value, tags)}</Typography>)}</Box>
        {!!rule.for_duration_ms && <Typography variant="body2" sx={{ mt: 1 }}>For {rule.for_duration_ms / 1000} seconds continuously</Typography>}
      </Box>
      <Box component="section" aria-label="Then">
        <Typography component="h3" variant="overline" fontWeight={700}>Then</Typography>
        <Box component="ol" sx={{ m: 0, pl: 2.5 }}>{rule.actions.map((action, index) => <Typography component="li" key={index} variant="body2" fontWeight={600}>
          {tagName(action.target_tag_id, tags)} → {displayValue(action.value, tags.get(action.target_tag_id)?.unit)}
        </Typography>)}</Box>
      </Box>
      <Stack spacing={1}>
        {!rule.enabled && <Typography variant="body2">Rule is disabled</Typography>}
        <Stack direction="row" flexWrap="wrap" gap={1} alignItems="center">
          <StatusBadge label={runtime?.state ?? 'Not reported'} />
          {runtime && <Typography variant="body2">{rule.enabled ? stateExplanation(runtime.state) : 'Last reported runtime'}</Typography>}
        </Stack>
        {truth ? <Typography variant="body2">Last reported conditions: {truth}</Typography> : rule.enabled && <Typography variant="body2" color="text.secondary">Condition state unavailable</Typography>}
        <Typography variant="body2">Last triggered: {displayTime(runtime?.last_triggered_at)}</Typography>
        {runtime?.last_result ? <Stack direction="row" flexWrap="wrap" gap={1}><StatusBadge label={runtime.last_result} /><Typography variant="body2">{resultExplanation(runtime.last_result)}</Typography></Stack> : <Typography variant="body2" color="text.secondary">No execution result yet</Typography>}
      </Stack>
      {runtime?.error && <RuleError error={runtime.error} />}
      <DataDetails label="Details">
        {rule.description && <Typography variant="body2" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>{rule.description}</Typography>}
        <DetailFields fields={[
          ['Priority', `${rule.priority} — higher priorities are evaluated first. Conflicting actions may be skipped.`],
          ['Logical mode', rule.condition_mode],
          ['Condition duration', `${(rule.for_duration_ms ?? 0) / 1000} seconds`],
          ['Cooldown', `${(rule.cooldown_ms ?? 0) / 1000} seconds after all commands succeed`],
          ['Condition true since', runtime?.true_since ? displayTime(runtime.true_since) : 'Not reported'],
          ['Cooldown until', runtime?.cooldown_until ? displayTime(runtime.cooldown_until) : 'Not reported'],
          ['Rule ID', rule.id],
        ]} />
        {rule.conditions.map((condition, index) => <Typography key={index} variant="body2" sx={{ mb: 1 }}>Condition {index + 1}: operator {condition.operator}; hysteresis {displayValue(condition.hysteresis, tags.get(condition.tag_id)?.unit)}</Typography>)}
        <Typography variant="caption" color="text.secondary">A continuously true condition does not run repeatedly. The reported condition includes configured hysteresis. Its evaluation time and per-condition results are not supplied.</Typography>
      </DataDetails>
      <Stack direction="row" flexWrap="wrap" gap={1}>
        {configure && <Button variant="outlined" onClick={onEdit}>Edit</Button>}
        <Button onClick={onHistory}>Executions</Button>
        {configure && <RowActions name={rule.name} actions={[
          { label: rule.enabled ? 'Disable rule' : 'Enable rule', run: onToggle, disabled: busy },
          { label: 'Delete rule', run: onDelete, destructive: true, disabled: busy },
        ]} />}
      </Stack>
    </Stack>
  </Card>;
}

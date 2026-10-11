import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Typography, useMediaQuery, useTheme } from '@mui/material';
import { automationApi } from '../../api/automation';
import type { Execution, Rule } from '../../types/automation';
import type { Tag } from '../../types/configuration';
import StatusBadge from '../data/StatusBadge';
import { DataDetails } from '../data/MobileDataCard';
import RuleError from './RuleError';
import { conditionSummary, displayTime, displayValue, resultExplanation } from './presentation';
import { shellLayout } from '../../layout/tokens';

export default function RuleHistory({ rule, tags, onClose }: { rule: Rule; tags: Map<number, Tag>; onClose: () => void }) {
  const [rows, setRows] = useState<Execution[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const fullScreen = useMediaQuery(useTheme().breakpoints.down('sm'));
  useEffect(() => {
    const controller = new AbortController();
    void automationApi.executions(rule.id, controller.signal).then(result => { if (!controller.signal.aborted) setRows(result); })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Request failed'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [rule.id]);
  return <Dialog open fullScreen={fullScreen} fullWidth maxWidth="md" onClose={onClose} aria-labelledby="execution-history-title" sx={{ '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
    <DialogTitle id="execution-history-title" sx={{ overflowWrap: 'anywhere' }}>{rule.name}: executions</DialogTitle>
    <DialogContent><Stack spacing={2}>
      {loading && <Typography role="status">Loading executions...</Typography>}
      {error && <Alert severity="error">{error}</Alert>}
      {!loading && !error && !rows.length && <Typography>No executions yet. This rule has not recorded a trigger.</Typography>}
      {rows.map(row => <Paper key={row.id} component="article" aria-label={`Execution ${row.id}`} variant="outlined" sx={{ p: 2, minWidth: 0, overflowWrap: 'anywhere' }}>
        <Stack spacing={1.5}>
          <Typography component="h3" variant="subtitle2">{displayTime(row.triggered_at)}</Typography>
          <Stack direction="row" flexWrap="wrap" gap={1}><StatusBadge label={row.result} /><Typography variant="body2">{resultExplanation(row.result).replace(/^Last execution/, 'Execution')}</Typography></Stack>
          {row.completed_at && <Typography variant="caption">Completed: {displayTime(row.completed_at)}</Typography>}
          {row.error && <RuleError error={row.error} />}
          <Box component="section" aria-label="Commands"><Typography variant="body2" fontWeight={600}>Commands</Typography>
            {row.command_ids.length ? <Stack direction="row" flexWrap="wrap" gap={1}>{row.command_ids.map(id => <Button key={id} component={Link} to={`/commands?command_id=${id}`} variant="outlined">#{id}</Button>)}</Stack> : <Typography variant="body2" color="text.secondary">No commands recorded</Typography>}
          </Box>
          <DataDetails label="Condition snapshot">
            {!row.snapshot.length && <Typography variant="body2">No condition snapshot available</Typography>}
            <Stack spacing={1.5}>{row.snapshot.map((condition, index) => <Box key={index}>
              <Typography variant="body2">{conditionSummary(condition.tag_id, condition.operator, condition.comparison, tags)}</Typography>
              <Typography variant="body2">Observed: {displayValue(condition.value, tags.get(condition.tag_id)?.unit)}</Typography>
              <StatusBadge label={condition.quality} />
            </Box>)}</Stack>
          </DataDetails>
        </Stack>
      </Paper>)}
    </Stack></DialogContent>
    <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
  </Dialog>;
}

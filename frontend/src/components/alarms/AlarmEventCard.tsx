import { useId } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Box, Button, Card, Chip, Stack, Typography } from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';
import Can from '../../auth/Can';
import { shellLayout } from '../../layout/tokens';
import type { AlarmEvent } from '../../types/alarms';
import { DetailFields } from '../data/MobileDataCard';
import { alarmTime, triggerValue } from './presentation';

const stateHelp = {
  ACTIVE: 'Not acknowledged',
  ACKNOWLEDGED: 'Acknowledged; not yet cleared',
  CLEARED: 'Episode closed',
};

export default function AlarmEventCard({ event, busy, onAcknowledge, onFocusFallback }: {
  event: AlarmEvent; busy: boolean; onAcknowledge: (event: AlarmEvent) => Promise<void>; onFocusFallback: () => void;
}) {
  const id = useId();
  const color = event.severity === 'CRITICAL' ? 'error' : event.severity === 'WARNING' ? 'warning' : 'info';
  async function acknowledge() {
    await onAcknowledge(event);
    // The ACTIVE-only filter can remove this card; keep focus on the results heading.
    onFocusFallback();
  }
  return <Card component="article" aria-labelledby={`${id}-title`} variant="outlined" sx={{
    p: { xs: 2, sm: 2.5 }, minWidth: 0, overflowWrap: 'anywhere', height: '100%',
    borderLeft: 4, borderLeftColor: event.state === 'CLEARED' ? 'divider' : `${color}.main`,
    '& .MuiButton-root': { minHeight: shellLayout.touchTarget },
  }}>
    <Stack spacing={1.5} sx={{ height: '100%' }}>
      <Stack direction="row" useFlexGap flexWrap="wrap" gap={1}>
        <Chip size="small" label={event.severity} color={color} variant="outlined" />
        <Chip size="small" label={event.state} color={event.state === 'ACTIVE' ? color : 'default'} />
      </Stack>
      <Box>
        <Typography id={`${id}-title`} component="h3" variant="h6" sx={{ lineHeight: 1.35 }}>{event.name}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{stateHelp[event.state]}</Typography>
      </Box>
      <Box>
        <Typography fontWeight={600}>{event.tag_name}</Typography>
        <Typography variant="caption" color="text.secondary">Value at activation</Typography>
        <Typography variant="h5" component="p" fontWeight={600}>{triggerValue(event)}</Typography>
        <Typography variant="body2" sx={{ mt: 0.5 }}>Condition: {event.condition}</Typography>
      </Box>
      <Typography variant="body2" color="text.secondary">Activated: <time dateTime={event.activated_at}>{alarmTime(event.activated_at)}</time></Typography>
      {event.state === 'ACKNOWLEDGED' && <Typography variant="body2">Acknowledged{event.acknowledged_by_username ? ` by ${event.acknowledged_by_username}` : ''}{event.acknowledged_at ? `: ${alarmTime(event.acknowledged_at)}` : ''}</Typography>}
      {event.state === 'CLEARED' && <Typography variant="body2">Cleared: {alarmTime(event.cleared_at)}</Typography>}
      {event.state === 'ACTIVE' && <Can permission="acknowledge"><Button variant="contained" disabled={busy}
        aria-label={`Acknowledge ${event.name}`} onClick={() => void acknowledge()} sx={{ alignSelf: { xs: 'stretch', sm: 'flex-start' } }}>Acknowledge</Button></Can>}
      <Box sx={{ flexGrow: 1 }} />
      <Accordion disableGutters elevation={0} sx={{ bgcolor: 'transparent', '&:before': { display: 'none' }, borderTop: 1, borderColor: 'divider' }}>
        <AccordionSummary id={`${id}-summary`} aria-controls={`${id}-details`} expandIcon={<ExpandMore />}
          aria-label={`Details for ${event.name}`} sx={{ px: 0, minHeight: shellLayout.touchTarget }}>
          <Typography variant="body2" fontWeight={600}>Details</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pb: 0 }}>
          <DetailFields fields={[
            ['Activated', alarmTime(event.activated_at)],
            ['Acknowledged', event.acknowledged_at ? alarmTime(event.acknowledged_at) : 'Not acknowledged'],
            ['Acknowledged by', event.acknowledged_by_username ?? (event.acknowledged_by ? `User ${event.acknowledged_by}` : 'Not recorded')],
            ['Cleared', event.cleared_at ? alarmTime(event.cleared_at) : 'Not cleared'],
            ['Event ID', event.id], ['Rule ID', event.rule_id], ['Tag ID', event.tag_id],
          ]} />
          {event.clear_reason && <Box><Typography variant="body2" fontWeight={600}>Clear reason</Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{event.clear_reason}</Typography></Box>}
        </AccordionDetails>
      </Accordion>
    </Stack>
  </Card>;
}

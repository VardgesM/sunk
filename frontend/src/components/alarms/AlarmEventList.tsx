import { useRef } from 'react';
import { Alert, Box, Stack, Typography } from '@mui/material';
import type { AlarmEvent } from '../../types/alarms';
import { shellLayout } from '../../layout/tokens';
import AlarmEventCard from './AlarmEventCard';
import { orderOpenAlarms } from './presentation';

export default function AlarmEventList({ events, history, loading, failed, filtered, busy, onAcknowledge }: {
  events: AlarmEvent[]; history: boolean; loading: boolean; failed: boolean; filtered: boolean; busy: boolean;
  onAcknowledge: (event: AlarmEvent) => Promise<void>;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const open = orderOpenAlarms(events.filter(event => event.state !== 'CLEARED'));
  const cleared = events.filter(event => event.state === 'CLEARED');
  function cards(rows: AlarmEvent[]) {
    return <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', [shellLayout.dataViewBreakpoint]: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
      {rows.map(event => <AlarmEventCard key={event.id} event={event} busy={busy} onAcknowledge={onAcknowledge} onFocusFallback={() => heading.current?.focus()} />)}
    </Box>;
  }
  return <Stack spacing={2}>
    <Box>
      <Typography ref={heading} tabIndex={-1} variant="h6" component="h2">{history ? 'Alarm history' : 'Active alarms'}</Typography>
      <Typography variant="body2" color="text.secondary">{history ? 'Recorded episodes, including open alarms. Dates are shown in your local time.' : 'Open alarms include acknowledged events until they clear. Acknowledgement does not clear the condition.'}</Typography>
    </Box>
    {loading ? <Typography role="status">Loading alarms…</Typography> : <>
      {!!open.length && <Box component="section" aria-label="Open alarms">
        {history && <Typography component="h2" variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>Still open on this page</Typography>}
        {cards(open)}
      </Box>}
      {!!cleared.length && history && <Box component="section" aria-label="Cleared alarms">
        <Typography component="h2" variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>Cleared episodes</Typography>
        {cards(cleared)}
      </Box>}
      {!events.length && !failed && (filtered ? <Typography>No alarms match these filters. Try resetting filters or another page.</Typography>
        : history ? <Typography>No alarm history yet.</Typography>
          : <Alert severity="success">No active alarms. No open alarm events are reported.</Alert>)}
    </>}
  </Stack>;
}

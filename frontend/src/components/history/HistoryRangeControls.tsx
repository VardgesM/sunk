import { Box, Button, Stack, TextField, Typography } from '@mui/material';
import { shellLayout } from '../../layout/tokens';

const ranges = [
  { value: '1', label: '1h', name: 'Last hour' }, { value: '6', label: '6h', name: 'Last 6 hours' },
  { value: '24', label: '24h', name: 'Last 24 hours' }, { value: '168', label: '7d', name: 'Last 7 days' },
  { value: '720', label: '30d', name: 'Last 30 days' }, { value: 'custom', label: 'Custom range', name: 'Custom range' },
];

export default function HistoryRangeControls({ range, from, to, loading, onRange, onFrom, onTo, onLoad }: {
  range: string; from: string; to: string; loading: boolean;
  onRange: (range: string) => void; onFrom: (value: string) => void; onTo: (value: string) => void; onLoad: () => void;
}) {
  return <Stack spacing={2} sx={{ minWidth: 0, '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
    <Box role="group" aria-label="History time range" sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(3, minmax(0, 1fr))', sm: 'repeat(6, minmax(0, 1fr))' }, gap: 1 }}>
      {ranges.map(item => <Button key={item.value} variant={range === item.value ? 'contained' : 'outlined'} aria-label={item.name}
        aria-pressed={range === item.value} onClick={() => onRange(item.value)} sx={{ minWidth: 0, whiteSpace: 'normal', lineHeight: 1.3 }}>{item.label}</Button>)}
    </Box>
    {range === 'custom' && <Box component="fieldset" sx={{ m: 0, p: 2, minWidth: 0, border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <Typography component="legend" variant="body2">Custom range</Typography>
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary">Enter local dates, then apply. Maximum range: 366 days. The chart keeps its applied range until you apply these dates.</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
          <TextField label="Start (local time)" type="datetime-local" value={from} onChange={e => onFrom(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} sx={{ minWidth: 0, '& input': { minWidth: 0 } }} />
          <TextField label="End (local time)" type="datetime-local" value={to} onChange={e => onTo(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} sx={{ minWidth: 0, '& input': { minWidth: 0 } }} />
        </Box>
      </Stack>
    </Box>}
    <Button variant="outlined" disabled={loading} onClick={onLoad} sx={{ alignSelf: { xs: 'stretch', sm: 'flex-start' } }}>{range === 'custom' ? 'Apply custom range' : 'Refresh history'}</Button>
  </Stack>;
}

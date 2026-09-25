import { useEffect, useState } from 'react';
import { Alert, Button, CircularProgress, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { getHistory } from '../api/history';
import type { HistoryResponse } from '../types/history';
import HistoricalChart from './HistoricalChart';

const ranges = [{ label: 'Last hour', hours: 1 }, { label: '6 hours', hours: 6 }, { label: '24 hours', hours: 24 }, { label: '7 days', hours: 168 }, { label: '30 days', hours: 720 }];

export default function TagHistory({ tagId }: { tagId: number }) {
  const [range, setRange] = useState('1');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [request, setRequest] = useState(() => ({ from: new Date(Date.now() - 3600000).toISOString(), to: new Date().toISOString() }));
  const [result, setResult] = useState<{ loading: boolean; data?: HistoryResponse; error?: string }>({ loading: true });
  const [rangeError, setRangeError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    getHistory(tagId, request.from, request.to, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResult({ loading: false, data }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setResult({ loading: false, error: error instanceof Error ? error.message : 'History query failed' }); });
    return () => controller.abort();
  }, [tagId, request]);
  function load(nextRange = range) {
    const end = nextRange === 'custom' ? new Date(to) : new Date();
    const start = nextRange === 'custom' ? new Date(from) : new Date(end.getTime() - Number(nextRange) * 3600000);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end || end.getTime() - start.getTime() > 366 * 86400000) {
      setRangeError('Choose a valid start and end, no more than 366 days apart.'); return;
    }
    setRangeError(''); setResult({ loading: true });
    setRequest({ from: start.toISOString(), to: end.toISOString() });
  }
  return <Stack spacing={2}>
    <Typography component="h2" variant="h5">History</Typography>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
      <TextField select label="Time range" value={range} sx={{ minWidth: 160 }} onChange={(event) => { setRange(event.target.value); if (event.target.value !== 'custom') load(event.target.value); }}>
        {ranges.map(({ label, hours }) => <MenuItem key={hours} value={String(hours)}>{label}</MenuItem>)}<MenuItem value="custom">Custom</MenuItem>
      </TextField>
      {range === 'custom' && <>
        <TextField label="Start (local time)" type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
        <TextField label="End (local time)" type="datetime-local" value={to} onChange={(event) => setTo(event.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
      </>}
      <Button onClick={() => load()}>{range === 'custom' ? 'Apply / Refresh' : 'Refresh history'}</Button>
    </Stack>
    <Typography variant="body2">Times are shown in your local timezone. History refreshes on request; current values update live independently.</Typography>
    {rangeError && <Alert severity="error">{rangeError}</Alert>}
    {result.loading && <Stack direction="row" gap={1} role="status"><CircularProgress size={20} />Loading history…</Stack>}
    {result.error && <Alert severity="error">{result.error}</Alert>}
    {result.data && <>
      <Typography variant="body2">{result.data.count} points from {result.data.total_count} stored records{result.data.downsampled ? ' — time buckets; numeric points show averages' : ''}.</Typography>
      {!!result.data.count && <Typography variant="body2">Sources: {[...new Set(result.data.points.map((point) => point.source ?? 'unknown / legacy or mixed bucket'))].join(', ')}</Typography>}
      {result.data.count === 0 ? <Alert severity="info">No history in this range. Enable history on the tag and wait for a sample.</Alert>
        : result.data.tag.data_type === 'bool' || ['uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64'].includes(result.data.tag.data_type)
          ? <HistoricalChart history={result.data} /> : <Alert severity="info">This value type is not chartable.</Alert>}
      {result.data.downsampled && <Typography variant="body2">Buckets containing an invalid quality or multiple boolean states appear as gaps. Zooming changes the view; choose a shorter time range to request finer detail.</Typography>}
    </>}
  </Stack>;
}

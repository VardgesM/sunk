import { useEffect, useState } from 'react';
import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import { getHistory } from '../api/history';
import type { HistoryResponse } from '../types/history';
import HistoricalChart from './HistoricalChart';
import HistoryRangeControls from './history/HistoryRangeControls';
import HistoryDataInfo from './history/HistoryDataInfo';
import { isHistoryChartable, localHistoryTime } from './history/presentation';

type RangeQuery = { from: string; to: string };

export default function TagHistory({ tagId, showHeading = true }: { tagId: number; showHeading?: boolean }) {
  const [range, setRange] = useState('1');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [request, setRequest] = useState<RangeQuery>(() => ({ from: new Date(Date.now() - 3600000).toISOString(), to: new Date().toISOString() }));
  const [result, setResult] = useState<{ tagId: number; query: RangeQuery; data?: HistoryResponse; error?: string }>();
  const [rangeError, setRangeError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    getHistory(tagId, request.from, request.to, controller.signal)
      .then(data => { if (!controller.signal.aborted) setResult({ tagId, query: request, data }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setResult({ tagId, query: request, error: error instanceof Error ? error.message : 'History query failed' }); });
    return () => controller.abort();
  }, [tagId, request]);
  function load(nextRange = range) {
    const end = nextRange === 'custom' ? new Date(to) : new Date();
    const start = nextRange === 'custom' ? new Date(from) : new Date(end.getTime() - Number(nextRange) * 3600000);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end || end.getTime() - start.getTime() > 366 * 86400000) {
      setRangeError('Choose a valid start and end, no more than 366 days apart.'); return;
    }
    setRangeError('');
    setRequest({ from: start.toISOString(), to: end.toISOString() });
  }
  const matched = result?.tagId === tagId && result.query === request;
  const loading = !matched;
  const data = matched ? result.data : undefined;
  const error = matched ? result.error : undefined;
  return <Stack spacing={2} sx={{ minWidth: 0, overflowWrap: 'anywhere', '& .MuiAlert-message': { minWidth: 0, overflowWrap: 'anywhere' } }}>
    {showHeading && <Typography component="h2" variant="h5">History</Typography>}
    <HistoryRangeControls range={range} from={from} to={to} loading={loading} onFrom={setFrom} onTo={setTo} onLoad={() => load()}
      onRange={next => { setRange(next); setRangeError(''); if (next !== 'custom') load(next); }} />
    <Box>
      <Typography variant="body2" fontWeight={600}>{loading ? 'Requested range' : 'Applied range'} (local time)</Typography>
      <Typography variant="body2">{localHistoryTime(request.from)} – {localHistoryTime(request.to)}</Typography>
      <Typography variant="caption" color="text.secondary">History refreshes on request; current values update live independently.</Typography>
    </Box>
    {rangeError && <Alert severity="error">{rangeError}</Alert>}
    {data?.truncated && <Alert severity="warning">The API limited this result. Only returned points are displayed; select a shorter range for more detail.</Alert>}
    <Box aria-busy={loading} sx={{ minWidth: 0, minHeight: { xs: 480, sm: 520 } }}>
      {loading ? <Stack spacing={2} alignItems="center" justifyContent="center" role="status" sx={{ minHeight: { xs: 480, sm: 520 } }}><CircularProgress size={24} /><Typography>Loading history…</Typography></Stack>
        : error ? <Alert severity="error" action={<Button onClick={() => setRequest({ ...request })} sx={{ minHeight: 44 }}>Retry history</Button>}>{error}</Alert>
          : data?.count === 0 ? <Alert severity="info">No historical data for this period. Try another range; history may not have been recorded for this Tag.</Alert>
            : data && (isHistoryChartable(data) ? <HistoricalChart history={data} /> : <Alert severity="info">This value type is not chartable.</Alert>)}
    </Box>
    {data && <HistoryDataInfo history={data} />}
  </Stack>;
}

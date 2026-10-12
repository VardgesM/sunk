import { Stack, Typography } from '@mui/material';
import type { HistoryResponse } from '../../types/history';
import StatusBadge from '../data/StatusBadge';
import { DataDetails } from '../data/MobileDataCard';
import { isHistoryChartable, plotValue } from './presentation';

export default function HistoryDataInfo({ history }: { history: HistoryResponse }) {
  const gaps = history.points.filter(point => plotValue(history, point) === null).length;
  const qualities = [...new Set(history.points.map(point => point.quality))];
  return <Stack spacing={1} sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <Typography variant="body2">{history.count} returned {history.downsampled ? 'buckets' : 'points'} from {history.total_count} stored records in the requested range.</Typography>
    {!!history.count && isHistoryChartable(history) && <Typography variant="body2" color="text.secondary">{history.points.length - gaps} plotted points · {gaps} gaps in returned points. Gaps are not connected.</Typography>}
    {history.downsampled && <Typography variant="body2">Numeric buckets show averages. Invalid-quality buckets and mixed boolean states remain gaps. Select a shorter range for finer detail.</Typography>}
    {!!history.count && <DataDetails label="Data details">
      <Stack spacing={1}>
        <Typography variant="body2">Quality of returned points (not counts of original samples):</Typography>
        <Stack direction="row" useFlexGap flexWrap="wrap" gap={1.5}>{qualities.map(quality => <Stack key={quality} direction="row" alignItems="center" gap={0.5}>
          <StatusBadge label={quality} /><Typography variant="body2">× {history.points.filter(point => point.quality === quality).length}</Typography>
        </Stack>)}</Stack>
        <Typography variant="body2">Sources: {[...new Set(history.points.map(point => point.source ?? 'unknown / legacy or mixed bucket'))].join(', ')}</Typography>
        <Typography variant="body2">Only stored records are shown. A silent time interval does not prove continuous coverage; no missing samples are invented.</Typography>
      </Stack>
    </DataDetails>}
  </Stack>;
}

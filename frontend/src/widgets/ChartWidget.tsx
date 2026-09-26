import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { init, use as register } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { getHistory } from '../api/history';
import type { Widget } from '../types/dashboards';
import type { HistoryResponse } from '../types/history';
register([LineChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, AriaComponent, SVGRenderer]);

function Plot({ data, legend }: { data: HistoryResponse[]; legend: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = init(container.current, undefined, { renderer: 'svg' });
    chart.setOption({ animation: false, aria: { enabled: true, label: { description: 'Historical line chart' } },
      legend: { show: legend, type: 'scroll' }, grid: { left: 60, right: 15, top: 45, bottom: 65 },
      tooltip: { trigger: 'axis', renderMode: 'richText' }, xAxis: { type: 'time', axisLabel: { hideOverlap: true } },
      yAxis: { type: 'value', scale: true, name: data[0]?.tag.unit ?? '' },
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 5 }],
      series: data.map(history => ({ name: history.tag.name, type: 'line', connectNulls: false, showSymbol: false,
        data: history.points.map(p => [p.recorded_at, p.has_invalid || p.quality !== 'GOOD' ? null : p.value_numeric]) })),
    });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(container.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [data, legend]);
  return <Box ref={container} role="img" aria-label="Historical line chart" sx={{ width: '100%', minWidth: 0, height: 300 }} />;
}

export default function ChartWidget({ widget }: { widget: Widget }) {
  const [range, setRange] = useState(String(widget.configuration.range_hours ?? 1));
  const [start, setStart] = useState(''), [end, setEnd] = useState('');
  const [query, setQuery] = useState(() => ({ from: new Date(Date.now() - Number(range) * 3600000).toISOString(), to: new Date().toISOString() }));
  const [data, setData] = useState<HistoryResponse[]>();
  const [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const [rangeError, setRangeError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    Promise.all(widget.tag_ids.map(id => getHistory(id, query.from, query.to, controller.signal)))
      .then(result => { if (!controller.signal.aborted) { setData(result); setError(''); setLoading(false); } })
      .catch((e: unknown) => { if (!controller.signal.aborted) { setError(e instanceof Error ? e.message : 'History unavailable'); setLoading(false); } });
    return () => controller.abort();
  }, [widget.tag_ids, query]);
  useEffect(() => {
    const seconds = widget.configuration.refresh_seconds ?? 0;
    if (!seconds || range === 'custom') return;
    const timer = setInterval(() => { setLoading(true); setQuery({ from: new Date(Date.now() - Number(range) * 3600000).toISOString(), to: new Date().toISOString() }); }, seconds * 1000);
    return () => clearInterval(timer);
  }, [range, widget.configuration.refresh_seconds]);
  function refresh(next = range) {
    const to = next === 'custom' ? new Date(end) : new Date();
    const from = next === 'custom' ? new Date(start) : new Date(to.getTime() - Number(next) * 3600000);
    if (!Number.isFinite(from.getTime()) || !Number.isFinite(to.getTime()) || from >= to || to.getTime() - from.getTime() > 366 * 86400000) {
      setRangeError('Choose a valid range of at most 366 days'); return;
    }
    setRangeError(''); setLoading(true); setQuery({ from: from.toISOString(), to: to.toISOString() });
  }
  const ranges = [...new Set([1, 6, 24, 168, widget.configuration.range_hours ?? 1])];
  return <Stack spacing={1}>
    <Stack direction="row" flexWrap="wrap" gap={1}>
      <TextField size="small" select label="Chart range" value={range} onChange={e => { setRange(e.target.value); if (e.target.value !== 'custom') refresh(e.target.value); }} sx={{ minWidth: 140 }}>
        {ranges.map(h => <MenuItem key={h} value={String(h)}>{h === 168 ? '7 days' : `${h} hours`}</MenuItem>)}<MenuItem value="custom">Custom</MenuItem>
      </TextField><Button onClick={() => refresh()}>Refresh history</Button>
    </Stack>
    {range === 'custom' && <><TextField type="datetime-local" label="Start (local time)" value={start} onChange={e => setStart(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} /><TextField type="datetime-local" label="End (local time)" value={end} onChange={e => setEnd(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} /></>}
    {(error || rangeError) && <Alert severity="error">{error || rangeError}</Alert>}
    {loading && <Typography role="status">Loading history...</Typography>}
    {data && !error && (data.every(h => !h.count) ? <Typography>No history in this range</Typography> : <Plot data={data} legend={widget.configuration.legend !== false} />)}
    <Typography variant="caption">Local timestamps; quality gaps preserved. Downsampled points show bucket averages. History refresh is separate from live values.</Typography>
  </Stack>;
}

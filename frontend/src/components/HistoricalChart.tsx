import { useEffect, useId, useRef } from 'react';
import { Box, Button, Stack, Typography } from '@mui/material';
import { init, use as registerECharts } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { HistoryResponse } from '../types/history';
import type { EChartsType } from 'echarts/core';
import { historyTooltip, plotValue } from './history/presentation';

registerECharts([LineChart, GridComponent, TooltipComponent, DataZoomComponent, AriaComponent, SVGRenderer]);

export default function HistoricalChart({ history }: { history: HistoryResponse }) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<EChartsType | null>(null);
  const description = useId();
  useEffect(() => {
    if (!container.current) return;
    const chart = init(container.current, undefined, { renderer: 'svg' });
    instance.current = chart;
    const binary = history.tag.data_type === 'bool';
    const compactOptions = () => {
      const width = container.current?.clientWidth ?? 0;
      const narrow = width < 480;
      return {
        grid: { left: 8, right: 12, top: 20, bottom: 70, containLabel: true },
        tooltip: historyTooltip([history], width, container.current?.clientHeight ?? 340),
        xAxis: { type: 'time', splitNumber: narrow ? 3 : 6, axisLabel: { hideOverlap: true, fontSize: 11 } },
      };
    };
    chart.setOption({
      animation: false, aria: { enabled: true, label: { description: `${history.tag.name} ${binary ? 'boolean step' : 'numeric line'} history chart` } },
      ...compactOptions(),
      yAxis: { type: 'value', scale: !binary,
        ...(binary ? { min: 0, max: 1, interval: 1, axisLabel: { formatter: (value: number) => value === 1 ? 'True' : 'False' } } : {}) },
      dataZoom: [{ type: 'inside', zoomOnMouseWheel: false, moveOnMouseWheel: false }, { type: 'slider', bottom: 8, height: 28, showDetail: false }],
      series: [{ name: history.tag.name, type: 'line', step: binary ? 'end' : false,
        connectNulls: false, showSymbol: history.points.length < 100, symbolSize: 6,
        data: history.points.map(point => [point.recorded_at, plotValue(history, point)]) }],
    });
    const observer = new ResizeObserver(() => { chart.resize(); chart.setOption(compactOptions()); });
    observer.observe(container.current);
    return () => { observer.disconnect(); chart.dispose(); instance.current = null; };
  }, [history]);
  return <Stack spacing={1} sx={{ minWidth: 0 }}>
    {history.tag.unit && <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>Unit: {history.tag.unit}</Typography>}
    <Box ref={container} role="img" aria-describedby={description} aria-label={`${history.tag.name} ${history.tag.data_type === 'bool' ? 'boolean step' : 'numeric line'} history chart`}
      sx={{ width: '100%', maxWidth: '100%', minWidth: 0, height: { xs: 340, sm: 420 } }} />
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
      <Typography id={description} variant="caption" color="text.secondary" sx={{ flex: 1 }}>Tap or point at the chart for values and local timestamps. Use the slider to zoom. Invalid values remain gaps; zoom does not request new samples.</Typography>
      <Button onClick={() => instance.current?.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })} sx={{ minHeight: 44, flexShrink: 0 }}>Reset zoom</Button>
    </Stack>
  </Stack>;
}

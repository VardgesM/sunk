import { useEffect, useRef } from 'react';
import { Box } from '@mui/material';
import { init, use as registerECharts } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { HistoryResponse } from '../types/history';

registerECharts([LineChart, GridComponent, TooltipComponent, DataZoomComponent, AriaComponent, SVGRenderer]);

export default function HistoricalChart({ history }: { history: HistoryResponse }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = init(container.current, undefined, { renderer: 'svg' });
    const binary = history.tag.data_type === 'bool';
    chart.setOption({
      animation: false, aria: { enabled: true, label: { description: `${history.tag.name} ${binary ? 'boolean step' : 'numeric line'} history chart` } },
      grid: { left: 65, right: 20, top: 40, bottom: 85 },
      tooltip: { trigger: 'axis', renderMode: 'richText', valueFormatter: (value: unknown) => binary ? value === 1 ? 'True' : value === 0 ? 'False' : 'No valid value' : `${value ?? 'No valid value'} ${history.tag.unit ?? ''}` },
      xAxis: { type: 'time', axisLabel: { hideOverlap: true } },
      yAxis: { type: 'value', name: history.tag.unit ?? '', scale: !binary,
        ...(binary ? { min: 0, max: 1, interval: 1, axisLabel: { formatter: (value: number) => value === 1 ? 'True' : 'False' } } : {}) },
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
      series: [{ name: history.tag.name, type: 'line', step: binary ? 'end' : false,
        connectNulls: false, showSymbol: history.points.length < 100, symbolSize: 6,
        data: history.points.map((point) => [point.recorded_at, point.has_invalid || point.quality !== 'GOOD' ? null
          : binary ? point.value_boolean === null ? null : Number(point.value_boolean) : point.value_numeric]) }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [history]);
  return <Box ref={container} role="img" aria-label={`${history.tag.name} ${history.tag.data_type === 'bool' ? 'boolean step' : 'numeric line'} history chart`}
    sx={{ width: '100%', minWidth: 0, height: { xs: 320, sm: 420 } }} />;
}

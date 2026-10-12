import type { TooltipComponentOption } from 'echarts';
import type { HistoryPoint, HistoryResponse } from '../../types/history';

// Keep the existing plot semantics: invalid quality and ambiguous buckets are gaps.
export function plotValue(history: HistoryResponse, point: HistoryPoint): number | null {
  if (point.has_invalid || point.quality !== 'GOOD') return null;
  return history.tag.data_type === 'bool'
    ? point.value_boolean === null ? null : Number(point.value_boolean)
    : point.value_numeric;
}

export const localHistoryTime = (timestamp: string) => new Date(timestamp).toLocaleString();

export function isHistoryChartable(history: HistoryResponse): boolean {
  return ['bool', 'uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64'].includes(history.tag.data_type);
}

export function historyTooltip(data: HistoryResponse[], width: number, height = 340): TooltipComponentOption {
  const touch = window.matchMedia?.('(pointer: coarse)').matches;
  return {
    trigger: 'axis', renderMode: 'html', confine: true, enterable: true,
    // Open after a tap, not on touch-start before the synthetic pointer-leave.
    ...(touch ? { triggerOn: 'click' as const } : {}),
    hideDelay: touch ? 8000 : 100,
    transitionDuration: 0,
    // Keep an interactive tooltip away from the tapping finger. Otherwise a synthetic
    // mouse-leave can immediately dismiss it, and the content obscures the selected point.
    position: touch ? (point, _params, _element, _rect, size) => [
      Math.max(0, (size.viewSize[0] - size.contentSize[0]) / 2),
      point[1] < size.viewSize[1] / 2 ? Math.max(0, size.viewSize[1] - size.contentSize[1] - 4) : 4,
    ] : undefined,
    formatter(params) {
      const root = document.createElement('div');
      root.setAttribute('role', 'tooltip');
      Object.assign(root.style, { maxWidth: `${Math.max(80, Math.min(320, width - 48))}px`, maxHeight: touch ? `${Math.max(60, Math.min(160, height / 2 - 32))}px` : '210px',
        overflowY: 'auto', whiteSpace: 'normal', overflowWrap: 'anywhere', fontSize: '13px', lineHeight: '1.5' });
      for (const item of Array.isArray(params) ? params : [params]) {
        const history = data[item.seriesIndex ?? 0];
        const point = history?.points[item.dataIndex];
        if (!history || !point) continue;
        const block = document.createElement('div');
        block.style.marginBottom = '8px';
        const value = plotValue(history, point) === null ? 'No valid plotted value'
          : history.tag.data_type === 'bool' ? point.value_boolean ? 'ON / true' : 'OFF / false'
            : `${point.value_numeric_exact ?? point.value_numeric}${history.tag.unit ? ` ${history.tag.unit}` : ''}`;
        const lines = [localHistoryTime(point.recorded_at),
          `${history.downsampled && history.tag.data_type !== 'bool' ? 'Bucket average' : 'Value'}: ${value}`,
          `Quality: ${point.quality}${point.has_invalid ? ' · contains invalid samples; shown as a gap' : ''}`,
          `Tag: ${history.tag.name}`];
        if (history.downsampled) lines.push(`Bucket: ${localHistoryTime(point.first_timestamp)} – ${localHistoryTime(point.last_timestamp)}`, `Stored records: ${point.sample_count}`);
        for (const [index, line] of lines.entries()) {
          const row = document.createElement('div');
          // Tag names/units are configuration data, never HTML or rich-text markup.
          row.textContent = line;
          if (index === 1) row.style.fontWeight = '600';
          block.append(row);
        }
        root.append(block);
      }
      return root;
    },
  };
}

import { render } from './render';
import { useState } from 'react';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as historyApi from '../api/history';
import HistorySettings from '../components/HistorySettings';
import HistoricalChart from '../components/HistoricalChart';
import TagHistory from '../components/TagHistory';
import HistoryPage from '../pages/HistoryPage';
import { tagsApi } from '../api/configuration';
import { historyTooltip, plotValue } from '../components/history/presentation';
import type { HistoryResponse } from '../types/history';
import type { Tag, TagInput } from '../types/configuration';
import type { DefaultLabelFormatterCallbackParams as CallbackDataParams } from 'echarts';

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), dispatchAction: vi.fn() }));
vi.mock('echarts/core', () => ({ init: () => chart, use: vi.fn() }));

const input: TagInput = { name: 'Test', key: 'test', device_id: 1, register_type: 'holding_register', address: 0,
  data_type: 'float32', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: 'unit', poll_interval_ms: 1000,
  writable: false, enabled: true, min_value: null, max_value: null, description: null,
  history_enabled: true, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null };
const response: HistoryResponse = { tag: { id: 1, key: 'test', name: 'Test', unit: 'unit', data_type: 'float32' },
  from_timestamp: '2026-01-01T00:00:00Z', to_timestamp: '2026-01-01T01:00:00Z', count: 1, total_count: 1,
  downsampled: false, truncated: false, points: [{ recorded_at: '2026-01-01T00:01:00Z', source_timestamp: '2026-01-01T00:01:00Z',
    value_numeric: 12, value_numeric_exact: '12', value_boolean: null, value_text: null, quality: 'GOOD',
    minimum: null, maximum: null, average: null, first_timestamp: '2026-01-01T00:01:00Z', last_timestamp: '2026-01-01T00:01:00Z', sample_count: 1, has_invalid: false }] };

function SettingsForm({ boolean = false }: { boolean?: boolean }) {
  const [value, setValue] = useState<TagInput>({ ...input, data_type: boolean ? 'bool' : 'float32' });
  return <HistorySettings value={value} change={(field, next) => setValue((old) => ({ ...old, [field]: next }))} />;
}

describe('history UI', () => {
  beforeEach(() => {
    chart.setOption.mockClear(); chart.dispose.mockClear();
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  });
  it('shows interval and numeric threshold only for the selected policy', async () => {
    const user = userEvent.setup(); render(<SettingsForm />);
    expect(screen.queryByLabelText(/History interval/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'History mode' }));
    await user.click(screen.getByRole('option', { name: 'fixed_interval' }));
    expect(screen.getByLabelText(/History interval/)).toHaveAttribute('min', '1000');
    await user.click(screen.getByRole('combobox', { name: 'History mode' }));
    await user.click(screen.getByRole('option', { name: 'on_change' }));
    expect(screen.getByLabelText(/Change threshold/)).toBeRequired();
    expect(screen.queryByLabelText(/History interval/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Retention days/)).toBeInTheDocument();
  });
  it('explains boolean change policy without a numeric threshold', async () => {
    const user = userEvent.setup(); render(<SettingsForm boolean />);
    await user.click(screen.getByRole('combobox', { name: 'History mode' }));
    await user.click(screen.getByRole('option', { name: 'on_change' }));
    expect(screen.getByText('Stores each boolean state change.')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Change threshold/)).not.toBeInTheDocument();
  });
  it('loads REST history and renders a numeric chart', async () => {
    let finish!: (data: HistoryResponse) => void;
    vi.spyOn(historyApi, 'getHistory').mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<TagHistory tagId={1} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading history');
    await act(async () => { finish(response); });
    expect(await screen.findByRole('img')).toHaveAccessibleName('Test numeric line history chart');
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ series: [expect.objectContaining({ type: 'line', step: false, connectNulls: false })] }));
  });
  it('renders explicit empty and API error states with retry', async () => {
    const get = vi.spyOn(historyApi, 'getHistory').mockResolvedValue({ ...response, count: 0, points: [] });
    const user = userEvent.setup(); render(<TagHistory tagId={1} />);
    expect(await screen.findByText(/No historical data for this period/)).toBeInTheDocument();
    get.mockRejectedValueOnce(new Error('Database unavailable'));
    await user.click(screen.getByRole('button', { name: 'Refresh history' }));
    expect(await screen.findByText('Database unavailable')).toBeInTheDocument();
  });
  it('uses a boolean step chart and preserves false as zero', () => {
    const history = { ...response, tag: { ...response.tag, data_type: 'bool' }, points: [{ ...response.points[0], value_numeric: null, value_boolean: false }] };
    const { unmount } = render(<HistoricalChart history={history} />);
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ series: [expect.objectContaining({ step: 'end', data: [[response.points[0].recorded_at, 0]] })] }));
    unmount(); expect(chart.dispose).toHaveBeenCalledOnce();
  });
  it('passes null gaps for invalid history instead of retained current values', () => {
    render(<HistoricalChart history={{ ...response, points: [{ ...response.points[0], quality: 'COMM_ERROR', has_invalid: true }] }} />);
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ series: [expect.objectContaining({ connectNulls: false, data: [[response.points[0].recorded_at, null]] })] }));
  });
  it('changes preset ranges and validates custom local dates', async () => {
    const get = vi.spyOn(historyApi, 'getHistory').mockResolvedValue(response);
    const user = userEvent.setup(); render(<TagHistory tagId={1} />);
    await screen.findByRole('img');
    await user.click(screen.getByRole('button', { name: 'Last 7 days' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const [, from, to] = get.mock.calls[1];
    expect(new Date(to).getTime() - new Date(from).getTime()).toBe(7 * 86400000);
    await user.click(screen.getByRole('button', { name: 'Custom range' }));
    await user.click(screen.getByRole('button', { name: 'Apply custom range' }));
    expect(screen.getByText(/Choose a valid start/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });
  it('encodes UTC ranges and a bounded point count in API requests', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    await historyApi.getHistory(1, response.from_timestamp, response.to_timestamp);
    const url = new URL(fetch.mock.calls[0][0], 'http://test');
    expect(url.searchParams.get('from')).toBe(response.from_timestamp);
    expect(url.searchParams.get('max_points')).toBe('1000');
    expect(url.searchParams.get('limit')).toBe('1000');
    expect(url.pathname).toBe('/api/tags/1/history');
  });
});

const tag: Tag = { ...input, id: 1, created_at: '', updated_at: '' };
const tagTwo: Tag = { ...tag, id: 2, name: 'Another measurement', key: 'another', unit: '%' };
const initialize = () => {
  chart.setOption.mockClear(); chart.dispatchAction.mockClear();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.spyOn(tagsApi, 'all').mockResolvedValue([tag, tagTwo]);
  return vi.spyOn(historyApi, 'getHistory').mockResolvedValue(response);
};

describe('history selection and responsive controls', () => {
  it('starts without an invented Tag selection and searches by key or unit', async () => {
    const get = initialize(); render(<HistoryPage />);
    expect(screen.getByText(/No Tag selected/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(get).not.toHaveBeenCalled();
    await userEvent.type(screen.getByRole('combobox', { name: 'History Tag' }), 'another');
    await userEvent.click(await screen.findByRole('option', { name: /Another measurement/ }));
    await waitFor(() => expect(get).toHaveBeenCalledWith(2, expect.any(String), expect.any(String), expect.any(AbortSignal)));
    expect(screen.getByRole('heading', { name: 'Another measurement' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText(/No Tag selected/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole('combobox', { name: 'History Tag' }), '%');
    expect(screen.getAllByRole('option')).toHaveLength(1);
  });
  it('bounds the option DOM while searching all loaded Tags and shows full long names', async () => {
    initialize(); const long = 'Long_unbroken_name_'.repeat(15);
    vi.mocked(tagsApi.all).mockResolvedValue(Array.from({ length: 200 }, (_, id) => ({ ...tag, id: id + 1, name: id === 199 ? long : `Tag ${id}`, key: `key_${id}` })));
    render(<HistoryPage />); await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    const selector = screen.getByRole('combobox', { name: 'History Tag' });
    await userEvent.click(selector); expect(screen.getAllByRole('option')).toHaveLength(80);
    await userEvent.type(selector, 'key_199');
    await userEvent.click(screen.getByRole('option', { name: new RegExp(long) }));
    expect(screen.getByRole('heading', { name: long })).toBeInTheDocument();
  });
  it('reports Tag loading failure and retries metadata without a history query', async () => {
    const get = initialize(); vi.mocked(tagsApi.all).mockRejectedValueOnce(new Error('Tag metadata unavailable'));
    render(<HistoryPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Tag metadata unavailable');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(tagsApi.all).toHaveBeenCalledTimes(2); expect(get).not.toHaveBeenCalled();
  });
  it.each([['Last hour', 1], ['Last 6 hours', 6], ['Last 24 hours', 24], ['Last 7 days', 168], ['Last 30 days', 720]])('applies %s with the existing UTC API arguments', async (label, hours) => {
    const get = initialize(); render(<TagHistory tagId={1} />); await screen.findByRole('img');
    await userEvent.click(screen.getByRole('button', { name: String(label) }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const [id, from, to] = get.mock.calls[1];
    expect(id).toBe(1); expect(from.endsWith('Z') && to.endsWith('Z')).toBe(true);
    expect(Date.parse(to) - Date.parse(from)).toBe(Number(hours) * 3600000);
    expect(screen.getByRole('button', { name: String(label) })).toHaveAttribute('aria-pressed', 'true');
  });
  it('applies custom local dates only when requested and rejects inverted/oversized ranges', async () => {
    const get = initialize(); render(<TagHistory tagId={1} />); await screen.findByRole('img');
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    const start = screen.getByLabelText('Start (local time)'), end = screen.getByLabelText('End (local time)');
    fireEvent.change(start, { target: { value: '2026-01-02T10:00' } });
    fireEvent.change(end, { target: { value: '2026-01-03T12:00' } });
    expect(get).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Apply custom range' }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith(1, new Date('2026-01-02T10:00').toISOString(), new Date('2026-01-03T12:00').toISOString(), expect.any(AbortSignal)));
    fireEvent.change(end, { target: { value: '2025-01-01T10:00' } });
    await userEvent.click(screen.getByRole('button', { name: 'Apply custom range' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a valid start and end');
    fireEvent.change(end, { target: { value: '2028-01-01T10:00' } });
    await userEvent.click(screen.getByRole('button', { name: 'Apply custom range' }));
    expect(get).toHaveBeenCalledTimes(2);
  });
  it('hides stale chart data while the Tag changes and aborts earlier requests', async () => {
    const get = initialize(); const { rerender } = render(<TagHistory tagId={1} />); await screen.findByRole('img');
    let finish!: (data: HistoryResponse) => void;
    get.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    rerender(<TagHistory tagId={2} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading history');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(get.mock.calls[0][3]?.aborted).toBe(true);
    await act(async () => finish({ ...response, tag: { ...response.tag, id: 2, name: 'Second history' } }));
    expect(await screen.findByRole('img')).toHaveAccessibleName('Second history numeric line history chart');
  });
  it('ignores late range responses and retries the applied range after an error', async () => {
    const get = initialize(); let finish!: (data: HistoryResponse) => void;
    get.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    render(<TagHistory tagId={1} />);
    await userEvent.click(screen.getByRole('button', { name: 'Last 24 hours' }));
    await screen.findByRole('img');
    await act(async () => finish({ ...response, tag: { ...response.tag, name: 'Old response' } }));
    expect(screen.getByRole('img')).not.toHaveAccessibleName('Old response numeric line history chart');
    get.mockRejectedValueOnce(new Error('History query unavailable'));
    await userEvent.click(screen.getByRole('button', { name: 'Refresh history' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('History query unavailable');
    const failed = get.mock.calls.at(-1)!;
    await userEvent.click(screen.getByRole('button', { name: 'Retry history' }));
    await screen.findByRole('img');
    expect(get.mock.calls.at(-1)!.slice(0, 3)).toEqual(failed.slice(0, 3));
  });
  it('explains bucket gaps, limits and source provenance without invented summary statistics', async () => {
    const get = initialize(); get.mockResolvedValue({ ...response, downsampled: true, truncated: true, total_count: 2000, points: [{ ...response.points[0], has_invalid: true, source: 'modbus_rtu' }] });
    render(<TagHistory tagId={1} />); await screen.findByRole('img');
    expect(screen.getByRole('alert')).toHaveTextContent('The API limited this result');
    expect(screen.getByText('1 returned buckets from 2000 stored records in the requested range.')).toBeInTheDocument();
    expect(screen.getByText(/0 plotted points · 1 gaps/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Data details' }));
    expect(screen.getByText('Sources: modbus_rtu')).toBeVisible();
    expect(screen.queryByText('Average')).not.toBeInTheDocument();
  });
  it('does not pretend future text data is numeric', async () => {
    initialize().mockResolvedValue({ ...response, tag: { ...response.tag, data_type: 'text' } });
    render(<TagHistory tagId={1} />);
    expect(await screen.findByText('This value type is not chartable.')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

describe('history chart presentation', () => {
  beforeEach(() => { initialize(); });
  it.each(['STALE', 'BAD', 'COMM_ERROR', 'DISABLED'] as const)('keeps %s as a null gap', quality => {
    expect(plotValue(response, { ...response.points[0], quality, value_numeric: 999 })).toBeNull();
  });
  it('keeps GOOD-but-invalid/mixed buckets and absent numeric values as gaps', () => {
    expect(plotValue(response, { ...response.points[0], has_invalid: true })).toBeNull();
    expect(plotValue(response, { ...response.points[0], value_numeric: null })).toBeNull();
    expect(plotValue({ ...response, tag: { ...response.tag, data_type: 'bool' } }, { ...response.points[0], value_boolean: null })).toBeNull();
  });
  it('has accessible guidance and resets zoom without fetching new history', async () => {
    render(<HistoricalChart history={response} />);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/Invalid values remain gaps/);
    await userEvent.click(screen.getByRole('button', { name: 'Reset zoom' }));
    expect(chart.dispatchAction).toHaveBeenCalledWith({ type: 'dataZoom', start: 0, end: 100 });
    expect(historyApi.getHistory).not.toHaveBeenCalled();
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ tooltip: expect.objectContaining({ confine: true }), xAxis: expect.objectContaining({ splitNumber: 3 }) }));
  });
  function tooltip(data = response, dataIndex = 0): HTMLElement {
    const formatter = historyTooltip([data], 320).formatter;
    if (typeof formatter !== 'function') throw new Error('Missing formatter');
    return formatter([{ seriesIndex: 0, dataIndex } as CallbackDataParams], '', () => {}) as HTMLElement;
  }
  it.each([true, false])('keeps touch results readable without delaying mouse tooltips (coarse=%s)', coarse => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: coarse })));
    const options = historyTooltip([response], 390);
    expect(options).toMatchObject({ hideDelay: coarse ? 8000 : 100, transitionDuration: 0 });
    expect(options.triggerOn).toBe(coarse ? 'click' : undefined);
    if (coarse && typeof options.position === 'function') {
      for (const y of [80, 260]) {
        const point = options.position([180, y], [], document.createElement('div'), null, { viewSize: [360, 340], contentSize: [320, 160] });
        if (!Array.isArray(point)) throw new Error('Expected bounded tooltip coordinates');
        const [left, top] = point.map(Number);
        expect(left).toBeGreaterThanOrEqual(0);
        expect(left + 320).toBeLessThanOrEqual(360);
        expect(top).toBeGreaterThanOrEqual(0);
        expect(top + 160).toBeLessThanOrEqual(340);
        expect(y < top || y > top + 160).toBe(true);
      }
    }
    expect(window.matchMedia).toHaveBeenCalledWith('(pointer: coarse)');
  });
  it('shows timestamp, exact value, unit and quality using safe text nodes', () => {
    const name = '<img src=x onerror=alert(1)>' + 'LongName'.repeat(40);
    const result = tooltip({ ...response, tag: { ...response.tag, name }, points: [{ ...response.points[0], value_numeric_exact: '9007199254740993' }] });
    expect(result.textContent).toContain(name);
    expect(result.textContent).toContain('Value: 9007199254740993 unit');
    expect(result.textContent).toContain('Quality: GOOD');
    expect(result.textContent).toContain(new Date(response.points[0].recorded_at).toLocaleString());
    expect(result.firstElementChild?.children[0].textContent).toBe(new Date(response.points[0].recorded_at).toLocaleString());
    expect(result.firstElementChild?.children[1].textContent).toBe('Value: 9007199254740993 unit');
    expect(result.firstElementChild?.children[2].textContent).toBe('Quality: GOOD');
    expect(result.querySelector('img')).toBeNull();
    expect(result.style.maxWidth).toBe('272px');
    expect(result.style.overflowWrap).toBe('anywhere');
  });
  it('does not display a retained numeric value in an invalid tooltip', () => {
    const result = tooltip({ ...response, downsampled: true, points: [{ ...response.points[0], quality: 'COMM_ERROR', has_invalid: true }] });
    expect(result.textContent).toContain('No valid plotted value');
    expect(result.textContent).toContain('COMM_ERROR');
    expect(result.textContent).toContain('contains invalid samples');
    expect(result.textContent).toContain('Bucket:');
    expect(result.textContent).not.toContain('Value: 12');
  });
  it('labels boolean OFF accurately in the tooltip', () => {
    expect(tooltip({ ...response, tag: { ...response.tag, data_type: 'bool' }, points: [{ ...response.points[0], value_boolean: false }] }).textContent).toContain('OFF / false');
  });
});

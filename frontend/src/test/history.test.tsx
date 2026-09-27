import { render } from './render';
import { useState } from 'react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as historyApi from '../api/history';
import HistorySettings from '../components/HistorySettings';
import HistoricalChart from '../components/HistoricalChart';
import TagHistory from '../components/TagHistory';
import type { HistoryResponse } from '../types/history';
import type { TagInput } from '../types/configuration';

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }));
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
    finish(response);
    expect(await screen.findByRole('img')).toHaveAccessibleName('Test numeric line history chart');
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ series: [expect.objectContaining({ type: 'line', step: false, connectNulls: false })] }));
  });
  it('renders explicit empty and API error states with retry', async () => {
    const get = vi.spyOn(historyApi, 'getHistory').mockResolvedValue({ ...response, count: 0, points: [] });
    const user = userEvent.setup(); render(<TagHistory tagId={1} />);
    expect(await screen.findByText(/No history in this range/)).toBeInTheDocument();
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
    await user.click(screen.getByRole('combobox', { name: 'Time range' }));
    await user.click(screen.getByRole('option', { name: '7 days' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const [, from, to] = get.mock.calls[1];
    expect(new Date(to).getTime() - new Date(from).getTime()).toBe(7 * 86400000);
    await user.click(screen.getByRole('combobox', { name: 'Time range' }));
    await user.click(screen.getByRole('option', { name: 'Custom' }));
    await user.click(screen.getByRole('button', { name: 'Apply / Refresh' }));
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
  });
});

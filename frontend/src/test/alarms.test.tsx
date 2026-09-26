import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AlarmEditor from '../components/AlarmEditor';
import AlarmIndicator from '../components/AlarmIndicator';
import AlarmsPage from '../pages/AlarmsPage';
import { alarmsApi } from '../api/alarms';
import { tagsApi } from '../api/configuration';
import { liveStore, LiveStore } from '../websocket/liveStore';
import { parseLiveEvent } from '../types/telemetry';
import type { Tag } from '../types/configuration';
import type { AlarmRule, AlarmEvent } from '../types/alarms';
const tag: Tag = { id: 1, name: 'Reading', key: 'reading', device_id: 1, register_type: 'input_register', address: 0, data_type: 'uint16', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: null, poll_interval_ms: 1000, writable: false, enabled: true, history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null, min_value: null, max_value: null, description: null, created_at: '', updated_at: '' };
const relay: Tag = { ...tag, id: 2, key: 'relay', name: 'Relay', data_type: 'bool', register_type: 'coil', writable: true };

const rule: AlarmRule = { id: 1, name: 'High reading', description: null, enabled: true, tag_id: 1, operator: '>', value: '30', severity: 'CRITICAL', for_duration_ms: 2000, hysteresis: '2', notification_enabled: true, created_at: '', updated_at: '' };
const event: AlarmEvent = { id: 1, rule_id: 1, tag_id: 1, name: 'High reading', tag_name: 'Reading', unit: 'C', condition: '> 30 C', severity: 'CRITICAL', state: 'ACTIVE', value_numeric: '31', value_boolean: null, activated_at: '2026-09-01T00:00:00Z', acknowledged_at: null, cleared_at: null, clear_reason: null, revision: 1 };
function mocks() {
  vi.spyOn(liveStore, 'retain').mockReturnValue(() => {});
  vi.spyOn(tagsApi, 'all').mockResolvedValue([tag, relay]);
  vi.spyOn(alarmsApi, 'destination').mockResolvedValue({ chat_id: '' });
  vi.spyOn(alarmsApi, 'deliveries').mockResolvedValue([]);
  vi.spyOn(alarmsApi, 'rules').mockResolvedValue([rule]);
  vi.spyOn(alarmsApi, 'events').mockResolvedValue([event]);
}
describe('alarm UI', () => {
  it('edits typed numeric threshold, delay, hysteresis and notification flag', async () => {
    const save = vi.spyOn(alarmsApi, 'edit').mockResolvedValue(rule); const user = userEvent.setup();
    render(<AlarmEditor rule={rule} tags={[tag, relay]} onClose={() => {}} onSaved={() => {}} />);
    await user.clear(screen.getByLabelText('Comparison value')); await user.type(screen.getByLabelText('Comparison value'), '35');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(1, expect.objectContaining({ value: '35', hysteresis: '2', for_duration_ms: 2000, notification_enabled: true })));
  });
  it('boolean rules have no numeric hysteresis and show typed values', () => {
    render(<AlarmEditor rule={{ ...rule, tag_id: 2, operator: '==', value: true, hysteresis: '0' }} tags={[tag, relay]} onClose={() => {}} onSaved={() => {}} />);
    expect(screen.queryByLabelText('Hysteresis')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Comparison value' })).toHaveTextContent('ON / true');
  });
  it('shows server validation without closing', async () => {
    vi.spyOn(alarmsApi, 'edit').mockRejectedValue(new Error('Invalid threshold'));
    render(<AlarmEditor rule={rule} tags={[tag]} onClose={() => {}} onSaved={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Invalid threshold')).toBeInTheDocument();
  });
  it('acknowledges an ACTIVE event and filters historical states', async () => {
    mocks(); const ack = vi.spyOn(alarmsApi, 'acknowledge').mockResolvedValue({ ...event, state: 'ACKNOWLEDGED' });
    render(<AlarmsPage />);
    expect(await screen.findByText('ACTIVE')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(ack).toHaveBeenCalledWith(1));
    await userEvent.click(screen.getByRole('tab', { name: 'History' }));
    await userEvent.click(screen.getByLabelText('State filter')); await userEvent.click(screen.getByRole('option', { name: 'CLEARED' }));
    await waitFor(() => expect(alarmsApi.events).toHaveBeenLastCalledWith(expect.stringContaining('state=CLEARED')));
  });
  it('toggles enabled state and shows delivery failure separately', async () => {
    mocks(); const edit = vi.spyOn(alarmsApi, 'edit').mockResolvedValue({ ...rule, enabled: false });
    vi.spyOn(alarmsApi, 'deliveries').mockResolvedValue([{ id: 4, event_id: 1, kind: 'ACTIVATED', status: 'FAILED', attempt_count: 1, created_at: event.activated_at, completed_at: null, error: 'Telegram timed out' }]);
    render(<AlarmsPage />); await screen.findByText('ACTIVE');
    await userEvent.click(screen.getByRole('tab', { name: 'Alarm rules' })); await userEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(edit).toHaveBeenCalledWith(1, { enabled: false }));
    await userEvent.click(screen.getByRole('tab', { name: 'Telegram' }));
    expect(await screen.findByText(/Telegram timed out/)).toBeInTheDocument();
  });
  it('shows active and critical counts using text', async () => {
    mocks(); vi.spyOn(alarmsApi, 'summary').mockResolvedValue({ active: 3, critical: 1 });
    render(<MemoryRouter><AlarmIndicator /></MemoryRouter>);
    expect(await screen.findByText('Alarms: 3 / 1 CRITICAL')).toBeInTheDocument();
  });
  it('validates alarm payload and resnapshots on existing socket events/reconnect', async () => {
    expect(parseLiveEvent(JSON.stringify({ type: 'alarm_event', data: event })).type).toBe('alarm_event');
    expect(() => parseLiveEvent(JSON.stringify({ type: 'alarm_event', data: { id: 1 } }))).toThrow();
    const socket = { onmessage: null as ((e: {data: string}) => void) | null, close: vi.fn() };
    const store = new LiveStore(vi.fn().mockResolvedValue([]), () => socket as unknown as WebSocket);
    const callback = vi.fn(); const unsubscribe = store.subscribeAlarms(callback); const release = store.retain();
    for (let i = 0; i < 10; i++) await Promise.resolve();
    socket.onmessage?.({ data: JSON.stringify({ type: 'alarm_event', data: event }) });
    socket.onmessage?.({ data: JSON.stringify({ type: 'resync_required' }) });
    expect(callback).toHaveBeenCalledTimes(2); unsubscribe(); release();
  });
});

import { render, testAuth } from './render';
import { act, screen, waitFor, within } from '@testing-library/react';
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
import { AuthContext } from '../auth/context';
const tag: Tag = { id: 1, name: 'Reading', key: 'reading', device_id: 1, register_type: 'input_register', address: 0, data_type: 'uint16', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: null, poll_interval_ms: 1000, writable: false, enabled: true, history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null, min_value: null, max_value: null, description: null, created_at: '', updated_at: '' };
const relay: Tag = { ...tag, id: 2, key: 'relay', name: 'Relay', data_type: 'bool', register_type: 'coil', writable: true };

const rule: AlarmRule = { id: 1, name: 'High reading', description: null, enabled: true, tag_id: 1, operator: '>', value: '30', severity: 'CRITICAL', for_duration_ms: 2000, hysteresis: '2', notification_enabled: true, created_at: '', updated_at: '' };
const event: AlarmEvent = { id: 1, rule_id: 1, tag_id: 1, name: 'High reading', tag_name: 'Reading', unit: 'C', condition: '> 30 C', severity: 'CRITICAL', state: 'ACTIVE', value_numeric: '31', value_boolean: null, activated_at: '2026-09-01T00:00:00Z', acknowledged_at: null, cleared_at: null, clear_reason: null, revision: 1 };
function mocks() {
  viewport(1440);
  vi.spyOn(liveStore, 'retain').mockReturnValue(() => {});
  vi.spyOn(tagsApi, 'all').mockResolvedValue([tag, relay]);
  vi.spyOn(alarmsApi, 'destination').mockResolvedValue({ chat_id: '' });
  vi.spyOn(alarmsApi, 'deliveries').mockResolvedValue([]);
  vi.spyOn(alarmsApi, 'rules').mockResolvedValue([rule]);
  vi.spyOn(alarmsApi, 'events').mockResolvedValue([event]);
}
function viewport(width: number) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: query.includes('min-width') ? width >= Number(query.match(/min-width:\s*([\d.]+)/)?.[1] ?? Infinity) : width <= Number(query.match(/max-width:\s*([\d.]+)/)?.[1] ?? 0),
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
}
const acknowledged: AlarmEvent = { ...event, id: 2, name: 'Reviewed alarm', state: 'ACKNOWLEDGED', severity: 'WARNING', acknowledged_at: event.activated_at, acknowledged_by_username: 'operator' };
const cleared: AlarmEvent = { ...event, id: 3, name: 'Closed alarm', state: 'CLEARED', severity: 'INFO', cleared_at: event.activated_at, clear_reason: 'Condition returned below the reset threshold' };
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
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge High reading' }));
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

describe('responsive alarm events', () => {
  it('prioritizes unacknowledged alarms and severity within the loaded page', async () => {
    mocks();
    vi.spyOn(alarmsApi, 'events').mockResolvedValue([acknowledged, { ...event, id: 4, name: 'Warning alarm', severity: 'WARNING' }, event]);
    render(<AlarmsPage />);
    const cards = await screen.findAllByRole('article');
    expect(cards.map(card => within(card).getAllByRole('heading', { level: 3 })[0].textContent)).toEqual(['High reading', 'Warning alarm', 'Reviewed alarm']);
    expect(within(cards[0]).getByText('CRITICAL')).toBeInTheDocument();
    expect(within(cards[0]).getAllByText('Not acknowledged')[0]).toBeVisible();
    expect(within(cards[2]).getByText('Acknowledged; not yet cleared')).toBeInTheDocument();
  });

  it('separates open events from cleared history and preserves the history query', async () => {
    mocks(); vi.spyOn(alarmsApi, 'events').mockImplementation(async query => query?.includes('active=true') ? [event] : [cleared, acknowledged, event]);
    render(<AlarmsPage />); await screen.findByRole('article');
    await userEvent.click(screen.getByRole('tab', { name: 'History' }));
    const closed = await screen.findByRole('region', { name: 'Cleared alarms' });
    expect(within(closed).getByText('CLEARED')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Open alarms' })).toBeInTheDocument();
    expect(screen.getAllByRole('article').map(card => within(card).getAllByRole('heading', { level: 3 })[0].textContent)).toEqual(['High reading', 'Reviewed alarm', 'Closed alarm']);
    expect(alarmsApi.events).toHaveBeenLastCalledWith('offset=0');
    expect(within(closed).queryByRole('button', { name: /Acknowledge/ })).not.toBeInTheDocument();
  });

  it.each([360, 390, 768, 1024, 1440])('renders accessible cards at %ipx with filters appropriate to the breakpoint', async width => {
    mocks(); viewport(width); render(<AlarmsPage />);
    const card = await screen.findByRole('article', { name: event.name });
    expect(within(card).getByText('31 C')).toBeInTheDocument();
    expect(within(card).getByText('Value at activation')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: `Acknowledge ${event.name}` })).toBeInTheDocument();
    if (width < 900) {
      const filters = screen.getByRole('button', { name: 'Filters' });
      expect(filters).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(filters);
      expect(filters).toHaveAttribute('aria-expanded', 'true');
    }
    expect(screen.getByRole('textbox', { name: 'Search alarms' })).toBeVisible();
  });

  it('reveals full long messages, acknowledgement attribution and technical details', async () => {
    mocks(); const longName = 'LongAlarmName'.repeat(25); const reason = 'Full backend clear reason\n' + 'long_reason_'.repeat(50);
    vi.spyOn(alarmsApi, 'events').mockResolvedValue([{ ...cleared, name: longName, clear_reason: reason, acknowledged_at: event.activated_at, acknowledged_by_username: 'reviewer' }]);
    render(<AlarmsPage />); await userEvent.click(screen.getByRole('tab', { name: 'History' }));
    const card = await screen.findByRole('article', { name: longName });
    const details = within(card).getByRole('button', { name: `Details for ${longName}` });
    expect(details).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(details);
    expect(details).toHaveAttribute('aria-expanded', 'true');
    expect(within(card).getByText('reviewer')).toBeVisible();
    expect(within(card).getByText(/Full backend clear reason/).textContent).toBe(reason);
    expect(within(card).getByText('Event ID')).toBeVisible();
  });

  it('distinguishes boolean OFF and unavailable values without fabricating a reading', async () => {
    mocks(); vi.spyOn(alarmsApi, 'events').mockResolvedValue([{ ...event, value_numeric: null, value_boolean: false }, { ...event, id: 4, name: 'Missing value', value_numeric: null }]);
    render(<AlarmsPage />);
    expect(await screen.findByText('OFF')).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('provides healthy active-empty, history-empty and filtered-empty states', async () => {
    mocks(); vi.spyOn(alarmsApi, 'events').mockResolvedValue([]);
    render(<AlarmsPage />);
    expect(await screen.findByText('No active alarms. No open alarm events are reported.')).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Search alarms' }), 'missing');
    expect(screen.getByText(/No alarms match these filters/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await userEvent.click(screen.getByRole('tab', { name: 'History' }));
    expect(await screen.findByText('No alarm history yet.')).toBeInTheDocument();
  });

  it('does not show a healthy empty state during loading or API failure', async () => {
    mocks(); let reject!: (reason: Error) => void;
    vi.spyOn(alarmsApi, 'events').mockReturnValue(new Promise((_, no) => { reject = no; }));
    render(<AlarmsPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading alarms');
    expect(screen.queryByText(/No active alarms/)).not.toBeInTheDocument();
    await act(async () => reject(new Error('Cannot load alarms')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot load alarms');
    expect(screen.queryByText(/No active alarms/)).not.toBeInTheDocument();
  });

  it('searches loaded names and Tags, shows active filters and resets without a new query', async () => {
    mocks(); vi.spyOn(alarmsApi, 'events').mockResolvedValue([event, acknowledged]);
    render(<AlarmsPage />); await screen.findAllByRole('article');
    const user = userEvent.setup(); const count = vi.mocked(alarmsApi.events).mock.calls.length;
    await user.type(screen.getByRole('textbox', { name: 'Search alarms' }), 'reviewed');
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getByText('Search: reviewed')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect(alarmsApi.events).toHaveBeenCalledTimes(count);
  });

  it('keeps server severity, state and Tag filters, with a single reset', async () => {
    mocks(); render(<AlarmsPage />); await screen.findByRole('article');
    const user = userEvent.setup();
    for (const [label, option] of [['Severity filter', 'CRITICAL'], ['State filter', 'ACKNOWLEDGED'], ['Tag filter', 'Reading']]) {
      await user.click(screen.getByRole('combobox', { name: label })); await user.click(screen.getByRole('option', { name: option }));
    }
    await waitFor(() => expect(alarmsApi.events).toHaveBeenLastCalledWith('offset=0&active=true&severity=CRITICAL&state=ACKNOWLEDGED&tag_id=1'));
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => expect(alarmsApi.events).toHaveBeenLastCalledWith('offset=0&active=true'));
  });

  it.each(['VIEWER', 'OPERATOR'] as const)('preserves %s permissions', async role => {
    mocks(); const permissions = role === 'VIEWER' ? ['read'] : ['read', 'acknowledge', 'command'];
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role, permissions } }}><AlarmsPage /></AuthContext.Provider>);
    await screen.findByRole('article');
    expect(!!screen.queryByRole('button', { name: `Acknowledge ${event.name}` })).toBe(role === 'OPERATOR');
    expect(screen.queryByRole('tab', { name: 'Telegram' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Alarm rules' }));
    expect(screen.queryByRole('button', { name: /New alarm rule|Edit|Disable|Delete/ })).not.toBeInTheDocument();
    expect(alarmsApi.destination).not.toHaveBeenCalled();
  });

  it('keeps Cloud acknowledgement queued until the server confirms it and moves focus safely', async () => {
    mocks(); const ack = vi.spyOn(alarmsApi, 'acknowledge').mockResolvedValue(event);
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, application_mode: 'cloud' } }}><AlarmsPage /></AuthContext.Provider>);
    await userEvent.click(await screen.findByRole('button', { name: `Acknowledge ${event.name}` }));
    expect(ack).toHaveBeenCalledWith(event.id);
    expect(await screen.findByText('Acknowledgement queued for Edge; waiting for confirmation')).toBeInTheDocument();
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Active alarms' })).toHaveFocus();
  });

  it('displays acknowledge failure without changing the event state', async () => {
    mocks(); vi.spyOn(alarmsApi, 'acknowledge').mockRejectedValue(new Error('Acknowledgement rejected'));
    render(<AlarmsPage />);
    await userEvent.click(await screen.findByRole('button', { name: `Acknowledge ${event.name}` }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Acknowledgement rejected');
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
  });

  it('refreshes all cards through the existing shared alarm subscription', async () => {
    mocks(); let notify!: () => void;
    vi.spyOn(liveStore, 'subscribeAlarms').mockImplementation(callback => { notify = callback; return () => {}; });
    render(<AlarmsPage />); await screen.findByText('ACTIVE');
    vi.mocked(alarmsApi.events).mockResolvedValue([acknowledged]);
    act(() => notify());
    expect(await screen.findByText('ACKNOWLEDGED')).toBeInTheDocument();
    expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument();
    expect(liveStore.retain).toHaveBeenCalledTimes(1);
    expect(liveStore.subscribeAlarms).toHaveBeenCalledTimes(1);
  });
});

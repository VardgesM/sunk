import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { ReactElement } from 'react';
import { AuthContext, type AuthUser } from '../auth/context';
import { testAuth } from './render';
import TagsPage from '../pages/TagsPage';
import DevicesPage from '../pages/DevicesPage';
import ConnectionsPage from '../pages/ConnectionsPage';
import LocationsPage from '../pages/LocationsPage';
import CommandsPage from '../pages/CommandsPage';
import { connectionsApi, devicesApi, locationsApi, tagsApi } from '../api/configuration';
import * as commandsApi from '../api/commands';
import * as client from '../api/client';
import * as runtime from '../api/runtime';
import { liveStore } from '../websocket/liveStore';
import type { Connection, Device, Location, Tag } from '../types/configuration';
import type { Command } from '../types/commands';
import type { CurrentValue } from '../types/telemetry';

const time = '2026-10-01T10:00:00Z';
const timestamps = { created_at: time, updated_at: time };
const longName = `Measurement ${'long_unbroken_name_'.repeat(10)}`;
const connection: Connection = { id: 1, name: 'Configured connection', protocol: 'modbus_tcp', enabled: true, host: 'example.invalid', port: 502,
  timeout_ms: 1000, serial_port: null, baud_rate: null, parity: null, data_bits: null, stop_bits: null, ...timestamps };
const location: Location = { id: 1, name: 'Configured location', description: 'Operator supplied description', parent_id: null, sort_order: 0, ...timestamps };
const device: Device = { id: 1, name: 'Configured device', connection_id: 1, connection_protocol: 'modbus_tcp', location_id: 1, slave_id: 7, enabled: true, description: null, ...timestamps };
const tag: Tag = { id: 1, name: longName, key: 'measurement', device_id: 1, register_type: 'holding_register', address: 100, data_type: 'float32',
  byte_order: 'big', word_order: 'little', scale: 1, offset: 0, unit: '%', poll_interval_ms: 5000, writable: false, enabled: true,
  history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null,
  min_value: null, max_value: null, description: null, ...timestamps };
const current: CurrentValue = { tag_id: 1, key: 'measurement', name: longName, unit: '%', device_id: 1, enabled: true, effective_enabled: true, data_type: 'float32',
  value_numeric: 84.6, value_numeric_exact: '84.6', value_boolean: null, value_text: null, quality: 'GOOD', source: 'modbus_tcp', source_timestamp: time,
  updated_at: time, error: null, raw_value: null, revision: 1 };
const command: Command = { id: 2, request_id: 'request-correlation', tag_id: 1, tag_name: longName, device_id: 1, device_name: device.name,
  requested_value: true, previous_value: false, verified_value: false, status: 'QUEUED', source: 'manual', telemetry_mode: 'modbus', attempt_count: 0,
  revision: 1, created_at: time, expires_at: time, started_at: null, completed_at: null, error_message: null, requested_by_username: 'operator' };

function viewport(width: number) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: width >= Number(query.match(/min-width:\s*(\d+)/)?.[1] ?? Infinity),
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
}
function show(page: ReactElement, role: AuthUser['role'] = 'ADMIN', entry = '/') {
  const permissions = role === 'ADMIN' ? testAuth.user!.permissions : role === 'OPERATOR' ? ['read', 'command', 'acknowledge'] : ['read'];
  return render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role, permissions } }}><MemoryRouter initialEntries={[entry]}>{page}</MemoryRouter></AuthContext.Provider>);
}
beforeEach(() => {
  viewport(390);
  vi.spyOn(connectionsApi, 'list').mockResolvedValue([connection]); vi.spyOn(connectionsApi, 'all').mockResolvedValue([connection]);
  vi.spyOn(devicesApi, 'list').mockResolvedValue([device]); vi.spyOn(devicesApi, 'all').mockResolvedValue([device]);
  vi.spyOn(locationsApi, 'list').mockResolvedValue([location]); vi.spyOn(locationsApi, 'all').mockResolvedValue([location]);
  vi.spyOn(tagsApi, 'list').mockResolvedValue([tag]);
  vi.spyOn(commandsApi, 'getCommands').mockResolvedValue([command]);
  vi.spyOn(liveStore, 'retain').mockReturnValue(() => {});
  vi.spyOn(liveStore, 'getValue').mockReturnValue(current);
  vi.spyOn(client, 'request').mockResolvedValue({ state: 'ONLINE', last_success: time, last_error: null });
});

const pages = [
  { name: 'Tags', Page: TagsPage, title: longName }, { name: 'Devices', Page: DevicesPage, title: device.name },
  { name: 'Connections', Page: ConnectionsPage, title: connection.name }, { name: 'Locations', Page: LocationsPage, title: location.name },
  { name: 'Commands', Page: CommandsPage, title: longName },
];
describe('responsive data views', () => {
  it.each(pages)('keeps the $name desktop table and its content', async ({ name, Page, title }) => {
    viewport(1440); show(<Page />);
    const table = await screen.findByRole('table', { name });
    expect(within(table).getByText(title)).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(screen.getByLabelText(`${name} table scroll area`)).toHaveAttribute('tabindex', '0');
  });
  it.each(pages)('renders $name as named mobile cards with no duplicate table', async ({ name, Page, title }) => {
    show(<Page />);
    expect(await screen.findByRole('article', { name: title })).toBeInTheDocument();
    expect(screen.getByRole('list', { name })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it.each([360, 768, 1024])('uses the shared md breakpoint at %dpx', async width => {
    viewport(width); show(<TagsPage />);
    expect(await screen.findByRole(width < 900 ? 'article' : 'table')).toBeInTheDocument();
    expect(screen.queryByRole(width < 900 ? 'table' : 'article')).not.toBeInTheDocument();
  });
  it('shows live value, full long name, quality and context; exposes technical details by touch', async () => {
    show(<TagsPage />);
    const card = await screen.findByRole('article', { name: longName });
    expect(within(card).getByRole('heading', { name: longName })).toHaveTextContent(longName);
    for (const text of ['84.6', 'GOOD', device.name, 'Last successful update']) expect(within(card).getByText(text, { exact: false })).toBeVisible();
    expect(within(card).getByText('Address (zero-based)')).not.toBeVisible();
    await userEvent.click(within(card).getByRole('button', { name: 'Details' }));
    expect(within(card).getByText('Address (zero-based)')).toBeVisible();
    expect(within(card).getByText('modbus_tcp')).toBeVisible();
    expect(within(card).getByRole('link', { name: 'Tag details' })).toHaveAttribute('href', '/tags/1');
  });
  it('updates the same mobile tag card from the shared live subscription', async () => {
    const callbacks = new Set<() => void>();
    vi.spyOn(liveStore, 'subscribe').mockImplementation((_id, callback) => { callbacks.add(callback); return () => { callbacks.delete(callback); }; });
    show(<TagsPage />);
    const card = await screen.findByRole('article');
    vi.mocked(liveStore.getValue).mockReturnValue({ ...current, value_numeric: 0, value_numeric_exact: '0', quality: 'COMM_ERROR', error: 'Timed out', revision: 2 });
    act(() => callbacks.forEach(callback => callback()));
    expect(within(card).getByText('COMM_ERROR')).toBeVisible();
    expect(within(card).getByText('0')).toBeVisible();
    await userEvent.click(within(card).getByRole('button', { name: 'Details' }));
    expect(within(card).getByText('Timed out')).toBeVisible();
    expect(tagsApi.list).toHaveBeenCalledTimes(1);
    expect(liveStore.retain).toHaveBeenCalledTimes(1);
  });
  it('does not hide boolean false as an empty tag value', async () => {
    vi.mocked(tagsApi.list).mockResolvedValue([{ ...tag, data_type: 'bool', register_type: 'coil', unit: null }]);
    vi.mocked(liveStore.getValue).mockReturnValue({ ...current, value_numeric: null, value_boolean: false });
    show(<TagsPage />);
    expect(await screen.findByText('False')).toBeVisible();
  });
  it('retains edit/save and confirmation/dependency errors in the mobile menu', async () => {
    const update = vi.spyOn(locationsApi, 'update').mockResolvedValue(location);
    const remove = vi.spyOn(locationsApi, 'remove').mockRejectedValue(new Error('Dependent configuration exists'));
    const user = userEvent.setup(); show(<LocationsPage />);
    await user.click(await screen.findByRole('button', { name: `Actions for ${location.name}` }));
    await user.click(screen.getByRole('menuitem', { name: 'Edit' }));
    const edit = screen.getByRole('dialog');
    await user.clear(within(edit).getByLabelText(/^Name/)); await user.type(within(edit).getByLabelText(/^Name/), 'Renamed');
    await user.click(within(edit).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ name: 'Renamed' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: `Actions for ${location.name}` }));
    await user.click(screen.getByRole('menuitem', { name: 'Delete' }));
    expect(remove).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Dependent configuration exists')).toBeVisible();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(await screen.findByRole('article', { name: location.name })).toBeVisible();
  });
  it('supports keyboard access, Escape and focus return for the action menu', async () => {
    show(<LocationsPage />);
    const button = await screen.findByRole('button', { name: `Actions for ${location.name}` });
    button.focus(); await userEvent.keyboard('{Enter}');
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(button).toHaveFocus();
  });
  it.each(['VIEWER', 'OPERATOR'] as const)('keeps configuration actions unavailable for %s on mobile', async role => {
    show(<ConnectionsPage />, role);
    const card = await screen.findByRole('article');
    expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /Actions/ })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Details' }));
    expect(screen.queryByRole('button', { name: /Test / })).not.toBeInTheDocument();
  });
  it('keeps transport test and auto-detection actions inside accessible details', async () => {
    vi.mocked(connectionsApi.list).mockResolvedValue([{ ...connection, protocol: 'modbus_rtu', serial_port_mode: 'auto' }]);
    vi.mocked(client.request).mockResolvedValue({ state: 'ERROR', detected_port: 'COM7', detection_status: 'AMBIGUOUS', detection_error: 'Multiple adapters found', last_error: 'Port unavailable', last_success: null });
    const redetect = vi.spyOn(runtime, 'redetectConnection').mockResolvedValue({ request_id: 'test', state: 'PENDING' });
    const test = vi.spyOn(runtime, 'testConnection').mockResolvedValue({ test_id: 'test', state: 'SUCCEEDED', success: true, message: 'Transport only; slave not verified', latency_ms: 1 });
    show(<ConnectionsPage />);
    expect(await screen.findByText('ERROR')).toBeVisible();
    expect(screen.getByText('Port unavailable')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Detection details' }));
    expect(screen.getByText('Multiple adapters found')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Re-detect' }));
    expect(redetect).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole('button', { name: 'Details' }));
    await userEvent.click(screen.getByRole('button', { name: `Test ${connection.name}` }));
    expect(test).toHaveBeenCalledWith(1, expect.any(AbortSignal));
    expect(await screen.findByText(/slave not verified/)).toBeVisible();
  });
  it('collapses mobile tag filters, displays applied values and resets the existing query', async () => {
    const user = userEvent.setup(); show(<TagsPage />);
    await screen.findByRole('article');
    expect(screen.getByLabelText('Search name or key')).not.toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await user.type(screen.getByLabelText('Search name or key'), 'humidity');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(tagsApi.list).toHaveBeenLastCalledWith(expect.stringContaining('search=humidity'), expect.any(AbortSignal)));
    expect(screen.getByText('Search: humidity')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Filters (1)' })).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => expect(tagsApi.list).toHaveBeenLastCalledWith('&limit=50&offset=0', expect.any(AbortSignal)));
    expect(screen.queryByText('Search: humidity')).not.toBeInTheDocument();
  });
  it('shows loading, empty, filtered-empty and error/retry states', async () => {
    vi.mocked(tagsApi.list).mockResolvedValue([]); show(<TagsPage />);
    expect(screen.getByRole('progressbar', { name: 'Loading Tags' })).toBeInTheDocument();
    expect(await screen.findByText('No tags configured.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Filters' }));
    await userEvent.type(screen.getByLabelText('Search name or key'), 'missing');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('No results match these filters.')).toBeVisible();
    vi.mocked(tagsApi.list).mockRejectedValueOnce(new Error('Unavailable'));
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(await screen.findByText('Unavailable')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No tags configured.')).toBeVisible();
  });
});

describe('responsive command history', () => {
  it('shows a loading error without claiming the history is empty', async () => {
    vi.mocked(commandsApi.getCommands).mockRejectedValue(new Error('Command history unavailable'));
    show(<CommandsPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading commands');
    expect(await screen.findByText('Command history unavailable')).toBeVisible();
    expect(screen.queryByText('No commands yet.')).not.toBeInTheDocument();
  });
  it('distinguishes empty command history from an empty filtered result', async () => {
    vi.mocked(commandsApi.getCommands).mockResolvedValue([]);
    const page = show(<CommandsPage />);
    expect(await screen.findByText('No commands yet.')).toBeVisible();
    page.unmount(); show(<CommandsPage />, 'ADMIN', '/commands?command_id=123');
    expect(await screen.findByText('No commands match these filters.')).toBeVisible();
  });
  it('separates requested and read-back values and exposes lifecycle details', async () => {
    show(<CommandsPage />);
    const card = await screen.findByRole('article');
    expect(within(card).getByText('Requested: ON')).toBeVisible();
    expect(within(card).getAllByText('OFF')[0]).toBeVisible();
    expect(within(card).getByText('QUEUED')).toBeVisible();
    expect(within(card).getByText('request-correlation')).not.toBeVisible();
    await userEvent.click(within(card).getByRole('button', { name: 'Details' }));
    expect(within(card).getByText('request-correlation')).toBeVisible();
    expect(within(card).getByText('operator')).toBeVisible();
  });
  it.each(['ADMIN', 'OPERATOR'] as const)('preserves queued cancellation for %s using the existing API', async role => {
    const cancel = vi.spyOn(commandsApi, 'cancelCommand').mockResolvedValue({ ...command, status: 'CANCELLED' });
    show(<CommandsPage />, role);
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for command 2' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Cancel command' }));
    expect(cancel).toHaveBeenCalledWith(2);
    await waitFor(() => expect(commandsApi.getCommands).toHaveBeenCalledTimes(2));
  });
  it('does not offer cancellation to VIEWER', async () => {
    show(<CommandsPage />, 'VIEWER'); await screen.findByRole('article');
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument();
  });
  it('shows numeric zero, full failure details and no cancellation for finished commands', async () => {
    const error = `Read-back mismatch: ${'long_error_'.repeat(30)}`;
    vi.mocked(commandsApi.getCommands).mockResolvedValue([{ ...command, requested_value: '0', verified_value: '1', status: 'FAILED', error_message: error, completed_at: time }]);
    show(<CommandsPage />);
    expect(await screen.findByText('Requested: 0')).toBeVisible();
    expect(screen.getByText(error)).toBeVisible();
    expect(screen.getByText('Completed')).toBeVisible();
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument();
  });
  it('preserves linked command filtering, reset and refresh', async () => {
    show(<CommandsPage />, 'ADMIN', '/commands?command_id=2');
    await waitFor(() => expect(commandsApi.getCommands).toHaveBeenCalledWith('command_id=2', expect.any(AbortSignal)));
    expect(screen.getByText('Command: 2')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Filters (1)' }));
    await userEvent.type(screen.getByLabelText('Device ID'), '7');
    await waitFor(() => expect(commandsApi.getCommands).toHaveBeenLastCalledWith('command_id=2&device_id=7', expect.any(AbortSignal)));
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => expect(commandsApi.getCommands).toHaveBeenLastCalledWith('', expect.any(AbortSignal)));
    const count = vi.mocked(commandsApi.getCommands).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(commandsApi.getCommands).toHaveBeenCalledTimes(count + 1));
  });
});

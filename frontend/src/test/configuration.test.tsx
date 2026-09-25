import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { liveStore } from '../websocket/liveStore';
import ConnectionsPage from '../pages/ConnectionsPage';
import DevicesPage from '../pages/DevicesPage';
import LocationsPage from '../pages/LocationsPage';
import TagsPage from '../pages/TagsPage';
import { connectionsApi, devicesApi, locationsApi, tagsApi } from '../api/configuration';
import { ApiError } from '../api/client';
import type { Connection, Device, Location, Tag } from '../types/configuration';

const timestamps = { created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-01T00:00:00+00:00' };
const connection: Connection = { id: 1, name: 'Test transport', protocol: 'modbus_tcp', enabled: true,
  host: 'test.local', port: 502, timeout_ms: 1000, serial_port: null, baud_rate: null,
  parity: null, stop_bits: null, data_bits: null, ...timestamps };
const device: Device = { id: 1, name: 'Test device', connection_id: 1, connection_protocol: 'modbus_tcp',
  location_id: null, slave_id: 1, enabled: true, description: null, ...timestamps };
const location: Location = { id: 1, name: 'Parent', parent_id: null, description: null, sort_order: 0, ...timestamps };
const tag: Tag = { id: 1, name: 'Test tag', key: 'test_tag', device_id: 1, register_type: 'holding_register',
  address: 0, data_type: 'float32', byte_order: 'big', word_order: 'big', scale: 1, offset: 0,
  unit: null, poll_interval_ms: 1000, writable: true, history_enabled: false, enabled: true,
  history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null,
  min_value: null, max_value: null, description: null, ...timestamps };

async function choose(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  await user.click(screen.getByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: option }));
}

describe('configuration management', () => {
  beforeEach(() => { vi.spyOn(liveStore, 'retain').mockReturnValue(() => {}); });
  it('switches TCP/RTU fields and persists typed serial configuration', async () => {
    vi.spyOn(connectionsApi, 'list').mockResolvedValue([]);
    const create = vi.spyOn(connectionsApi, 'create').mockResolvedValue(connection);
    const user = userEvent.setup(); render(<ConnectionsPage />);
    await screen.findByText('No matching connections.');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await user.type(screen.getByLabelText(/^Name/), 'Serial test');
    expect(screen.getByLabelText(/^Host/)).toBeInTheDocument();
    await choose(user, 'Protocol', 'modbus_rtu');
    expect(screen.queryByLabelText(/^Host/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Serial port/), 'operator-port');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      serial_port: 'operator-port', protocol: 'modbus_rtu', host: null, port: null, baud_rate: 9600,
    })));
    expect(await screen.findByText('Configuration saved')).toBeInTheDocument();
  });

  it('hides irrelevant encoding fields and prevents writable discrete inputs', async () => {
    vi.spyOn(devicesApi, 'all').mockResolvedValue([device]);
    vi.spyOn(tagsApi, 'list').mockResolvedValue([tag]);
    const update = vi.spyOn(tagsApi, 'update').mockResolvedValue(tag);
    const user = userEvent.setup(); render(<TagsPage />);
    await user.click(await screen.findByRole('button', { name: 'Edit Test tag' }));
    expect(screen.getByRole('combobox', { name: 'Word order' })).toBeInTheDocument();
    await choose(user, 'Register type', 'discrete_input');
    expect(screen.queryByRole('combobox', { name: 'Word order' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Byte order' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Writable' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Writable' })).not.toBeChecked();
    expect(screen.getByLabelText(/^Address \(zero-based\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ data_type: 'bool', writable: false })));
    expect(update.mock.calls[0][1]).not.toHaveProperty('id');
  });

  it('shows server errors and preserves entered values', async () => {
    vi.spyOn(devicesApi, 'all').mockResolvedValue([device]);
    vi.spyOn(tagsApi, 'list').mockResolvedValue([tag]);
    vi.spyOn(tagsApi, 'update').mockRejectedValue(new ApiError(409, 'Tag key already exists'));
    const user = userEvent.setup(); render(<TagsPage />);
    await user.click(await screen.findByRole('button', { name: 'Edit Test tag' }));
    await user.clear(screen.getByLabelText(/^Key/)); await user.type(screen.getByLabelText(/^Key/), 'duplicate');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Tag key already exists')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Key/)).toHaveValue('duplicate');
  });

  it('confirms deletion and displays dependency conflicts without removing the row', async () => {
    vi.spyOn(locationsApi, 'list').mockResolvedValue([location]);
    vi.spyOn(locationsApi, 'all').mockResolvedValue([location]);
    const remove = vi.spyOn(locationsApi, 'remove').mockRejectedValue(new ApiError(409, 'Cannot delete: dependent configuration exists'));
    const user = userEvent.setup(); render(<LocationsPage />);
    await user.click(await screen.findByRole('button', { name: 'Delete Parent' }));
    expect(remove).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Cannot delete: dependent configuration exists')).toBeInTheDocument();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(await screen.findByRole('button', { name: 'Delete Parent' })).toBeInTheDocument();
  });

  it('sends search and all tag filters to the API', async () => {
    vi.spyOn(devicesApi, 'all').mockResolvedValue([device]);
    const list = vi.spyOn(tagsApi, 'list').mockResolvedValue([]);
    const user = userEvent.setup(); render(<TagsPage />);
    await screen.findByText('No matching tags.');
    await user.type(screen.getByLabelText('Search name or key'), 'pressure');
    await choose(user, 'Device filter', 'Test device');
    await choose(user, 'Register filter', 'holding_register');
    await choose(user, 'Enabled filter', 'Disabled');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.stringContaining('search=pressure&device_id=1&register_type=holding_register&enabled=false'), expect.any(AbortSignal)));
  });

  it('allows connection and optional location selection and shows protocol', async () => {
    vi.spyOn(devicesApi, 'list').mockResolvedValue([device]);
    vi.spyOn(connectionsApi, 'all').mockResolvedValue([connection]);
    vi.spyOn(locationsApi, 'all').mockResolvedValue([location]);
    const update = vi.spyOn(devicesApi, 'update').mockResolvedValue(device);
    const user = userEvent.setup(); render(<DevicesPage />);
    expect(await screen.findByText('Modbus TCP')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Edit Test device' }));
    await choose(user, 'Location', 'Parent');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ location_id: 1 })));
  });

  it('reports list failures and retries', async () => {
    const list = vi.spyOn(connectionsApi, 'list').mockRejectedValueOnce(new Error('Network unavailable')).mockResolvedValue([]);
    const user = userEvent.setup(); render(<ConnectionsPage />);
    expect(await screen.findByText('Network unavailable')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No matching connections.')).toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
  });
});

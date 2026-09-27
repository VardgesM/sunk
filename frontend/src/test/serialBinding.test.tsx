import { render } from './render';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AutoAdapter from '../components/AutoAdapter';
import { ConnectionState } from '../components/RuntimeStatus';
import ConnectionsPage from '../pages/ConnectionsPage';
import { connectionsApi } from '../api/configuration';
import * as runtime from '../api/runtime';
import * as client from '../api/client';
const adapter = { device: 'COM7', description: 'USB serial', vid: 123, pid: 456, serial_number: 'unique', manufacturer: 'Configured manufacturer', product: 'USB adapter', hwid: 'USB VID:PID=007B:01C8 SER=unique' };
const discovered = { worker_host: 'test-host', observed_at: '2026-09-26T00:00:00Z', error: null, ports: [adapter] };
describe('USB auto binding UI', () => {
  it('displays host metadata and selects hardware identity', async () => {
    vi.spyOn(runtime, 'discoverSerial').mockResolvedValue(discovered);
    const select = vi.fn(); render(<AutoAdapter select={select} />);
    await userEvent.click(await screen.findByRole('button', { name: /USB adapter.*COM7.*VID 007B.*Serial unique/ }));
    expect(select).toHaveBeenCalledWith(adapter);
  });
  it('shows missing adapters and discovery errors', async () => {
    vi.spyOn(runtime, 'discoverSerial').mockResolvedValue({ ...discovered, ports: [], error: 'Enumeration failed' });
    render(<AutoAdapter select={() => {}} />);
    expect(await screen.findByText('Enumeration failed')).toBeInTheDocument();
    expect(screen.getByText(/No USB adapters visible/)).toBeInTheDocument();
  });
  it('saves auto USB configuration without temporary COM number', async () => {
    vi.spyOn(runtime, 'discoverSerial').mockResolvedValue(discovered);
    vi.spyOn(connectionsApi, 'list').mockResolvedValue([]);
    const save = vi.spyOn(connectionsApi, 'create').mockRejectedValue(new Error('Test captured save'));
    const user = userEvent.setup(); render(<ConnectionsPage />);
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    await user.type(screen.getByLabelText(/^Name/), 'Auto transport');
    await user.click(screen.getByRole('combobox', { name: 'Protocol' })); await user.click(screen.getByRole('option', { name: 'modbus_rtu' }));
    await user.click(screen.getByRole('combobox', { name: 'Serial port mode' })); await user.click(screen.getByRole('option', { name: 'Auto detect' }));
    expect(screen.queryByRole('textbox', { name: /^Serial port/ })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /USB adapter.*COM7/ }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ serial_port_mode: 'auto', serial_port: null, usb_vid: 123, usb_pid: 456, usb_serial_number: 'unique', serial_probe_enabled: false })));
  });
  it('displays ambiguity and requests worker re-detection', async () => {
    vi.spyOn(client, 'request').mockResolvedValue({ state: 'ERROR', detected_port: null, detection_status: 'AMBIGUOUS', detection_error: 'Multiple matching USB adapters', last_success: null });
    const redetect = vi.spyOn(runtime, 'redetectConnection').mockResolvedValue({ request_id: 'test', state: 'PENDING' });
    render(<ConnectionState id={3} auto />);
    expect(await screen.findByText('Detection: AMBIGUOUS')).toBeInTheDocument();
    expect(screen.getByText('Multiple matching USB adapters')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Re-detect' }));
    await waitFor(() => expect(redetect).toHaveBeenCalledWith(3));
    expect(await screen.findByText('Re-detect requested')).toBeInTheDocument();
  });
});

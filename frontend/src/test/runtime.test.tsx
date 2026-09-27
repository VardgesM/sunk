import { render } from './render';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConnectionState, SourceMode, TestConnection } from '../components/RuntimeStatus';
import SerialDiscovery from '../components/SerialDiscovery';
import * as client from '../api/client';
import * as runtime from '../api/runtime';

describe('runtime visibility', () => {
  it('clearly labels simulation and removes the simulation label in real mode', async () => {
    const request = vi.spyOn(client, 'request').mockResolvedValue({ mode: 'simulator', alive: true });
    const page = render(<SourceMode />);
    expect(await screen.findByText(/SIMULATION MODE/)).toBeInTheDocument();
    page.unmount(); request.mockResolvedValue({ mode: 'modbus', alive: true });
    render(<SourceMode />);
    expect(await screen.findByText(/Modbus — read only/)).toBeInTheDocument();
    expect(screen.queryByText(/SIMULATION MODE/)).not.toBeInTheDocument();
  });
  it('shows connection state and human-readable errors with text', async () => {
    vi.spyOn(client, 'request').mockResolvedValue({ state: 'ERROR', last_success: null, last_error: 'Connection refused' });
    render(<ConnectionState id={1} />);
    expect(await screen.findByText('ERROR')).toBeInTheDocument();
    expect(screen.getByText('Connection refused')).toBeInTheDocument();
  });
  it('hands a transport test to the worker and reports the honest result', async () => {
    vi.spyOn(runtime, 'testConnection').mockResolvedValue({ test_id: 'request', state: 'PENDING', success: null, message: null, latency_ms: null });
    vi.spyOn(runtime, 'getTest').mockResolvedValue({ test_id: 'request', state: 'SUCCEEDED', success: true, message: 'Port opened; slave NOT verified', latency_ms: 2 });
    const user = userEvent.setup(); render(<TestConnection id={1} name="Configured bus" />);
    await user.click(screen.getByRole('button', { name: 'Test Configured bus' }));
    expect(await screen.findByText(/PENDING/)).toBeInTheDocument();
    expect(await screen.findByText(/slave NOT verified/, {}, { timeout: 2500 })).toBeInTheDocument();
  });
  it('shows discovery from the worker and lets the operator select a port', async () => {
    vi.spyOn(runtime, 'discoverSerial').mockResolvedValue({ worker_host: 'worker-host', observed_at: '2026-01-01T00:00:00Z', error: null, ports: [{ device: 'discovered', description: 'USB adapter' }] });
    const select = vi.fn(); const user = userEvent.setup(); render(<SerialDiscovery select={select} />);
    await user.click(screen.getByRole('button', { name: 'Discover serial ports' }));
    await user.click(await screen.findByRole('button', { name: 'discovered — USB adapter' }));
    expect(select).toHaveBeenCalledWith('discovered');
  });
  it('reports worker errors without pretending an unavailable port list is complete', async () => {
    vi.spyOn(runtime, 'discoverSerial').mockRejectedValue(new Error('Worker unavailable'));
    const user = userEvent.setup(); render(<SerialDiscovery select={() => {}} />);
    await user.click(screen.getByRole('button', { name: 'Discover serial ports' }));
    await waitFor(() => expect(screen.getByText(/Manual port entry remains available/)).toBeInTheDocument());
  });
});

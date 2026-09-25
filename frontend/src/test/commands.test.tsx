import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ManualControl from '../components/ManualControl';
import type { Tag } from '../types/configuration';
import type { Command } from '../types/commands';
import { parseLiveEvent } from '../types/telemetry';
import { mergeCommands } from '../hooks/useCommands';
import * as api from '../api/commands';

const state = vi.hoisted(() => ({ mode: 'simulator', enabled: false, rows: [] as Command[], reload: vi.fn() }));
vi.mock('../hooks/useRuntime', () => ({ useRuntime: () => ({ data: { mode: state.mode, alive: true, writes_enabled: state.enabled } }) }));
vi.mock('../hooks/useCommands', async (original) => ({ ...await original<object>(), useCommands: () => ({ rows: state.rows, reload: state.reload, loading: false, error: '' }) }));
vi.mock('../components/LiveValues', () => ({ LiveValue: ({ field }: { field: string }) => <span>{field === 'value' ? 'OFF' : 'GOOD'}</span> }));

const tag: Tag = { id: 1, name: 'Test actuator', key: 'test_actuator', device_id: 1, register_type: 'coil', address: 10,
  data_type: 'bool', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: null, poll_interval_ms: 1000,
  writable: true, enabled: true, min_value: null, max_value: null, description: null,
  history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null,
  history_retention_days: null, created_at: '', updated_at: '' };
const command: Command = { id: 1, request_id: 'token', tag_id: 1, tag_name: 'Test actuator', device_id: 1, device_name: 'Test device',
  requested_value: true, previous_value: false, verified_value: null, status: 'VERIFYING', source: 'manual', telemetry_mode: 'simulator',
  attempt_count: 1, revision: 3, created_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:01Z', completed_at: null, error_message: null };

describe('manual commands', () => {
  beforeEach(() => { state.mode = 'simulator'; state.enabled = false; state.rows = []; state.reload.mockClear(); });
  it('sends a simulator coil command without optimistically changing actual', async () => {
    const send = vi.spyOn(api, 'createCommand').mockResolvedValue(command);
    const user = userEvent.setup(); render(<ManualControl tag={tag} />);
    await user.click(screen.getByRole('combobox', { name: 'Requested state' }));
    await user.click(screen.getByRole('option', { name: 'ON' }));
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(1, true, expect.any(String), false));
    expect(screen.getByText('OFF')).toBeInTheDocument();
  });
  it('blocks physical writes when the worker switch is disabled', () => {
    state.mode = 'modbus'; render(<ManualControl tag={tag} />);
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(screen.getByText(/physical writes are disabled/)).toBeInTheDocument();
  });
  it('requires confirmation before a physical write', async () => {
    state.mode = 'modbus'; state.enabled = true;
    const send = vi.spyOn(api, 'createCommand').mockResolvedValue(command);
    const user = userEvent.setup(); render(<ManualControl tag={tag} />);
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('Confirm physical write');
    await user.click(screen.getByRole('button', { name: 'Confirm write' }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(1, false, expect.any(String), true));
  });
  it('preserves numeric input precision in API requests', async () => {
    const send = vi.spyOn(api, 'createCommand').mockResolvedValue(command);
    const user = userEvent.setup(); render(<ManualControl tag={{ ...tag, register_type: 'holding_register', data_type: 'uint64' }} />);
    await user.type(screen.getByLabelText('Requested value'), '18446744073709551615');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(1, '18446744073709551615', expect.any(String), false));
  });
  it('shows requested, verified and errors separately', () => {
    state.rows = [{ ...command, status: 'FAILED', verified_value: false, error_message: 'Read-back mismatch' }];
    render(<ManualControl tag={tag} />);
    expect(screen.getByText('Requested: ON')).toBeInTheDocument();
    expect(screen.getByText('Verified: OFF')).toBeInTheDocument();
    expect(screen.getByText('Status: FAILED')).toBeInTheDocument();
    expect(screen.getByText('Read-back mismatch')).toBeInTheDocument();
  });
  it('reuses request ID after an uncertain HTTP failure', async () => {
    const send = vi.spyOn(api, 'createCommand').mockRejectedValue(new Error('Network lost'));
    const user = userEvent.setup(); render(<ManualControl tag={tag} />);
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('Network lost')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[0][2]).toBe(send.mock.calls[1][2]);
  });
  it('parses command events and rejects stale snapshots', () => {
    expect(parseLiveEvent(JSON.stringify({ type: 'command_status', data: command }))).toEqual({ type: 'command_status', data: command });
    expect(mergeCommands([command], [{ ...command, status: 'QUEUED', revision: 1 }])[0].status).toBe('VERIFYING');
    expect(() => parseLiveEvent(JSON.stringify({ type: 'command_status', data: { ...command, status: 'INVALID' } }))).toThrow();
  });
});

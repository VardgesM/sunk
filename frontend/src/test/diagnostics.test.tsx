import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { render, testAuth } from './render';
import { AuthContext } from '../auth/context';
import * as runtime from '../api/runtime';
import * as client from '../api/client';
import SystemDiagnostics from '../components/SystemDiagnostics';
import SystemPage from '../pages/SystemPage';

const snapshot: runtime.SystemDiagnostics = {
  application_version: 'test-version', application_mode: 'edge', database_revision: 'test-revision',
  checked_at: '2026-10-04T12:00:00Z', database_status: 'OK', database_latency_ms: 2.4,
  sync_status: 'CONNECTED', last_sync_at: '2026-10-04T11:59:57Z', pending_sync_count: 0,
  last_telemetry_at: '2026-10-04T11:59:52Z', telemetry_status: 'FRESH', backup_status: 'AVAILABLE',
  last_backup_at: '2026-10-03T12:00:00Z', disk_free_bytes: 71 * 1024 ** 3,
  hostname: 'api-container', uptime_seconds: 2 * 86400 + 4 * 3600,
};

function value(label: string) {
  return within(screen.getByRole('region', { name: 'Diagnostics' })).getByText(label).nextElementSibling;
}

describe('System Diagnostics', () => {
  it('loads a compact snapshot through the existing API client', async () => {
    const request = vi.spyOn(client, 'request').mockResolvedValue(snapshot);
    render(<SystemDiagnostics />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading diagnostics');
    expect(await screen.findByText('FRESH')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/system/diagnostics', { signal: expect.any(AbortSignal) });
    expect(value('Database')).toHaveTextContent('OK');
    expect(value('Database query latency')).toHaveTextContent('2.4 ms');
    expect(value('Last successful telemetry')).toHaveTextContent('8 seconds ago');
    expect(value('Last successful sync')).toHaveTextContent('3 seconds ago');
    expect(value('Pending sync')).toHaveTextContent('0');
    expect(value('Last successful backup')).toHaveTextContent(new Date(snapshot.last_backup_at!).toLocaleString());
    expect(value('Disk free (backup storage)')).toHaveTextContent('71.0 GiB');
    expect(value('API hostname')).toHaveTextContent('api-container');
    expect(value('API uptime')).toHaveTextContent('2d 4h 0m');
    expect(screen.getByText(/Refresh to update/)).toBeInTheDocument();
  });

  it('updates on manual refresh without a background polling timer', async () => {
    const get = vi.spyOn(runtime, 'getSystemDiagnostics').mockResolvedValueOnce(snapshot)
      .mockResolvedValueOnce({ ...snapshot, telemetry_status: 'STALE', sync_status: 'DISCONNECTED', pending_sync_count: 17 });
    const timer = vi.spyOn(window, 'setInterval');
    const user = userEvent.setup();
    render(<SystemDiagnostics />);
    expect(timer).not.toHaveBeenCalled();
    await screen.findByText('FRESH');
    await user.click(screen.getByRole('button', { name: 'Refresh diagnostics' }));
    expect(await screen.findByText('STALE')).toBeInTheDocument();
    expect(value('Synchronization')).toHaveTextContent('DISCONNECTED');
    expect(value('Pending sync')).toHaveTextContent('17');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('does not invent zeros for unavailable metrics', async () => {
    vi.spyOn(runtime, 'getSystemDiagnostics').mockResolvedValue({ ...snapshot,
      database_latency_ms: null, telemetry_status: 'UNKNOWN', last_telemetry_at: null,
      sync_status: 'UNKNOWN', pending_sync_count: null, last_sync_at: null,
      backup_status: 'UNKNOWN', last_backup_at: null, disk_free_bytes: null, hostname: null, uptime_seconds: null,
    });
    render(<SystemDiagnostics />);
    await waitFor(() => expect(value('Pending sync')).toHaveTextContent('UNKNOWN'));
    for (const label of ['Last successful telemetry', 'Last successful backup', 'Disk free (backup storage)', 'API hostname', 'API uptime']) {
      expect(value(label)).toHaveTextContent('UNKNOWN');
    }
  });

  it('shows partial failures with text labels', async () => {
    vi.spyOn(runtime, 'getSystemDiagnostics').mockResolvedValue({ ...snapshot,
      database_status: 'ERROR', database_latency_ms: null, sync_status: 'PAUSED',
      telemetry_status: 'UNAVAILABLE', backup_status: 'FAILED',
    });
    render(<SystemDiagnostics />);
    expect(await screen.findByText('ERROR')).toBeInTheDocument();
    expect(value('Synchronization')).toHaveTextContent('PAUSED');
    expect(value('Backup status')).toHaveTextContent('FAILED');
    expect(value('Telemetry freshness')).toHaveTextContent('UNAVAILABLE');
  });

  it('reports request errors and allows retry', async () => {
    const get = vi.spyOn(runtime, 'getSystemDiagnostics').mockRejectedValueOnce(new Error('API unavailable'))
      .mockResolvedValueOnce(snapshot);
    const user = userEvent.setup();
    render(<SystemDiagnostics />);
    expect(await screen.findByRole('alert')).toHaveTextContent('API unavailable');
    await user.click(screen.getByRole('button', { name: 'Refresh diagnostics' }));
    expect(await screen.findByText('FRESH')).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it.each(['ADMIN', 'OPERATOR', 'VIEWER'] as const)('uses existing System page access for %s', async role => {
    vi.spyOn(runtime, 'getSystemDiagnostics').mockResolvedValue(snapshot);
    vi.spyOn(runtime, 'getSystemInfo').mockResolvedValue(snapshot);
    vi.spyOn(client, 'request').mockResolvedValue({ mode: 'standalone', edges: [] });
    render(<AuthContext.Provider value={{ ...testAuth,
      user: { id: 1, username: 'test', role, permissions: role === 'ADMIN' ? ['read', 'users'] : ['read'] },
    }}><SystemPage /></AuthContext.Provider>);
    expect(await screen.findByText('FRESH')).toBeInTheDocument();
    expect(screen.getByText('Application version: test-version')).toBeInTheDocument();
    expect(screen.getByText(/Cloud synchronization is disabled/)).toBeInTheDocument();
  });

  it('aborts an outstanding request on unmount', () => {
    const get = vi.spyOn(runtime, 'getSystemDiagnostics').mockReturnValue(new Promise(() => {}));
    const page = render(<SystemDiagnostics />);
    const signal = get.mock.calls[0][0];
    expect(signal?.aborted).toBe(false);
    page.unmount();
    expect(signal?.aborted).toBe(true);
  });
});

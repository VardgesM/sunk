import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { render, testAuth } from './render';
import { AuthContext } from '../auth/context';
import * as client from '../api/client';
import * as runtime from '../api/runtime';
import SystemPage from '../pages/SystemPage';

const info: runtime.SystemInfo = {
  application_version: '9.8.7-test',
  database_revision: '0013_realtime_sync',
  application_mode: 'edge',
};

function syncStatus() {
  vi.spyOn(client, 'request').mockResolvedValue({
    mode: 'standalone', installation_id: null, pending: 0,
    last_sync_at: null, error: null, edges: [],
  });
}

describe('System application information', () => {
  it.each(['standalone', 'edge', 'cloud'] as const)('displays API metadata for %s', async mode => {
    const request = vi.spyOn(client, 'request').mockImplementation(async path => {
      if (path === '/system/info') return { ...info, application_mode: mode } as never;
      if (path === '/sync/status') return { mode: 'standalone', edges: [] } as never;
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<SystemPage />);
    expect(await screen.findByText('Application version: 9.8.7-test')).toBeInTheDocument();
    expect(screen.getByText('Database revision: 0013_realtime_sync')).toBeInTheDocument();
    expect(screen.getByText(`Application mode: ${mode}`)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/system/info', { signal: expect.any(AbortSignal) });
  });

  it('loads independently of synchronization status', async () => {
    syncStatus();
    let finish!: (value: runtime.SystemInfo) => void;
    vi.spyOn(runtime, 'getSystemInfo').mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<SystemPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading application information');
    expect(await screen.findByText(/Cloud synchronization is disabled/)).toBeInTheDocument();
    finish(info);
    expect(await screen.findByText('Application version: 9.8.7-test')).toBeInTheDocument();
  });

  it('reports a metadata error while leaving sync status usable', async () => {
    syncStatus();
    vi.spyOn(runtime, 'getSystemInfo').mockRejectedValue(new Error('Database revision unavailable'));
    render(<SystemPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Database revision unavailable');
    expect(screen.getByText(/Cloud synchronization is disabled/)).toBeInTheDocument();
    expect(screen.queryByText(/Application version:/)).not.toBeInTheDocument();
  });

  it('shows an uninitialized database explicitly', async () => {
    syncStatus();
    vi.spyOn(runtime, 'getSystemInfo').mockResolvedValue({ ...info, database_revision: null });
    render(<SystemPage />);
    expect(await screen.findByText('Database revision: Not initialized')).toBeInTheDocument();
  });

  it.each(['OPERATOR', 'VIEWER'] as const)('keeps System metadata readable for %s', async role => {
    syncStatus();
    vi.spyOn(runtime, 'getSystemInfo').mockResolvedValue(info);
    render(<AuthContext.Provider value={{ ...testAuth, user: {
      id: 2, username: 'reader', role, permissions: ['read'],
    } }}><SystemPage /></AuthContext.Provider>);
    expect(await screen.findByText('Application version: 9.8.7-test')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Backup & Restore' })).not.toBeInTheDocument();
  });

  it('cancels the metadata request when leaving the page', async () => {
    syncStatus();
    const getInfo = vi.spyOn(runtime, 'getSystemInfo').mockReturnValue(new Promise(() => {}));
    const page = render(<SystemPage />);
    await waitFor(() => expect(getInfo).toHaveBeenCalledOnce());
    const signal = getInfo.mock.calls[0][0];
    expect(signal?.aborted).toBe(false);
    page.unmount();
    expect(signal?.aborted).toBe(true);
  });
});

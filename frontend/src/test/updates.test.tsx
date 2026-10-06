import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { updatesApi, type UpdateStatus } from '../api/updates';
import { AuthContext } from '../auth/context';
import UpdatesPage from '../pages/UpdatesPage';
import { render, testAuth } from './render';

const status: UpdateStatus = {
  state: 'IDLE', installed_version: '1.0.0', channel: 'Stable', last_checked: null,
  release: null, available: false, runner_available: true, install_supported: true,
  message: null, job_id: null, from_version: null, backup_id: null,
  failure_stage: null, error: null, recovery_required: false,
};
const available: UpdateStatus = {
  ...status, state: 'AVAILABLE', available: true, last_checked: '2026-10-05T00:00:00Z',
  release: { version: '1.1.0', published_at: '2026-10-04T12:00:00Z', notes: 'Reviewed stable release', manifest: { sha256: 'a'.repeat(64), size: 1000 } },
};

describe('System Updates', () => {
  beforeEach(() => { vi.spyOn(updatesApi, 'status').mockResolvedValue(status); });

  it('shows installed version and manually checks releases', async () => {
    const check = vi.spyOn(updatesApi, 'check').mockResolvedValue(available);
    render(<UpdatesPage />);
    expect(await screen.findByText('Installed version: 1.0.0')).toBeInTheDocument();
    expect(check).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Check for updates' }));
    expect(await screen.findByText('Latest version: 1.1.0')).toBeInTheDocument();
    expect(screen.getByText('Reviewed stable release')).toBeInTheDocument();
  });

  it('requires confirmation and an external backup passphrase, then displays progress', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue(available);
    const install = vi.spyOn(updatesApi, 'install').mockResolvedValue({ ...available, state: 'BACKING_UP' });
    render(<UpdatesPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Update' }));
    const submit = screen.getByRole('button', { name: 'Back up and install' });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('Backup encryption passphrase'), 'safe-test-passphrase');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('Type UPDATE to confirm'), 'UPDATE');
    await user.click(submit);
    await waitFor(() => expect(install).toHaveBeenCalledWith('1.1.0', 'safe-test-passphrase'));
    expect(await screen.findByText('BACKING_UP')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText('Backup encryption passphrase')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Check for updates' })).toBeDisabled();
  });

  it('shows up-to-date state and deployment restrictions', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue({ ...status, release: { ...available.release!, version: status.installed_version }, last_checked: '2026-10-05T00:00:00Z', install_supported: false, message: 'Native Edge updates remain operator-managed.' });
    render(<UpdatesPage />);
    expect(await screen.findByText('Up to date')).toBeInTheDocument();
    expect(screen.getByText('Native Edge updates remain operator-managed.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Update' })).not.toBeInTheDocument();
  });

  it('does not permit installation with an offline runner', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue({ ...available, runner_available: false });
    render(<UpdatesPage />);
    expect(await screen.findByText('Host deployment runner is offline.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update' })).toBeDisabled();
  });

  it('does not claim up-to-date when no public release is available', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue({ ...status, last_checked: '2026-10-05T00:00:00Z' });
    render(<UpdatesPage />);
    expect(await screen.findByText('No public stable release found')).toBeInTheDocument();
    expect(screen.queryByText('Up to date')).not.toBeInTheDocument();
  });

  it('shows rollback and failed migration recovery without offering retry', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue({ ...available, state: 'FAILED', failure_stage: 'MIGRATING', error: 'Migration could not be verified', recovery_required: true, message: 'Controlled offline recovery required' });
    render(<UpdatesPage />);
    expect(await screen.findByText('MIGRATING: Migration could not be verified')).toBeInTheDocument();
    expect(screen.getByText('Controlled offline recovery required')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update' })).toBeDisabled();
  });

  it('shows verified binary rollback', async () => {
    vi.mocked(updatesApi.status).mockResolvedValue({ ...available, state: 'ROLLED_BACK' });
    render(<UpdatesPage />);
    expect(await screen.findByText('Previous release restored and verified.')).toBeInTheDocument();
  });

  it('reports service interruption without claiming success', async () => {
    vi.mocked(updatesApi.status).mockRejectedValue(new Error('Network unavailable'));
    render(<UpdatesPage />);
    expect(await screen.findByText(/Services may be restarting/)).toBeInTheDocument();
    expect(screen.queryByText(/Update successful:/)).not.toBeInTheDocument();
  });

  it('denies viewer access without fetching update metadata', () => {
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role: 'VIEWER', permissions: ['read'] } }}><UpdatesPage /></AuthContext.Provider>);
    expect(screen.getByText('Administrator access required.')).toBeInTheDocument();
    expect(updatesApi.status).not.toHaveBeenCalled();
  });
});

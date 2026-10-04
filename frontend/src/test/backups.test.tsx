import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BackupRestorePage from '../pages/BackupRestorePage';
import { backupsApi, type Backup, type ConfigurationFile } from '../api/backups';
import { AuthContext } from '../auth/context';
import { render, testAuth } from './render';

const backup: Backup = {id: 'd3f20e03-28a5-4f32-8bde-d0d673381aaa', kind: 'backup', created_at: '2026-10-04T00:00:00Z', size: 1024, status: 'AVAILABLE', error: null,
  manifest: {format_version: 1, created_at: '2026-10-04T00:00:00Z', application_version: '0.1.0', migration_revision: '0014_backups', deployment_mode: 'standalone', postgres_major: 17}};
const config: ConfigurationFile = {format: 'modbus-monitor-config', version: 1, application_version: '0.1.0', exported_at: '2026-10-04T00:00:00Z', data: {tags: []}};

describe('Backup & Restore', () => {
  beforeEach(() => { vi.spyOn(backupsApi, 'list').mockResolvedValue([]); });
  it('creates an encrypted backup and clears the passphrase', async () => {
    const create = vi.spyOn(backupsApi, 'create').mockResolvedValue(backup);
    render(<BackupRestorePage />); const user = userEvent.setup();
    expect(await screen.findByText('No backups yet.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('New backup passphrase'), 'test-backup-password');
    await user.click(screen.getByRole('button', {name: 'Create backup'}));
    await waitFor(() => expect(create).toHaveBeenCalledWith('test-backup-password'));
    expect(await screen.findByText(/Encrypted backup created/)).toBeInTheDocument();
    expect(screen.getByLabelText('New backup passphrase')).toHaveValue('');
  });
  it('requires deletion confirmation', async () => {
    vi.mocked(backupsApi.list).mockResolvedValue([backup]);
    const remove = vi.spyOn(backupsApi, 'remove').mockResolvedValue();
    render(<BackupRestorePage />); const user = userEvent.setup();
    expect(await screen.findByRole('link', {name: 'Download'})).toHaveAttribute('href', `/api/system/backups/${backup.id}/download`);
    await user.click(screen.getByRole('button', {name: 'Delete'}));
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', {name: 'Delete permanently'}));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(backup.id));
  });
  it('validates and explicitly prepares an offline restore', async () => {
    vi.mocked(backupsApi.list).mockResolvedValue([backup]);
    const validate = vi.spyOn(backupsApi, 'validate').mockResolvedValue({...backup, status: 'VALIDATED'});
    const confirm = vi.spyOn(backupsApi, 'confirm').mockResolvedValue({...backup, status: 'READY_OFFLINE'});
    render(<BackupRestorePage />); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', {name: 'Select for restore'}));
    expect(screen.queryByRole('button', {name: 'Prepare full restore'})).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Backup passphrase'), 'test-backup-password');
    await user.click(screen.getByRole('button', {name: 'Validate backup'}));
    await waitFor(() => expect(validate).toHaveBeenCalled());
    expect(await screen.findByRole('button', {name: 'Prepare full restore'})).toBeDisabled();
    await user.type(screen.getByLabelText('Type RESTORE to confirm'), 'RESTORE');
    await user.click(screen.getByRole('button', {name: 'Prepare full restore'}));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(backup.id));
    expect(await screen.findByText(/python -m app.restore/)).toBeInTheDocument();
  });
  it('previews import before applying and reports failures', async () => {
    const preview = vi.spyOn(backupsApi, 'preview').mockResolvedValue({valid: true, counts: {tags: 3}, warnings: ['Connections remain disabled.']});
    const apply = vi.spyOn(backupsApi, 'import').mockRejectedValue(new Error('Identifier conflict'));
    render(<BackupRestorePage />); const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Import configuration', {selector: 'input'}), new File([JSON.stringify(config)], 'config.json', {type: 'application/json'}));
    expect(await screen.findByText('tags: 3')).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith(config); expect(apply).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', {name: 'Confirm import'}));
    await user.click(screen.getByRole('button', {name: 'Apply import'}));
    expect(await screen.findByText(/Identifier conflict/)).toBeInTheDocument();
  });
  it('hides import on Cloud and denies non-admin UI', async () => {
    const cloud = {...testAuth, user: {...testAuth.user!, application_mode: 'cloud'}};
    const view = render(<AuthContext.Provider value={cloud}><BackupRestorePage /></AuthContext.Provider>);
    expect(await screen.findByText(/Cloud remains a read-only mirror/)).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Export configuration'})).not.toBeInTheDocument();
    view.unmount();
    render(<AuthContext.Provider value={{...testAuth, user: {...testAuth.user!, role: 'VIEWER', permissions: ['read']}}}><BackupRestorePage /></AuthContext.Provider>);
    expect(screen.getByText('Administrator access required.')).toBeInTheDocument();
  });
  it('applies a validated configuration and clears its preview', async () => {
    vi.spyOn(backupsApi, 'preview').mockResolvedValue({valid: true, counts: {tags: 2}, warnings: []});
    const apply = vi.spyOn(backupsApi, 'import').mockResolvedValue({imported: {tags: 2}});
    render(<BackupRestorePage />); const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Import configuration', {selector: 'input'}), new File([JSON.stringify(config)], 'config.json', {type: 'application/json'}));
    await user.click(await screen.findByRole('button', {name: 'Confirm import'}));
    await user.click(screen.getByRole('button', {name: 'Apply import'}));
    expect(await screen.findByText(/Configuration imported/)).toBeInTheDocument();
    expect(apply).toHaveBeenCalledWith(config);
    expect(screen.queryByText('Import preview')).not.toBeInTheDocument();
  });
  it('uploads a backup and reports failed archive validation', async () => {
    const upload = vi.spyOn(backupsApi, 'upload').mockResolvedValue({...backup, kind: 'upload', status: 'UPLOADED'});
    vi.spyOn(backupsApi, 'validate').mockRejectedValue(new Error('Incorrect passphrase or damaged backup'));
    render(<BackupRestorePage />); const user = userEvent.setup();
    const file = new File(['encrypted-data'], 'copy.mmbak', {type: 'application/octet-stream'});
    await user.upload(screen.getByLabelText('Upload backup', {selector: 'input'}), file);
    await user.type(await screen.findByLabelText('Backup passphrase'), 'test-backup-password');
    await user.click(screen.getByRole('button', {name: 'Validate backup'}));
    expect(await screen.findByText(/Incorrect passphrase or damaged backup/)).toBeInTheDocument();
    expect(upload).toHaveBeenCalledWith(file);
    expect(screen.queryByRole('button', {name: 'Prepare full restore'})).not.toBeInTheDocument();
  });
});

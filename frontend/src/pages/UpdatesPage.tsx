import { useEffect, useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Stack, TextField, Typography } from '@mui/material';
import { updatesApi, type UpdateStatus } from '../api/updates';
import { usePermission } from '../auth/context';

const active = new Set(['CHECKING', 'DOWNLOADING', 'VALIDATING', 'BACKING_UP', 'READY', 'INSTALLING', 'MIGRATING', 'RESTARTING', 'VERIFYING', 'ROLLING_BACK']);

export default function UpdatesPage() {
  const admin = usePermission('users');
  const [status, setStatus] = useState<UpdateStatus>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');

  useEffect(() => {
    if (!admin) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const result = await updatesApi.status(controller.signal);
        if (!controller.signal.aborted) { setStatus(result); setError(''); }
      } catch {
        if (!controller.signal.aborted) setError('Update status unavailable. Services may be restarting; this page will reconnect. If recovery is required, inspect the host updater journal.');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), 3000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [admin]);

  async function perform(operation: () => Promise<UpdateStatus>) {
    setBusy(true); setError('');
    try { setStatus(await operation()); }
    catch (err) { setError(err instanceof Error ? err.message : 'Update request failed'); }
    finally { setBusy(false); }
  }

  if (!admin) return <Alert severity="error">Administrator access required.</Alert>;
  const running = status && active.has(status.state);
  return <Stack spacing={2} sx={{ maxWidth: 850 }}>
    <Typography variant="h4" component="h1">System / Updates</Typography>
    <Alert severity="info">Manual updates only. An encrypted full backup is required. Keep its passphrase in your password manager; it is never saved by the application.</Alert>
    {error && <Alert severity="warning">{error}</Alert>}
    {!status && <Typography role="status">Loading update status...</Typography>}
    {status && <>
      <Typography>Installed version: {status.installed_version}</Typography>
      <Typography>Latest version: {status.release?.version ?? 'Unknown'}</Typography>
      <Typography>Update channel: {status.channel}</Typography>
      <Typography>Last checked: {status.last_checked ? new Date(status.last_checked).toLocaleString() : 'Never'}</Typography>
      <Typography role="status">{status.state}</Typography>
      {running && <LinearProgress aria-label="Update in progress" />}
      {status.message && <Alert severity={status.recovery_required ? 'error' : 'info'}>{status.message}</Alert>}
      {status.error && <Alert severity="error">{status.failure_stage}: {status.error}</Alert>}
      {status.state === 'SUCCESS' && <Alert severity="success">Update successful: {status.from_version} → {status.release?.version}</Alert>}
      {status.state === 'ROLLED_BACK' && <Alert severity="warning">Previous release restored and verified.</Alert>}
      {status.backup_id && <Typography>Recovery backup: {status.backup_id}</Typography>}
      {!running && <Typography>{status.available ? 'Update available' : status.last_checked && status.state !== 'FAILED' ? status.release ? 'Up to date' : 'No public stable release found' : 'Check for a stable release'}</Typography>}
      <Button disabled={busy || running || status.recovery_required} onClick={() => void perform(updatesApi.check)}>Check for updates</Button>
      {status.release && <Stack spacing={1}>
        <Typography variant="h6">Release {status.release.version}</Typography>
        <Typography>{new Date(status.release.published_at).toLocaleString()}</Typography>
        <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{status.release.notes || 'No release notes.'}</Typography>
        <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>SHA-256: {status.release.manifest.sha256}</Typography>
      </Stack>}
      {status.install_supported && !status.runner_available && <Alert severity="warning">Host deployment runner is offline.</Alert>}
      {status.available && <Button variant="contained" disabled={busy || running || !status.install_supported || !status.runner_available || status.recovery_required} onClick={() => setConfirm(true)}>Update</Button>}
    </>}
    <Dialog open={confirm} onClose={() => { setConfirm(false); setPassword(''); setConfirmation(''); }} fullWidth>
      <DialogTitle>Confirm manual update</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <Typography>Cloud services will briefly stop. If a database migration is attempted and verification fails, services stay stopped for controlled recovery. Local Edge operation is independent.</Typography>
        <TextField type="password" autoComplete="new-password" label="Backup encryption passphrase" value={password} onChange={event => setPassword(event.target.value)} helperText="At least 12 characters. Save this outside the application database." />
        <TextField label="Type UPDATE to confirm" value={confirmation} onChange={event => setConfirmation(event.target.value)} />
      </Stack></DialogContent>
      <DialogActions><Button onClick={() => { setConfirm(false); setPassword(''); setConfirmation(''); }}>Cancel</Button>
        <Button disabled={busy || password.length < 12 || confirmation !== 'UPDATE'} onClick={() => {
          if (!status?.release) return;
          const version = status.release.version, passphrase = password;
          setPassword(''); setConfirmation(''); setConfirm(false);
          void perform(() => updatesApi.install(version, passphrase));
        }}>Back up and install</Button></DialogActions>
    </Dialog>
  </Stack>;
}

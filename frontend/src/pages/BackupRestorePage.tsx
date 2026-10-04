import { useEffect, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Divider, Stack, TextField, Typography } from '@mui/material';
import { backupsApi, type Backup, type ConfigurationFile, type ImportPreview } from '../api/backups';
import { useAuth, usePermission } from '../auth/context';

export default function BackupRestorePage() {
  const admin = usePermission('users');
  const cloud = useAuth().user?.application_mode === 'cloud';
  const [rows, setRows] = useState<Backup[]>([]);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [password, setPassword] = useState(''), [restorePassword, setRestorePassword] = useState('');
  const [selected, setSelected] = useState<Backup | null>(null), [remove, setRemove] = useState<Backup | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [document, setDocument] = useState<ConfigurationFile | null>(null), [preview, setPreview] = useState<ImportPreview | null>(null);
  const [importConfirm, setImportConfirm] = useState(false);
  const refresh = async () => setRows(await backupsApi.list());
  useEffect(() => { let active = true; if (admin) void backupsApi.list().then(data => { if (active) setRows(data); }).catch(e => { if (active) setError(String(e)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [admin]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); await refresh(); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  function downloadConfiguration(data: ConfigurationFile) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const link = window.document.createElement('a'); link.href = url; link.download = 'modbus-monitor-config.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (!admin) return <Alert severity="error">Administrator access required.</Alert>;
  return <Stack spacing={3}>
    <Typography component="h1" variant="h4">System / Backup &amp; Restore</Typography>
    {error && <Alert severity="error">{error}</Alert>}{message && <Alert severity="success">{message}</Alert>}
    {busy && <Alert icon={<CircularProgress size={20} />} severity="info">Operation in progress. Large backups can take several minutes.</Alert>}
    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h5">Full Backup</Typography>
      <Typography>Encrypted database and non-secret recovery settings. Store the downloaded file and its passphrase separately. Lost passphrases cannot be recovered.</Typography>
      <Stack direction={{xs: 'column', sm: 'row'}} spacing={2}>
        <TextField label="New backup passphrase" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} helperText="At least 12 characters. Never stored on the server." />
        <Button disabled={busy || password.length < 12} variant="contained" onClick={() => void run(async () => { try { await backupsApi.create(password); setMessage('Encrypted backup created. Download it to independent storage.'); } finally { setPassword(''); } })}>Create backup</Button>
        <Button disabled={busy} onClick={() => void run(refresh)}>Refresh status</Button>
      </Stack>
      {loading ? <Typography role="status">Loading backups...</Typography> : rows.length === 0 ? <Typography>No backups yet.</Typography> : rows.map(row => <Box key={row.id} sx={{border: 1, borderColor: 'divider', p: 2, borderRadius: 1, overflowWrap: 'anywhere'}}>
        <Typography>{new Date(row.created_at).toLocaleString()} - {row.status}</Typography>
        <Typography variant="body2">{(row.size / 1024 / 1024).toFixed(2)} MB | App {row.manifest?.application_version ?? 'Not validated'} | {row.kind}</Typography>
        {row.error && <Alert severity="warning">{row.error}</Alert>}
        <Stack direction="row" flexWrap="wrap" gap={1}>
          {!['FAILED','CREATING','RESTORING'].includes(row.status) && <Button component="a" href={`/api/system/backups/${row.id}/download`} download>Download</Button>}
          <Button disabled={busy || ['CREATING','RESTORING'].includes(row.status)} onClick={() => { setSelected(row); setConfirmation(''); setRestorePassword(''); }}>Select for restore</Button>
          <Button disabled={busy || ['CREATING','READY_OFFLINE','RESTORING'].includes(row.status)} color="error" onClick={() => setRemove(row)}>Delete</Button>
          {['CREATING','READY_OFFLINE','RESTORING'].includes(row.status) && <Button disabled={busy} onClick={() => void run(async () => { await backupsApi.cancel(row.id); if (selected?.id === row.id) setSelected(null); })}>Cancel preparation</Button>}
        </Stack>
      </Box>)}
    </Stack></CardContent></Card>
    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h5">Restore</Typography>
      <Alert severity="warning">Restore replaces the database. Final execution requires stopping all API, worker and sync processes and running the documented offline restore command. Physical writes must be disabled. Use only trusted backups.</Alert>
      <Button component="label" disabled={busy}>Upload backup<input hidden type="file" accept=".mmbak" aria-label="Upload backup" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void run(async () => { setSelected(await backupsApi.upload(file)); setConfirmation(''); setRestorePassword(''); }); }} /></Button>
      {selected && <>
        <Typography sx={{overflowWrap: 'anywhere'}}>Selected: {selected.id} - {selected.status}</Typography>
        <TextField label="Backup passphrase" type="password" autoComplete="off" value={restorePassword} onChange={e => setRestorePassword(e.target.value)} />
        <Button disabled={busy || restorePassword.length < 12} onClick={() => void run(async () => { try { setSelected(await backupsApi.validate(selected.id, restorePassword)); setMessage('Archive, integrity, database dump and compatibility validated.'); } finally { setRestorePassword(''); } })}>Validate backup</Button>
        {selected.manifest && <Typography>Mode: {selected.manifest.deployment_mode} | PostgreSQL {selected.manifest.postgres_major} | Migration {selected.manifest.migration_revision}</Typography>}
        {selected.status === 'VALIDATED' && <><TextField label="Type RESTORE to confirm" value={confirmation} onChange={e => setConfirmation(e.target.value)} /><Button color="error" variant="contained" disabled={busy || confirmation !== 'RESTORE'} onClick={() => void run(async () => { setSelected(await backupsApi.confirm(selected.id)); setConfirmation(''); })}>Prepare full restore</Button></>}
        {selected.status === 'READY_OFFLINE' && <Alert severity="warning">Prepared. Stop services, then run in the API environment: <Box component="code" sx={{display: 'block', overflowWrap: 'anywhere'}}>python -m app.restore --id {selected.id} --confirm RESTORE</Box>The command prompts for the passphrase. Follow docs/backup-restore.md for Docker commands, rollback and Edge/Cloud reconciliation.</Alert>}
      </>}
    </Stack></CardContent></Card>
    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h5">Configuration</Typography>
      {cloud ? <Alert severity="info">Configuration export/import is available on Edge or standalone installations. Cloud remains a read-only mirror of Edge configuration.</Alert> : <>
        <Typography>Portable JSON: Locations, Connections, Devices, Tags, history policies, Dashboards, Automation and Alarm rules. No users, credentials, telemetry or event history.</Typography>
        <Stack direction={{xs: 'column', sm: 'row'}} gap={1}>
          <Button disabled={busy} onClick={() => void run(async () => { downloadConfiguration(await backupsApi.export()); setMessage('Configuration exported. Treat device addresses and names as private installation information.'); })}>Export configuration</Button>
          <Button component="label" disabled={busy}>Import configuration<input hidden type="file" accept=".json,application/json" aria-label="Import configuration" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; setPreview(null); setDocument(null); if (file) void run(async () => { const data = JSON.parse(await file.text()) as ConfigurationFile; const result = await backupsApi.preview(data); setDocument(data); setPreview(result); }); }} /></Button>
        </Stack>
        {preview && <><Divider /><Typography variant="h6">Import preview</Typography>{Object.entries(preview.counts).map(([name, count]) => <Typography key={name}>{name.replaceAll('_', ' ')}: {count}</Typography>)}{preview.warnings.map(warning => <Alert key={warning} severity="warning">{warning}</Alert>)}<Button disabled={busy || !preview.valid} variant="contained" onClick={() => setImportConfirm(true)}>Confirm import</Button></>}
      </>}
    </Stack></CardContent></Card>
    <Dialog open={!!remove} onClose={() => !busy && setRemove(null)}><DialogTitle>Delete backup?</DialogTitle><DialogContent>This removes this copy from server storage. Download it first if needed.</DialogContent><DialogActions><Button disabled={busy} onClick={() => setRemove(null)}>Cancel</Button><Button color="error" disabled={busy} onClick={() => void run(async () => { if (remove) { await backupsApi.remove(remove.id); if (selected?.id === remove.id) setSelected(null); setRemove(null); } })}>Delete permanently</Button></DialogActions></Dialog>
    <Dialog open={importConfirm} onClose={() => !busy && setImportConfirm(false)}><DialogTitle>Apply configuration import?</DialogTitle><DialogContent>Existing configuration will not be overwritten. Connections, Automation and Alarm rules will be disabled until you review and enable them.</DialogContent><DialogActions><Button disabled={busy} onClick={() => setImportConfirm(false)}>Cancel</Button><Button disabled={busy} onClick={() => void run(async () => { if (document) { await backupsApi.import(document); setPreview(null); setDocument(null); setImportConfirm(false); setMessage('Configuration imported. Review hardware settings before enabling connections and rules.'); } })}>Apply import</Button></DialogActions></Dialog>
  </Stack>;
}

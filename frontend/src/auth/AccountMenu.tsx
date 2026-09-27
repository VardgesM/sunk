import { useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from '@mui/material';
import { useAuth } from './context';
import { request } from '../api/client';
export default function AccountMenu() {
  const auth = useAuth(); const [open,setOpen] = useState(false), [current,setCurrent] = useState(''), [password,setPassword] = useState(''), [error,setError] = useState(''), [busy,setBusy] = useState(false);
  return <><Stack direction="row" alignItems="center" flexWrap="wrap">
    <Button color="inherit" onClick={() => setOpen(true)}>{auth.user?.username} ({auth.user?.role})</Button>
    <Button color="inherit" disabled={busy} onClick={() => { setBusy(true); void auth.logout().catch(e => setError(String(e))).finally(() => setBusy(false)); }}>Logout</Button>
  </Stack>{error && !open && <Typography role="alert">{error}</Typography>}
  <Dialog open={open} onClose={() => { if (!busy) { setOpen(false); setCurrent(''); setPassword(''); } }} fullWidth maxWidth="sm"><DialogTitle>Change password</DialogTitle><DialogContent><Stack spacing={2} sx={{pt:1}}>{error && <Alert severity="error">{error}</Alert>}
    <TextField label="Current password" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} />
    <TextField label="New password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} helperText="Non-empty, up to 128 characters. All sessions will be revoked; sign in again." />
  </Stack></DialogContent><DialogActions><Button disabled={busy} onClick={() => { setOpen(false); setCurrent(''); setPassword(''); }}>Cancel</Button><Button disabled={busy || !password || !current} onClick={() => { setBusy(true); void request('/auth/password',{method:'POST',body:JSON.stringify({current_password:current,password})}).then(auth.refresh).catch(e => setError(String(e))).finally(() => { setBusy(false); setCurrent(''); setPassword(''); }); }}>Change password</Button></DialogActions></Dialog></>;
}

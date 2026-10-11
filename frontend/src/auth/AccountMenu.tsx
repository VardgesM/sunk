import { useState } from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, ListItemIcon, ListItemText, Menu, MenuItem, Snackbar, Stack, TextField, Typography } from '@mui/material';
import AccountCircleOutlined from '@mui/icons-material/AccountCircleOutlined';
import PasswordOutlined from '@mui/icons-material/PasswordOutlined';
import LogoutOutlined from '@mui/icons-material/LogoutOutlined';
import { useAuth } from './context';
import { request } from '../api/client';
import { shellLayout } from '../layout/tokens';

export default function AccountMenu() {
  const auth = useAuth();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false), [current, setCurrent] = useState(''), [password, setPassword] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  function closePassword() {
    if (!busy) { setOpen(false); setCurrent(''); setPassword(''); setError(''); }
  }
  return <>
    <Button color="inherit" aria-label={`Account: ${auth.user?.username} (${auth.user?.role})`}
      aria-haspopup="menu" aria-expanded={!!anchor} aria-controls={anchor ? 'account-menu' : undefined}
      onClick={event => setAnchor(event.currentTarget)}
      sx={{ minWidth: shellLayout.touchTarget, minHeight: shellLayout.touchTarget, flexShrink: 0, gap: 1, px: 1 }}>
      <AccountCircleOutlined />
      <Box sx={{ display: { xs: 'none', sm: 'block' }, textAlign: 'left', maxWidth: 180 }}>
        <Typography component="span" noWrap sx={{ display: 'block', fontSize: 14, fontWeight: 600, textTransform: 'none' }}>{auth.user?.username}</Typography>
        <Typography component="span" variant="caption" sx={{ display: 'block' }}>{auth.user?.role}</Typography>
      </Box>
    </Button>
    <Menu id="account-menu" anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}
      slotProps={{ list: { 'aria-label': 'Account menu' }, paper: { sx: { width: 280, maxWidth: 'calc(100vw - 32px)' } } }}>
      <Box sx={{ px: 2, py: 1, overflowWrap: 'anywhere' }}>
        <Typography fontWeight={600}>{auth.user?.username}</Typography>
        <Typography variant="body2" color="text.secondary">{auth.user?.role}</Typography>
      </Box>
      <MenuItem sx={{ minHeight: shellLayout.touchTarget }} onClick={() => { setAnchor(null); setError(''); setOpen(true); }}>
        <ListItemIcon><PasswordOutlined fontSize="small" /></ListItemIcon><ListItemText>Change password</ListItemText>
      </MenuItem>
      <MenuItem disabled={busy} sx={{ minHeight: shellLayout.touchTarget }} onClick={() => {
        setAnchor(null); setBusy(true); setError('');
        void auth.logout().catch(e => setError(String(e))).finally(() => setBusy(false));
      }}><ListItemIcon><LogoutOutlined fontSize="small" /></ListItemIcon><ListItemText>Logout</ListItemText></MenuItem>
    </Menu>
    <Snackbar open={!!error && !open} onClose={() => setError('')}><Alert severity="error" onClose={() => setError('')}>{error}</Alert></Snackbar>
    <Dialog open={open} onClose={closePassword} fullWidth maxWidth="sm" aria-labelledby="password-dialog-title">
      <DialogTitle id="password-dialog-title">Change password</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{error && <Alert severity="error">{error}</Alert>}
        <TextField label="Current password" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} helperText="Non-empty, up to 128 characters. All sessions will be revoked; sign in again." />
      </Stack></DialogContent>
      <DialogActions><Button disabled={busy} onClick={closePassword}>Cancel</Button><Button disabled={busy || !password || !current} onClick={() => {
        setBusy(true);
        void request('/auth/password', { method: 'POST', body: JSON.stringify({ current_password: current, password }) })
          .then(auth.refresh).catch(e => setError(String(e))).finally(() => { setBusy(false); setCurrent(''); setPassword(''); });
      }}>Change password</Button></DialogActions>
    </Dialog>
  </>;
}

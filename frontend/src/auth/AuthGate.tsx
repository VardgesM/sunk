import { useState, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import { useAuth } from './context';
function LoginPage() {
  const auth = useAuth();
  const [username,setUsername] = useState(''), [password,setPassword] = useState(''), [error,setError] = useState(''), [busy,setBusy] = useState(false);
  return <Box sx={{ p:2, minHeight:'100dvh', display:'grid', placeItems:'center' }}><Paper sx={{p:3,width:'100%',maxWidth:400}}><Stack component="form" spacing={2} onSubmit={e => {
    e.preventDefault(); setBusy(true); setError(''); void auth.login(username,password).catch(reason => setError(reason instanceof Error ? reason.message : 'Login failed')).finally(() => { setBusy(false); setPassword(''); });
  }}><Typography variant="h4" component="h1">Sign in</Typography>
    <Typography>Modbus Monitor</Typography>{error && <Alert severity="error">{error}</Alert>}
    <TextField label="Username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required />
    <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
    <Button type="submit" variant="contained" disabled={busy}>Sign in</Button>
  </Stack></Paper></Box>;
}
export default function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth(); const location = useLocation();
  if (auth.loading) return <Typography role="status">Checking session...</Typography>;
  if (!auth.user) return location.pathname === '/login' ? <LoginPage /> : <Navigate to="/login" replace />;
  if (location.pathname === '/login') return <Navigate to="/dashboard" replace />;
  return children;
}

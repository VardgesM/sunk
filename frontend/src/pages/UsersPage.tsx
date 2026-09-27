import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { usersApi, type User, type UserInput, type Role } from '../api/users';
import { useAuth } from '../auth/context';
export default function UsersPage() {
  const auth = useAuth(); const [rows,setRows] = useState<User[]>(), [error,setError] = useState(''), [notice,setNotice] = useState('');
  const [offset,setOffset] = useState(0), [revision,setRevision] = useState(0), [busy,setBusy] = useState(false);
  const [editor,setEditor] = useState<User|'new'>(), [form,setForm] = useState<UserInput>({username:'',role:'VIEWER',enabled:true});
  const [reset,setReset] = useState<User>(), [password,setPassword] = useState(''), [remove,setRemove] = useState<User>();
  useEffect(() => { let active=true; usersApi.list(offset).then(r => { if(active) { setRows(r); setError(''); } }).catch(e => { if(active) setError(String(e)); }); return () => {active=false;}; },[offset,revision]);
  async function action(fn:()=>Promise<unknown>) { setBusy(true); setError(''); try {await fn();setEditor(undefined);setReset(undefined);setRemove(undefined);setPassword('');setRevision(v=>v+1);setNotice('User updated');await auth.refresh();} catch(e){setError(e instanceof Error?e.message:'Operation failed');} finally{setBusy(false);} }
  return <Stack spacing={2}><Typography variant="h4" component="h1">Users</Typography>
    {error && <Alert severity="error">{error}</Alert>}{notice && <Alert severity="success" onClose={()=>setNotice('')}>{notice}</Alert>}
    <Button onClick={()=>{setForm({username:'',role:'VIEWER',enabled:true});setPassword('');setEditor('new');}}>Create user</Button>
    {!rows && !error && <Typography>Loading users...</Typography>}
    {rows?.map(row=><Stack key={row.id} spacing={1} sx={{border:1,borderColor:'divider',p:2,borderRadius:1}}>
      <Typography fontWeight={700}>{row.username} - {row.role} - {row.enabled?'Enabled':'Disabled'}</Typography>
      <Typography>Last login: {row.last_login_at?new Date(row.last_login_at).toLocaleString():'Never'}</Typography>
      <Stack direction="row" flexWrap="wrap"><Button onClick={()=>{setForm({username:row.username,role:row.role,enabled:row.enabled});setPassword('');setEditor(row);}}>Edit {row.username}</Button>
      {row.id!==auth.user?.id && <Button onClick={()=>{setPassword('');setReset(row);}}>Reset password</Button>}<Button color="error" onClick={()=>setRemove(row)}>Delete {row.username}</Button></Stack>
    </Stack>)}
    <Stack direction="row"><Button disabled={!offset} onClick={()=>setOffset(v=>Math.max(0,v-50))}>Previous</Button><Button disabled={!rows || rows.length<50} onClick={()=>setOffset(v=>v+50)}>Next</Button></Stack>
    <Dialog open={!!editor} fullWidth maxWidth="sm" onClose={()=>{if(!busy){setEditor(undefined);setPassword('');}}}><DialogTitle>{editor==='new'?'Create user':'Edit user'}</DialogTitle><DialogContent><Stack spacing={2} sx={{pt:1}}>{error && <Alert severity="error">{error}</Alert>}
      <TextField label="Username" value={form.username} onChange={e=>setForm({...form,username:e.target.value})} autoComplete="off" />
      <TextField select label="Role" value={form.role} onChange={e=>setForm({...form,role:e.target.value as Role})}>{(['ADMIN','OPERATOR','VIEWER'] as const).map(role=><MenuItem key={role} value={role}>{role}</MenuItem>)}</TextField>
      <FormControlLabel label="Enabled" control={<Checkbox checked={form.enabled} onChange={e=>setForm({...form,enabled:e.target.checked})}/>} />
      {editor==='new' && <TextField label="Initial password" type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} helperText="Non-empty, up to 128 characters"/>}
      <Typography>Role, username and enabled changes revoke this user's sessions. The last enabled ADMIN is protected.</Typography>
    </Stack></DialogContent><DialogActions><Button disabled={busy} onClick={()=>{setEditor(undefined);setPassword('');}}>Cancel</Button><Button disabled={busy || !form.username || editor==='new' && !password} onClick={()=>void action(()=>editor==='new'?usersApi.create({...form,password}):usersApi.edit((editor as User).id,form))}>Save user</Button></DialogActions></Dialog>
    <Dialog open={!!reset} onClose={()=>{if(!busy){setReset(undefined);setPassword('');}}}><DialogTitle>Reset password for {reset?.username}</DialogTitle><DialogContent><Stack spacing={2} sx={{pt:1}}>{error&&<Alert severity="error">{error}</Alert>}<TextField label="New password" type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} helperText="Non-empty, up to 128 characters; all sessions will be revoked."/></Stack></DialogContent><DialogActions><Button disabled={busy} onClick={()=>{setReset(undefined);setPassword('');}}>Cancel</Button><Button disabled={busy||!password} onClick={()=>reset&&void action(()=>usersApi.reset(reset.id,password))}>Reset password</Button></DialogActions></Dialog>
    <Dialog open={!!remove} onClose={()=>{if(!busy)setRemove(undefined);}}><DialogTitle>Delete {remove?.username}?</DialogTitle><DialogContent>{error&&<Alert severity="error">{error}</Alert>}Sessions will be revoked. Command, alarm and audit history is retained.</DialogContent><DialogActions><Button disabled={busy} onClick={()=>setRemove(undefined)}>Cancel</Button><Button disabled={busy} color="error" onClick={()=>remove&&void action(()=>usersApi.remove(remove.id))}>Confirm delete</Button></DialogActions></Dialog>
  </Stack>;
}

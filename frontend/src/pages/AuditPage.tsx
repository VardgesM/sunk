import { useEffect, useState } from 'react';
import { Alert, Button, Stack, TextField, Typography } from '@mui/material';
import { usersApi, type Audit } from '../api/users';
export default function AuditPage() {
  const [rows,setRows]=useState<Audit[]>(),[error,setError]=useState(''),[query,setQuery]=useState(''),[offset,setOffset]=useState(0);
  const [user,setUser]=useState(''),[action,setAction]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('');
  useEffect(()=>{let active=true;usersApi.audit(`${query}&offset=${offset}`).then(data=>{if(active){setRows(data);setError('');}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[query,offset]);
  return <Stack spacing={2}><Typography variant="h4" component="h1">Audit</Typography><Typography>Immutable action history. Times are displayed in your local timezone.</Typography>
    <Stack component="form" direction={{xs:'column',md:'row'}} spacing={1} onSubmit={e=>{e.preventDefault();const params=new URLSearchParams();if(user)params.set('user_id',user);if(action)params.set('action',action);if(from)params.set('from',new Date(from).toISOString());if(to)params.set('to',new Date(to).toISOString());setOffset(0);setQuery(params.toString());}}>
      <TextField label="User ID" type="number" value={user} onChange={e=>setUser(e.target.value)}/><TextField label="Action" value={action} onChange={e=>setAction(e.target.value)} helperText="Exact action, e.g. commands.request"/>
      <TextField label="From (local)" type="datetime-local" value={from} onChange={e=>setFrom(e.target.value)} slotProps={{inputLabel:{shrink:true}}}/><TextField label="To (local)" type="datetime-local" value={to} onChange={e=>setTo(e.target.value)} slotProps={{inputLabel:{shrink:true}}}/><Button type="submit">Filter</Button>
    </Stack>{error&&<Alert severity="error">{error}</Alert>}{!rows&&!error&&<Typography>Loading audit...</Typography>}{rows?.length===0&&<Typography>No matching audit records</Typography>}
    {rows?.map(row=><Stack key={row.id} sx={{borderBottom:1,borderColor:'divider',pb:1}}><Typography>{new Date(row.timestamp).toLocaleString()} - {row.username??'Anonymous / system'} - {row.action}</Typography><Typography>{row.entity_type} {row.entity_id??''}: {row.summary}</Typography></Stack>)}
    <Stack direction="row"><Button disabled={!offset} onClick={()=>setOffset(v=>Math.max(0,v-50))}>Previous</Button><Button disabled={!rows||rows.length<50} onClick={()=>setOffset(v=>v+50)}>Next</Button></Stack>
  </Stack>;
}

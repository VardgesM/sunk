import { render } from './render';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SystemPage from '../pages/SystemPage';
import { SourceMode } from '../components/RuntimeStatus';
import { AuthContext } from '../auth/context';
import * as client from '../api/client';
import { activeCommand, type Command } from '../types/commands';
const base={mode:'edge',installation_id:'installation',pending:17,last_sync_at:null,error:null,edges:[]};
describe('Edge / Cloud visibility',()=>{
  it('separates realtime from durable history and control events',async()=>{
    vi.spyOn(client,'request').mockResolvedValue({...base,pending:10010,pending_current:3,pending_history:10000,pending_status:1,pending_commands:2,pending_events:4,pending_metadata:0});
    render(<SystemPage/>);
    expect(await screen.findByText('Realtime pending: 3')).toBeInTheDocument();
    expect(screen.getByText('History pending: 10000')).toBeInTheDocument();
    expect(screen.getByText('Command events pending: 2')).toBeInTheDocument();
    expect(screen.getByText('Alarm / automation events pending: 4')).toBeInTheDocument();
  });
  it('shows offline durable backlog without pretending telemetry stopped',async()=>{
    vi.spyOn(client,'request').mockResolvedValue({...base,error:'Cloud synchronization failed: ConnectError'});
    render(<SystemPage/>);
    expect(await screen.findByText('Pending sync: 17')).toBeInTheDocument();
    expect(screen.getByText('Cloud: UNAVAILABLE')).toBeInTheDocument();
  });
  it('keeps standalone clearly separate',async()=>{
    vi.spyOn(client,'request').mockResolvedValue({...base,mode:'standalone'});
    render(<SystemPage/>);
    expect(await screen.findByText(/Cloud synchronization is disabled/)).toBeInTheDocument();
  });
  it('shows Cloud source instead of pretending there is a local worker',async()=>{
    vi.spyOn(client,'request').mockResolvedValue({application_mode:'cloud',mode:'unknown',alive:false});
    render(<SourceMode/>);
    expect(await screen.findByText(/CLOUD/)).toBeInTheDocument();
    expect(screen.queryByText(/Telemetry worker unavailable/)).not.toBeInTheDocument();
  });
  it('shows offline installations and pending acknowledgement delivery to viewers',async()=>{
    vi.spyOn(client,'request').mockImplementation(async path=>path==='/sync/status'?{...base,mode:'cloud',edges:[{id:'edge-id',name:'Site A',state:'OFFLINE',enabled:true,mode:'modbus',last_seen_at:null}]} as never:[{id:'request-id',kind:'acknowledge',status:'PENDING_EDGE',username:'operator',expires_at:new Date().toISOString(),error:null}] as never);
    render(<AuthContext.Provider value={{user:{id:1,username:'viewer',role:'VIEWER',permissions:['read']},loading:false,login:async()=>{},logout:async()=>{},refresh:async()=>{}}}><SystemPage/></AuthContext.Provider>);
    expect(await screen.findByText('Site A: OFFLINE')).toBeInTheDocument();
    expect(screen.getByText(/acknowledge: PENDING_EDGE/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Machine token')).not.toBeInTheDocument();
  });
  it('registers machine credentials through the protected API and clears the input',async()=>{
    const request=vi.spyOn(client,'request').mockImplementation(async path=>path==='/sync/status'?{...base,mode:'cloud'} as never:[] as never);
    render(<SystemPage/>); const user=userEvent.setup();
    await user.type(await screen.findByLabelText(/Installation UUID/),'8cdd3cbe-3856-4f13-a204-99820a91c402');
    await user.type(screen.getByLabelText(/Edge name/),'Site A');
    const secret='isolated-test-machine-credential-32-characters';
    await user.type(screen.getByLabelText(/Machine token/),secret);
    await user.click(screen.getByRole('button',{name:'Register / rotate'}));
    await waitFor(()=>expect(screen.getByLabelText(/Machine token/)).toHaveValue(''));
    expect(request).toHaveBeenCalledWith('/sync/installations',expect.objectContaining({method:'POST'}));
    expect(localStorage.length).toBe(0);
  });
  it.each(['PENDING_EDGE','DELIVERED'])('prevents repeated control while %s',status=>{
    expect(activeCommand({status} as Command)).toBe(true);
  });
});

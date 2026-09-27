import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import AuthProvider from '../auth/AuthProvider';
import AuthGate from '../auth/AuthGate';
import { AuthContext, type AuthState } from '../auth/context';
import AccountMenu from '../auth/AccountMenu';
import App from '../App';
import UsersPage from '../pages/UsersPage';
import ManualControl from '../components/ManualControl';
import * as client from '../api/client';
import * as commands from '../api/commands';
import { usersApi } from '../api/users';
import type { Tag } from '../types/configuration';
const viewer = {id:1,username:'reader',role:'VIEWER' as const,permissions:['read']};
const state: AuthState = {user:viewer,loading:false,login:async()=>{},logout:async()=>{},refresh:async()=>{}};
vi.mock('../components/HealthStatus',()=>({default:()=>null}));
vi.mock('../components/AlarmIndicator',()=>({default:()=>null}));
vi.mock('../components/RuntimeStatus',()=>({SourceMode:()=>null}));
vi.mock('../components/LiveValues',()=>({LiveValue:()=> <span>OFF</span>}));
vi.mock('../hooks/useRuntime',()=>({useRuntime:()=>({data:{mode:'simulator',alive:true,writes_enabled:false}})}));
vi.mock('../hooks/useCommands',()=>({useCommands:()=>({rows:[],reload:()=>{},loading:false,error:''})}));
const tag: Tag = {id:1,name:'Actuator',key:'actuator',device_id:1,register_type:'coil',address:0,data_type:'bool',byte_order:'big',word_order:'big',scale:1,offset:0,unit:null,poll_interval_ms:1000,writable:true,enabled:true,history_enabled:false,history_mode:'every_sample',history_interval_ms:null,history_change_threshold:null,history_retention_days:null,min_value:null,max_value:null,description:null,created_at:'',updated_at:''};

describe('authentication UI',()=>{
  it('requires login, submits credentials and logs out',async()=>{
    const request=vi.spyOn(client,'request').mockImplementation(async path=>{
      if(path==='/auth/me')throw new client.ApiError(401,'Authentication required');
      if(path==='/auth/login')return viewer as never;
      return undefined as never;
    });
    render(<MemoryRouter initialEntries={['/tags']}><AuthProvider><AuthGate><AccountMenu/><div>Protected content</div></AuthGate></AuthProvider></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'Sign in'})).toBeInTheDocument();
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    const user=userEvent.setup();await user.type(screen.getByLabelText(/Username/),'reader');await user.type(screen.getByLabelText(/Password/),'test-secret-password');await user.click(screen.getByRole('button',{name:'Sign in'}));
    expect(await screen.findByText('Protected content')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/auth/login',expect.objectContaining({method:'POST',body:JSON.stringify({username:'reader',password:'test-secret-password'})}));
    await user.click(screen.getByRole('button',{name:'Logout'}));expect(await screen.findByRole('heading',{name:'Sign in'})).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });
  it('removes protected UI on session expiry',async()=>{
    vi.spyOn(client,'request').mockResolvedValue(viewer);
    render(<MemoryRouter><AuthProvider><AuthGate><div>Protected content</div></AuthGate></AuthProvider></MemoryRouter>);
    await screen.findByText('Protected content');
    act(()=>window.dispatchEvent(new Event('auth-expired')));
    expect(await screen.findByRole('heading',{name:'Sign in'})).toBeInTheDocument();
  });
  it('shows generic login failure',async()=>{
    render(<MemoryRouter initialEntries={['/login']}><AuthContext.Provider value={{...state,user:null,login:async()=>{throw new Error('Invalid username or password');}}}><AuthGate><div/></AuthGate></AuthContext.Provider></MemoryRouter>);
    const user=userEvent.setup();await user.type(screen.getByLabelText(/Username/),'unknown');await user.type(screen.getByLabelText(/Password/),'wrong');await user.click(screen.getByRole('button',{name:'Sign in'}));
    expect(await screen.findByText('Invalid username or password')).toBeInTheDocument();
  });
  it.each(['VIEWER','OPERATOR','ADMIN'] as const)('restricts %s navigation',async role=>{
    const permissions=role==='ADMIN'?['read','configure','users','audit']:['read'];
    render(<MemoryRouter initialEntries={['/settings']}><AuthContext.Provider value={{...state,user:{...viewer,role,permissions}}}><App/></AuthContext.Provider></MemoryRouter>);
    expect(screen.queryByRole('link',{name:'Users'})!==null).toBe(role==='ADMIN');
    expect(screen.queryByRole('link',{name:'Audit'})!==null).toBe(role==='ADMIN');
  });
  it('VIEWER cannot access manual controls',()=>{
    render(<AuthContext.Provider value={state}><ManualControl tag={tag}/></AuthContext.Provider>);
    expect(screen.getByText('Read-only access')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Apply'})).not.toBeInTheDocument();
  });
  it('OPERATOR uses the same command API',async()=>{
    const create=vi.spyOn(commands,'createCommand').mockResolvedValue({id:1,status:'QUEUED',requested_value:true,verified_value:null} as never);
    render(<AuthContext.Provider value={{...state,user:{...viewer,role:'OPERATOR',permissions:['read','command','acknowledge']}}}><ManualControl tag={tag}/></AuthContext.Provider>);
    await userEvent.click(screen.getByRole('combobox',{name:'Requested state'}));await userEvent.click(screen.getByRole('option',{name:'ON'}));await userEvent.click(screen.getByRole('button',{name:'Apply'}));
    await waitFor(()=>expect(create).toHaveBeenCalledWith(1,true,expect.any(String),false));expect(screen.getByText('Actual:',{exact:false})).toHaveTextContent('OFF');
  });
  it('ADMIN manages users without exposing password hashes',async()=>{
    vi.spyOn(usersApi,'list').mockResolvedValue([]);const create=vi.spyOn(usersApi,'create').mockResolvedValue({id:2} as never);
    render(<AuthContext.Provider value={{...state,user:{...viewer,role:'ADMIN',permissions:['read','configure','users','audit']}}}><UsersPage/></AuthContext.Provider>);
    const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'Create user'}));await user.type(screen.getByLabelText(/Username/),'new_user');await user.type(screen.getByLabelText('Initial password'),'initial-test-password');await user.click(screen.getByRole('button',{name:'Save user'}));
    await waitFor(()=>expect(create).toHaveBeenCalledWith(expect.objectContaining({username:'new_user',role:'VIEWER',password:'initial-test-password'})));
    expect(screen.queryByText('password_hash')).not.toBeInTheDocument();
  });
});

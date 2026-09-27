import { request } from './client';
export type Role = 'ADMIN' | 'OPERATOR' | 'VIEWER';
export interface User { id:number; username:string; role:Role; enabled:boolean; last_login_at:string|null; created_at:string; updated_at:string }
export interface UserInput { username:string; role:Role; enabled:boolean; password?:string }
export interface Audit { id:number; timestamp:string; user_id:number|null; username:string|null; action:string; entity_type:string; entity_id:number|null; summary:string }
export const usersApi = {
  list: (offset=0) => request<User[]>(`/users?limit=50&offset=${offset}`),
  create: (body:UserInput) => request<User>('/users',{method:'POST',body:JSON.stringify(body)}),
  edit: (id:number,body:UserInput) => request<User>(`/users/${id}`,{method:'PATCH',body:JSON.stringify(body)}),
  reset: (id:number,password:string) => request<void>(`/users/${id}/password`,{method:'POST',body:JSON.stringify({password})}),
  remove: (id:number) => request<void>(`/users/${id}`,{method:'DELETE'}),
  audit: (query:string) => request<Audit[]>(`/audit?limit=50&${query}`),
};

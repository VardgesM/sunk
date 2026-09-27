import { createContext, useContext } from 'react';
export interface AuthUser { id: number; username: string; role: 'ADMIN' | 'OPERATOR' | 'VIEWER'; permissions: string[] }
export interface AuthState { user: AuthUser | null; loading: boolean; login: (username: string, password: string) => Promise<void>; logout: () => Promise<void>; refresh: () => Promise<void> }
export const AuthContext = createContext<AuthState>({ user: null, loading: true, login: async () => { throw new Error('Authentication unavailable'); }, logout: async () => {}, refresh: async () => {} });
export const useAuth = () => useContext(AuthContext);
export const usePermission = (permission: string) => useAuth().user?.permissions.includes(permission) ?? false;

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { AuthContext, type AuthUser } from './context';
import { ApiError, request } from '../api/client';
import { liveStore } from '../websocket/liveStore';
export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null), [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const invalidate = useCallback(() => { generation.current++; }, []);
  const expire = useCallback(() => { invalidate(); liveStore.reset(); setUser(null); setLoading(false); }, [invalidate]);
  const refresh = useCallback(async () => {
    const version = generation.current;
    try { const result = await request<AuthUser>('/auth/me'); if (version === generation.current) setUser(result); }
    catch (e) { if (version === generation.current && e instanceof ApiError && e.status === 401) expire(); }
    finally { if (version === generation.current) setLoading(false); }
  }, [expire]);
  useEffect(() => {
    const initial = setTimeout(() => { void refresh(); }, 0); window.addEventListener('auth-expired',expire);
    const timer = setInterval(() => { void refresh(); },30000);
    return () => { invalidate(); clearTimeout(initial); clearInterval(timer); window.removeEventListener('auth-expired',expire); };
  }, [expire,refresh,invalidate]);
  async function login(username: string, password: string) {
    const result = await request<AuthUser>('/auth/login',{ method:'POST',body:JSON.stringify({username,password}) });
    generation.current++; liveStore.reset(); setUser(result); setLoading(false);
  }
  async function logout() { await request('/auth/logout',{method:'POST'}); expire(); }
  return <AuthContext.Provider value={{user,loading,login,logout,refresh}}>{children}</AuthContext.Provider>;
}

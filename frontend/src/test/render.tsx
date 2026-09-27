import { render as originalRender, type RenderOptions } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { AuthContext, type AuthState } from '../auth/context';
export const testAuth: AuthState = {user:{id:1,username:'test_admin',role:'ADMIN',permissions:['read','configure','command','acknowledge','users','audit']},loading:false,login:async()=>{},logout:async()=>{},refresh:async()=>{}};
export function render(ui: ReactElement, options?: RenderOptions) {
  return originalRender(ui,{wrapper:({children}:{children:ReactNode})=><AuthContext.Provider value={testAuth}>{children}</AuthContext.Provider>,...options});
}

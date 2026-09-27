import type { ReactNode } from 'react';
import { usePermission } from './context';
export default function Can({ permission, children, fallback = null }: { permission: string; children: ReactNode; fallback?: ReactNode }) {
  return usePermission(permission) ? children : fallback;
}

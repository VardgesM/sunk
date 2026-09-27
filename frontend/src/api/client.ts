import type { HealthResponse } from '../types/health';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const csrf = document.cookie.split('; ').find(item => item.startsWith('mm_csrf='))?.slice('mm_csrf='.length);
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin', ...options, headers: { Accept: 'application/json', ...(csrf && options.method && !['GET','HEAD'].includes(options.method) ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}), ...options.body ? { 'Content-Type': 'application/json' } : {}, ...options.headers },
  });
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('auth-expired'));
    let message = `API request failed (${response.status})`;
    const contentType = response.headers.get('content-type');
    if (contentType?.includes('application/json')) {
      const body: { detail?: string | { loc?: (string | number)[]; msg: string }[] } = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((issue) => `${issue.loc?.slice(1).join('.') || 'Form'}: ${issue.msg}`).join('\n');
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function getHealth(signal: AbortSignal): Promise<HealthResponse> {
  const result = await request<unknown>('/health', { signal });
  if (typeof result !== 'object' || result === null || !('status' in result) || result.status !== 'ok') {
    throw new Error('Unexpected health response');
  }
  return { status: 'ok' };
}

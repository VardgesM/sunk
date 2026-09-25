import { request } from './client';
import type { Command } from '../types/commands';

export const getCommands = (query: string, signal?: AbortSignal) => request<Command[]>(`/commands?${query}`, { signal });
export const createCommand = (tag: number, value: string | boolean, requestId: string, physical: boolean) => request<Command>(`/tags/${tag}/commands`, {
  method: 'POST', body: JSON.stringify({ value, request_id: requestId, confirm_physical: physical }),
});
export const cancelCommand = (id: number) => request<Command>(`/commands/${id}/cancel`, { method: 'POST' });

import { request } from './client';
import type { AlarmInput, AlarmRule, AlarmEvent, Delivery } from '../types/alarms';
export const alarmsApi = {
  rules: () => request<AlarmRule[]>('/alarms/rules?limit=500'),
  create: (value: AlarmInput) => request<AlarmRule>('/alarms/rules', { method: 'POST', body: JSON.stringify(value) }),
  edit: (id: number, value: Partial<AlarmInput>) => request<AlarmRule>(`/alarms/rules/${id}`, { method: 'PATCH', body: JSON.stringify(value) }),
  remove: (id: number) => request<void>(`/alarms/rules/${id}`, { method: 'DELETE' }),
  events: (query = '') => request<AlarmEvent[]>(`/alarms/events?limit=100&${query}`),
  summary: () => request<{ active: number; critical: number }>('/alarms/summary'),
  acknowledge: (id: number) => request<AlarmEvent>(`/alarms/events/${id}/acknowledge`, { method: 'POST' }),
  destination: () => request<{ chat_id: string }>('/notifications/telegram/destination'),
  configure: (chat_id: string) => request<{ chat_id: string }>('/notifications/telegram/destination', { method: 'PATCH', body: JSON.stringify({ chat_id }) }),
  test: () => request<Delivery>('/notifications/telegram/test', { method: 'POST' }),
  deliveries: () => request<Delivery[]>('/notifications/telegram/deliveries'),
};

import { request } from './client';
import type { Execution, Rule, RuleInput } from '../types/automation';
const path = '/automation/rules';
export const automationApi = {
  list: (signal?: AbortSignal) => request<Rule[]>(`${path}?limit=500`, { signal }),
  create: (value: RuleInput) => request<Rule>(path, { method: 'POST', body: JSON.stringify(value) }),
  update: (id: number, value: Partial<RuleInput>) => request<Rule>(`${path}/${id}`, { method: 'PATCH', body: JSON.stringify(value) }),
  remove: (id: number) => request<void>(`${path}/${id}`, { method: 'DELETE' }),
  executions: (id: number, signal?: AbortSignal) => request<Execution[]>(`${path}/${id}/executions`, { signal }),
};

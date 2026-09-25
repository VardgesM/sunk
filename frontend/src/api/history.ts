import { request } from './client';
import type { HistoryResponse } from '../types/history';

export function getHistory(tagId: number, from: string, to: string, signal?: AbortSignal): Promise<HistoryResponse> {
  const params = new URLSearchParams({ from, to, max_points: '1000', limit: '1000' });
  return request<HistoryResponse>(`/tags/${tagId}/history?${params}`, { signal });
}

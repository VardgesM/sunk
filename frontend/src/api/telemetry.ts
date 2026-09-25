import { request } from './client';
import { isCurrentValue, type CurrentValue } from '../types/telemetry';

export async function loadCurrentValues(signal: AbortSignal): Promise<CurrentValue[]> {
  const result: CurrentValue[] = [];
  let after = 0;
  while (true) {
    const page = await request<unknown>(`/tags/values?limit=500&after_tag_id=${after}`, { signal });
    if (!Array.isArray(page) || !page.every(isCurrentValue)) throw new Error('Invalid current-value snapshot');
    result.push(...page);
    if (page.length < 500) return result;
    const next = page[page.length - 1].tag_id;
    if (next <= after) throw new Error('Snapshot pagination did not advance');
    after = next;
  }
}

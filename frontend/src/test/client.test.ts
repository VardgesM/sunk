import { describe, expect, it, vi } from 'vitest';
import { request } from '../api/client';

describe('API client', () => {
  it('formats server validation fields', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ loc: ['body', 'address'], msg: 'Must be nonnegative' }] }), { status: 422, headers: { 'content-type': 'application/json' } })));
    await expect(request('/tags')).rejects.toThrow('address: Must be nonnegative');
  });
  it('supports no-content delete responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request('/tags/1', { method: 'DELETE' })).resolves.toBeUndefined();
  });
});

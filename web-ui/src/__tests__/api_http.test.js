import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from '../api/_http';

describe('api/_http', () => {
  beforeEach(() => { global.fetch = vi.fn(); });

  it('builds query string from params, dropping empty values', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    await get('/api/x', { a: 1, b: '', c: null, d: undefined, e: 'two' });
    expect(global.fetch).toHaveBeenCalledWith('/api/x?a=1&e=two');
  });

  it('throws with status and code on non-ok', async () => {
    global.fetch.mockResolvedValue({
      ok: false, status: 422,
      json: async () => ({ error: 'invalid_root', detail: 'bad path' }),
    });
    await expect(get('/api/scans')).rejects.toMatchObject({
      status: 422, code: 'invalid_root', message: 'bad path',
    });
  });
});

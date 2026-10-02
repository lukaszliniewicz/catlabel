import { afterEach, describe, expect, test, vi } from 'vitest';
import { apiFetch, apiJson } from './apiClient';
import { ApiRequestError } from './apiErrors';

afterEach(() => vi.unstubAllGlobals());

describe('API client', () => {
  test('identifies app requests while preserving caller headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/api/test', { headers: { 'Content-Type': 'application/json' } });
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.get('X-CatLabel-Client')).toBe('1');
    expect(headers.get('Content-Type')).toBe('application/json');
  });
  test('rejects non-success responses with backend detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: { message: 'No printer', stage: 'connect' } }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    )));
    await expect(apiFetch('/api/test')).rejects.toMatchObject({
      name: 'ApiRequestError', message: 'No printer', status: 503, stage: 'connect'
    });
  });

  test('validates decoded JSON payloads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"unexpected":true}', { status: 200 })));
    await expect(apiJson('/api/list', {}, { validate: Array.isArray })).rejects.toBeInstanceOf(ApiRequestError);
  });

  test('times out and aborts stalled requests', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_input, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const request = apiFetch('/api/slow', {}, { timeoutMs: 50 });
    const rejection = expect(request).rejects.toMatchObject({ name: 'ApiRequestError', stage: 'frontend_request' });
    await vi.advanceTimersByTimeAsync(50);
    await rejection;
    vi.useRealTimers();
  });
});

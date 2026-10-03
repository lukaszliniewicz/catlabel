import { afterEach, describe, expect, test, vi } from 'vitest';
import { apiFetch, apiJson } from './apiClient';
import { ApiRequestError } from './apiErrors';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('API client', () => {
  test('identifies app requests while preserving caller headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/api/test', { headers: { 'Content-Type': 'application/json' } });
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.get('X-CatLabel-Client')).toBe('1');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  test('returns successful responses at headers and clears request listeners and timers', async () => {
    vi.useFakeTimers();
    const response = { ok: true, status: 200, text: vi.fn() };
    const controller = new AbortController();
    const addListener = vi.spyOn(controller.signal, 'addEventListener');
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    await expect(apiFetch('/api/test', { signal: controller.signal })).resolves.toBe(response);

    expect(response.text).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    const registeredAbortListener = addListener.mock.calls.find(([type]) => type === 'abort')?.[1];
    expect(registeredAbortListener).toBeDefined();
    expect(removeListener).toHaveBeenCalledWith('abort', registeredAbortListener);
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
    const rejection = expect(request).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 0,
      stage: 'frontend_request',
      message: 'Request timed out after 50 milliseconds.',
    });
    await vi.advanceTimersByTimeAsync(50);
    await rejection;
    expect(vi.getTimerCount()).toBe(0);
  });

  test('times out while consuming a successful JSON body', async () => {
    vi.useFakeTimers();
    const response = {
      ok: true,
      status: 200,
      json: vi.fn(() => new Promise(() => {})),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    const request = apiJson('/api/slow-body', {}, { timeoutMs: 25 });
    const rejection = expect(request).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 0,
      stage: 'frontend_request',
    });
    await vi.advanceTimersByTimeAsync(25);
    await rejection;

    expect(response.json).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  test('times out while parsing a failed response body', async () => {
    vi.useFakeTimers();
    const response = {
      ok: false,
      status: 503,
      text: vi.fn(() => new Promise(() => {})),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    const request = apiFetch('/api/slow-error', {}, { timeoutMs: 25 });
    const rejection = expect(request).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 0,
      stage: 'frontend_request',
    });
    await vi.advanceTimersByTimeAsync(25);
    await rejection;

    expect(response.text).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  test('rejects an already-aborted external signal before calling fetch', async () => {
    const controller = new AbortController();
    const reason = new Error('Caller cancelled the request.');
    controller.abort(reason);
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/api/test', { signal: controller.signal })).rejects.toBe(reason);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('preserves an external abort reason while JSON body consumption is stalled', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const reason = new Error('Caller cancelled while reading the response.');
    let markBodyStarted = () => {};
    const bodyStarted = new Promise((resolve) => {
      markBodyStarted = resolve;
    });
    const response = {
      ok: true,
      status: 200,
      json: vi.fn(() => {
        markBodyStarted();
        return new Promise(() => {});
      }),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    const request = apiJson(
      '/api/cancel-body',
      { signal: controller.signal },
      { timeoutMs: 5000 },
    );
    const rejection = expect(request).rejects.toBe(reason);
    await bodyStarted;
    controller.abort(reason);
    await rejection;

    expect(vi.getTimerCount()).toBe(0);
  });

  test('preserves decoded JSON when validation succeeds', async () => {
    const payload = { labels: 2 };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiJson('/api/test', {}, { validate: (value) => (
      Boolean(value)
      && typeof value === 'object'
      && !Array.isArray(value)
      && 'labels' in value
    ) })).resolves.toEqual(payload);
  });
});

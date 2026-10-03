import React, { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import LocalBatchRenderer from './LocalBatchRenderer';
import { useStore } from '../store';
import * as apiClient from '../utils/apiClient';

const resources = vi.hoisted(() => ({ current: null }));
vi.mock('./HeadlessPage', () => ({ default: props => { resources.current = props; return null; } }));
const original = useStore.getState();
const png = 'data:image/png;base64,' + btoa('PNG fixture');
const id = 'a'.repeat(32);
let root, container, requests, complete;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  resources.current = null; complete = vi.fn(); requests = [];
  useStore.setState({ pendingPrintJob: { id: 1, copies: 1, batchRecords: [{}], pageIndices: [0], canvasState: {} } });
  vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url, options) => {
    requests.push({ url, options });
    if (url === '/api/print/prepared') return { prepared_id: id, total: JSON.parse(options.body).expected_jobs, next_index: 0 };
    if (options.method === 'DELETE') return { status: 'discarded' };
    return { prepared_id: id, total: useStore.getState().pendingPrintJob.pageIndices.length, next_index: Number(url.split('/').at(-1)) + 1 };
  });
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); vi.restoreAllMocks(); });
const mount = async () => act(() => root.render(<LocalBatchRenderer onComplete={complete} />));

test('cancelling preparation rejects stale output without completing a physical submission', async () => {
  await mount(); const late = resources.current.onReady;
  expect(container.querySelector('[role=dialog]')).toBeNull();
  await act(() => root.render(null)); await act(() => late(png));
  expect(complete).not.toHaveBeenCalled();
  expect(requests.filter(x => x.options.method === 'DELETE')).toHaveLength(1);
  expect(requests.some(x => x.url.includes('/pages/'))).toBe(false);
});

test('rendering overlaps one ordered upload and only the final receipt reaches submission', async () => {
  useStore.setState({ pendingPrintJob: { ...useStore.getState().pendingPrintJob, pageIndices: [0, 1] } });
  let release;
  const normal = apiClient.apiJson.getMockImplementation();
  apiClient.apiJson.mockImplementation((url, options) => url.endsWith('/pages/0')
    ? new Promise(resolve => { requests.push({ url, options }); release = () => resolve({ prepared_id: id, total: 2, next_index: 1 }); })
    : normal(url, options));
  await mount(); expect(resources.current.pageIndex).toBe(0);
  const firstReady = resources.current.onReady;
  let pending, successor;
  await act(() => { pending = firstReady(png); });
  expect(resources.current.pageIndex).toBe(1); expect(complete).not.toHaveBeenCalled();
  await act(() => firstReady(png));
  await act(() => { successor = resources.current.onReady(png); });
  expect(requests.filter(x => x.url.includes('/pages/'))).toHaveLength(1);
  await act(async () => { release(); await pending; await successor; });
  expect(resources.current.pageIndex).toBe(1); expect(container.querySelector('[role=dialog]')).toBeNull();
  expect(complete).toHaveBeenCalledWith({ prepared_id: id, total: 2, next_index: 2 }, null, 1);
  for (const request of requests.filter(x => x.url.includes('/pages/'))) {
    expect(request.options.body).toBeInstanceOf(FormData);
    expect(request.options.body.get('file').type).toBe('image/png');
    expect(request.options.body.get('file').size).toBe(11);
  }
  await act(() => root.render(null));
  expect(requests.some(x => x.options.method === 'DELETE')).toBe(false);
});

test('cancellation during upload aborts it and its late acknowledgement cannot submit', async () => {
  let release, uploadSignal;
  const normal = apiClient.apiJson.getMockImplementation();
  apiClient.apiJson.mockImplementation((url, options) => url.includes('/pages/')
    ? new Promise(resolve => { uploadSignal = options.signal; release = resolve; }) : normal(url, options));
  await mount(); let pending;
  await act(() => { pending = resources.current.onReady(png); });
  await act(() => root.render(null));
  expect(uploadSignal.aborted).toBe(true);
  await act(async () => { release({ prepared_id: id, total: 1, next_index: 1 }); await pending; });
  expect(complete).not.toHaveBeenCalled();
});

test('a late creation response is discarded after cancellation before the first render', async () => {
  let release;
  const normal = apiClient.apiJson.getMockImplementation();
  apiClient.apiJson.mockImplementation((url, options) => url === '/api/print/prepared' ? new Promise(resolve => { release = resolve; }) : normal(url, options));
  await mount(); expect(resources.current).toBeNull();
  await act(() => root.render(null));
  await act(() => release({ prepared_id: id, total: 1, next_index: 0 }));
  expect(requests).toEqual([expect.objectContaining({ options: { method: 'DELETE' } })]);
  expect(complete).not.toHaveBeenCalled();
});

test('bad acknowledgement stops preparation and discards its files', async () => {
  const normal = apiClient.apiJson.getMockImplementation();
  apiClient.apiJson.mockImplementation((url, options) => url.includes('/pages/')
    ? Promise.resolve({ prepared_id: id, total: 1, next_index: 0 }) : normal(url, options));
  await mount(); await act(() => resources.current.onReady(png));
  expect(complete.mock.calls[0][0]).toEqual([]); expect(complete.mock.calls[0][1].message).toContain('acknowledgement');
  expect(requests.some(x => x.options.method === 'DELETE')).toBe(true);
});

test('StrictMode replay retains a fresh upload controller and discards the abandoned creation', async () => {
  let creations = 0;
  apiClient.apiJson.mockImplementation(async (url, options) => {
    requests.push({ url, options });
    if (url === '/api/print/prepared') return { prepared_id: (++creations === 1 ? 'b' : 'a').repeat(32), total: 1, next_index: 0 };
    if (options.method === 'DELETE') return { status: 'discarded' };
    expect(options.signal.aborted).toBe(false);
    return { prepared_id: id, total: 1, next_index: 1 };
  });
  await act(() => root.render(<StrictMode><LocalBatchRenderer onComplete={complete} /></StrictMode>));
  await act(() => resources.current.onReady(png));
  expect(complete).toHaveBeenCalledWith({ prepared_id: id, total: 1, next_index: 1 }, null, 1);
  expect(requests.filter(x => x.options.method === 'DELETE').map(x => x.url)).toEqual([`/api/print/prepared/${'b'.repeat(32)}`]);
});

test('a rejected submission callback discards the staged session without repeating submission', async () => {
  complete.mockRejectedValueOnce(new Error('submission callback failed'));
  await mount();
  await act(() => resources.current.onReady(png));
  expect(complete).toHaveBeenCalledOnce();
  expect(requests.filter(request => request.options.method === 'DELETE')).toHaveLength(1);
});


test('cancellation drops a rendered successor waiting behind the current upload', async () => {
  useStore.setState({ pendingPrintJob: { ...useStore.getState().pendingPrintJob, pageIndices: [0, 1, 2] } });
  let release;
  const normal = apiClient.apiJson.getMockImplementation();
  apiClient.apiJson.mockImplementation((url, options) => url.includes('/pages/')
    ? new Promise(resolve => { requests.push({ url, options }); release = resolve; }) : normal(url, options));
  await mount(); let first, successor;
  await act(() => { first = resources.current.onReady(png); });
  expect(resources.current.pageIndex).toBe(1);
  await act(() => { successor = resources.current.onReady(png); });
  expect(resources.current.pageIndex).toBe(1);
  await act(() => root.render(null));
  await act(async () => { release({ prepared_id: id, total: 3, next_index: 1 }); await first; await successor; });
  expect(requests.filter(x => x.url.includes('/pages/'))).toHaveLength(1);
  expect(complete).not.toHaveBeenCalled();
});

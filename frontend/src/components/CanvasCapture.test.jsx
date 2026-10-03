import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import CanvasCapture from './CanvasCapture';
import { useStore } from '../store';
const renderer = vi.hoisted(() => ({ requests: [] }));
vi.mock('./HeadlessPage', () => ({ default: props => { renderer.requests.push(props); return null; } }));
let root, container;
const original = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; vi.useFakeTimers(); renderer.requests = [];
  useStore.setState({ ...original, currentDpi: 300, canvasWidth: 600, canvasHeight: 300, currentPage: 2, batchRecords: [{ name: 'First' }] }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); delete window.__getStageB64; vi.useRealTimers(); useStore.setState(original, true); });
const mount = () => act(() => root.render(<CanvasCapture />));
const start = async () => { let promise; await act(() => { promise = window.__getStageB64(); }); return { promise }; };

test('capture uses a full-resolution versioned snapshot independent of subsequent editor changes', async () => {
  await mount(); const { promise } = await start(); const request = renderer.requests.at(-1);
  expect(request.state).toMatchObject({ document_version: 1, dpi: 300, width: 600, height: 300 });
  expect(request.pageIndex).toBe(2); expect(request.record).toEqual({ name: 'First' });
  await act(() => useStore.getState().setCanvasGeometry(200, 100, false));
  expect(request.state.width).toBe(600);
  await act(() => request.onReady('data:image/png;base64,fixture'));
  await expect(promise).resolves.toBe('data:image/png;base64,fixture');
});
test('a duplicate capture is rejected and stale callbacks cannot resolve the next capture', async () => {
  await mount(); const first = await start(); const outcome = first.promise.catch(error => error); const old = renderer.requests.at(-1);
  await expect(window.__getStageB64()).rejects.toThrow('already in progress');
  await act(() => old.onError(new Error('First render failed')));
  expect((await outcome).message).toBe('First render failed');
  const second = await start(); const next = renderer.requests.at(-1);
  await act(() => old.onReady('stale'));
  expect(renderer.requests.at(-1)).toBe(next);
  await act(() => next.onReady('new capture'));
  await expect(second.promise).resolves.toBe('new capture');
});
test('capture has a deadline, releases its renderer, and accepts a new attempt', async () => {
  await mount(); const first = await start(); const outcome = first.promise.catch(error => error);
  await act(async () => vi.advanceTimersByTimeAsync(90_000));
  expect((await outcome).message).toContain('timed out');
  expect(container.querySelector('[aria-hidden]')).toBeNull();
  const second = await start(); await act(() => renderer.requests.at(-1).onReady('retry'));
  await expect(second.promise).resolves.toBe('retry');
});
test('teardown rejects pending capture and removes only its own global handler', async () => {
  await mount(); const first = await start(); const outcome = first.promise.catch(error => error);
  const replacement = vi.fn(); window.__getStageB64 = replacement;
  await act(() => root.render(null));
  expect((await outcome).message).toContain('cancelled'); expect(window.__getStageB64).toBe(replacement);
});

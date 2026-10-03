import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import HeadlessRenderer from './HeadlessRenderer';
import { useStore } from './store';
const pages = vi.hoisted(() => ({ current: null, mounts: [] }));
vi.mock('./components/HeadlessPage', () => ({ default: props => { pages.current = props; pages.mounts.push(props.pageIndex); return null; } }));
let root, container;
const original = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  pages.current = null; pages.mounts = [];
  useStore.setState({ fetchFonts: () => Promise.resolve(true) });
  window.__INJECTED_PAYLOAD__ = { canvas_state: { width: 384, height: 384, pageLayouts: [{ pageIndex: 0 }, { pageIndex: 1 }] }, stream_output: true };
});
afterEach(async () => {
  await act(() => root.unmount()); container.remove(); useStore.setState(original, true);
  for (const key of ['__INJECTED_PAYLOAD__', '__RENDERED_IMAGES__', '__RENDER_ERROR__', '__CATLABEL_HEADLESS_VERSION__', '__CATLABEL_RENDER_STREAM_VERSION__', '__CATLABEL_RENDER_FRAME__', '__CATLABEL_ACK_RENDER_FRAME__']) delete window[key];
  document.getElementById('render-done')?.remove();
});

test('one immutable frame blocks further rendering until the matching acknowledgement', async () => {
  await act(() => root.render(<HeadlessRenderer />));
  expect(window.__CATLABEL_RENDER_STREAM_VERSION__).toBe(1);
  expect(pages.current.pageIndex).toBe(0);
  await act(() => pages.current.onReady('first'));
  const first = window.__CATLABEL_RENDER_FRAME__;
  const acknowledge = window.__CATLABEL_ACK_RENDER_FRAME__;
  expect(first).toEqual({ index: 0, total: 2, payload: 'first' }); expect(Object.isFrozen(first)).toBe(true);
  expect(window.__RENDERED_IMAGES__).toEqual([]);
  await act(() => pages.current.onReady('duplicate'));
  expect(window.__CATLABEL_RENDER_FRAME__).toBe(first); expect(pages.current.pageIndex).toBe(0);
  await act(() => expect(acknowledge(1)).toBe(false)); expect(pages.current.pageIndex).toBe(0);
  await act(() => expect(acknowledge(0)).toBe(true));
  expect(window.__CATLABEL_RENDER_FRAME__).toBeUndefined(); expect(window.__CATLABEL_ACK_RENDER_FRAME__).toBeUndefined();
  expect(pages.current.pageIndex).toBe(1); expect(acknowledge(0)).toBe(false);
  await act(() => pages.current.onReady('second'));
  expect(window.__CATLABEL_RENDER_FRAME__).toEqual({ index: 1, total: 2, payload: 'second' });
  await act(() => window.__CATLABEL_ACK_RENDER_FRAME__(1));
  expect(document.getElementById('render-done')).not.toBeNull();
  expect(window.__RENDERED_IMAGES__).toEqual([]);
  expect(window.__CATLABEL_RENDER_FRAME__).toBeUndefined(); expect(window.__CATLABEL_ACK_RENDER_FRAME__).toBeUndefined();
});

test('an error clears the pending frame and marks completion without retaining partial output', async () => {
  await act(() => root.render(<HeadlessRenderer />)); await act(() => pages.current.onReady('first'));
  await act(() => pages.current.onError(new Error('broken second resource')));
  expect(window.__RENDER_ERROR__).toBe('broken second resource'); expect(window.__RENDERED_IMAGES__).toEqual([]);
  expect(window.__CATLABEL_RENDER_FRAME__).toBeUndefined(); expect(window.__CATLABEL_ACK_RENDER_FRAME__).toBeUndefined();
  expect(document.getElementById('render-done')).not.toBeNull();
});

test('unmount releases the pending frame and stale acknowledgement cannot advance', async () => {
  await act(() => root.render(<HeadlessRenderer />)); await act(() => pages.current.onReady('first'));
  const acknowledge = window.__CATLABEL_ACK_RENDER_FRAME__;
  await act(() => root.render(null));
  expect(window.__CATLABEL_RENDER_FRAME__).toBeUndefined(); expect(window.__CATLABEL_ACK_RENDER_FRAME__).toBeUndefined();
  expect(acknowledge(0)).toBe(false);
});

test('unnegotiated legacy consumers retain the original ordered result contract', async () => {
  delete window.__INJECTED_PAYLOAD__.stream_output;
  await act(() => root.render(<HeadlessRenderer />));
  await act(() => pages.current.onReady('first'));
  expect(pages.current.pageIndex).toBe(1); expect(window.__CATLABEL_RENDER_FRAME__).toBeUndefined();
  await act(() => pages.current.onReady('second'));
  expect(window.__RENDERED_IMAGES__).toEqual(['first', 'second']);
  expect(document.getElementById('render-done')).not.toBeNull();
});

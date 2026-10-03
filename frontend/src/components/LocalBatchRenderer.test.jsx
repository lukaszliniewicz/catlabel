import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import LocalBatchRenderer from './LocalBatchRenderer';
import { useStore } from '../store';

const resources = vi.hoisted(() => ({ onReady: null }));
vi.mock('./HeadlessPage', () => ({ default: props => { resources.onReady = props.onReady; return null; } }));
let root, container;
const original = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
  useStore.setState({ pendingPrintJob: { id: 1, copies: 1, batchRecords: [{}], pageIndices: [0], canvasState: {} } });
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });

test('cancelling preparation rejects stale output without completing a physical submission', async () => {
  const complete = vi.fn();
  await act(() => root.render(<LocalBatchRenderer onComplete={complete} />));
  expect(container.querySelector('[role=dialog]').getAttribute('aria-modal')).toBe('true');
  await act(() => container.querySelector('button').click());
  expect(complete).toHaveBeenCalledOnce();
  expect(complete.mock.calls[0][0]).toEqual([]);
  expect(complete.mock.calls[0][1].message).toContain('before submission');
  await act(() => root.render(null));
  await act(() => resources.onReady('late image'));
  expect(complete).toHaveBeenCalledOnce();
});

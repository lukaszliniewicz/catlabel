import React, { act, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import LazyFeature from './LazyFeature';

let root, container;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); });

test('pending imports expose cancellable loading instead of a blank overlay', async () => {
  const Pending = lazy(() => new Promise(() => {}));
  const close = vi.fn();
  await act(() => root.render(<LazyFeature label="icons" onClose={close}><Pending /></LazyFeature>));
  expect(container.querySelector('[role=status]').textContent).toBe('Loading icons…');
  expect(container.querySelector('[role=dialog]').getAttribute('aria-modal')).toBe('true');
  await act(() => container.querySelector('button').click());
  expect(close).toHaveBeenCalledOnce();
});

test('rejected imports preserve surrounding editor and expose close/reload recovery', async () => {
  const Broken = lazy(() => Promise.reject(new Error('Missing chunk')));
  const close = vi.fn(), error = vi.fn();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  await act(() => root.render(<><span>Retained editor</span><LazyFeature label="icons" onClose={close} onError={error}><Broken /></LazyFeature></>));
  expect(container.textContent).toContain('Retained editor');
  expect(container.querySelector('[role=alert]').textContent).toContain('icons could not be opened');
  expect(error).toHaveBeenCalledOnce();
  expect([...container.querySelectorAll('button')].map(button => button.textContent)).toEqual(['Close', 'Reload app']);
  await act(() => container.querySelector('button').click());
  expect(close).toHaveBeenCalledOnce();
});

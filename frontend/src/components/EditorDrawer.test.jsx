import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import EditorDrawer from './EditorDrawer';
import { useStore } from '../store';
let root, container;
const original = useStore.getState();
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });

test('narrow breakpoints close panels and mutually exclusive drawers preserve choices within a breakpoint', () => {
  useStore.getState().setLayoutViewport(true);
  expect(useStore.getState()).toMatchObject({ isSidebarCollapsed: true, isPropertiesOpen: false });
  useStore.getState().toggleSidebar();
  useStore.getState().setLayoutViewport(true);
  expect(useStore.getState()).toMatchObject({ isSidebarCollapsed: false, isPropertiesOpen: false });
  useStore.getState().toggleProperties();
  expect(useStore.getState()).toMatchObject({ isSidebarCollapsed: true, isPropertiesOpen: true });
  useStore.getState().setLayoutViewport(false);
  expect(useStore.getState()).toMatchObject({ isSidebarCollapsed: false, isPropertiesOpen: true });
  useStore.getState().setLayoutViewport(true);
  expect(useStore.getState()).toMatchObject({ isSidebarCollapsed: true, isPropertiesOpen: false });
});
test('drawer exposes Escape and explicit close', async () => {
  const close = vi.fn();
  await act(() => root.render(<EditorDrawer label="Properties" onClose={close}><input aria-label="Paper length" /></EditorDrawer>));
  expect(container.querySelector('[role=dialog]').getAttribute('aria-modal')).toBe('true');
  await act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })));
  expect(close).toHaveBeenCalledOnce();
  await act(() => container.querySelector('button').click());
  expect(close).toHaveBeenCalledTimes(2);
});

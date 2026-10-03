import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import ConfirmActionDialog from './ConfirmActionDialog';
import ProjectActionsDialog from './ProjectActionsDialog';
import EditorDrawer from './EditorDrawer';
let root, container, trigger;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  container = document.createElement('div'); trigger = document.createElement('button');
  document.body.append(trigger, container); trigger.focus(); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); trigger.remove(); vi.useRealTimers(); });
const key = value => act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })));
test('confirmation defaults to cancel, contains focus and cannot dismiss while busy', async () => {
  const close = vi.fn(), confirm = vi.fn();
  const render = busy => act(() => root.render(<ConfirmActionDialog title="Delete saved project?" message="The canvas stays." actionLabel="Delete" busy={busy} error={busy ? '' : 'Try again'} onClose={close} onConfirm={confirm} />));
  await render(false); await act(() => vi.advanceTimersByTime(20));
  const dialog = document.querySelector('[role=dialog]');
  expect(document.activeElement.textContent).toBe('Cancel');
  expect(dialog.querySelector('[role=alert]').textContent).toBe('Try again');
  expect(container.hasAttribute('inert')).toBe(true);
  trigger.focus(); expect(dialog.contains(document.activeElement)).toBe(true);
  await key('Escape'); expect(close).toHaveBeenCalledOnce(); expect(confirm).not.toHaveBeenCalled();
  await render(true); expect([...dialog.querySelectorAll('button')].every(button => button.disabled)).toBe(true);
  await key('Escape'); expect(close).toHaveBeenCalledOnce();
  await act(() => root.render(null)); expect(container.hasAttribute('inert')).toBe(false); expect(document.activeElement).toBe(trigger);
});
test('portal actions own nested drawer focus and preserve drawer background on close', async () => {
  const render = open => act(() => root.render(<EditorDrawer label="Projects" onClose={() => {}}><button>Drawer action</button>{open && <ProjectActionsDialog name="Saved" coordinates={{ top: 50, left: 8 }} onClose={() => {}}><button>Export JSON</button></ProjectActionsDialog>}</EditorDrawer>));
  await render(false); await act(() => vi.advanceTimersByTime(20));
  await render(true); await act(() => vi.advanceTimersByTime(20));
  const portal = document.querySelector('[aria-label="Actions for Saved"]');
  expect(document.activeElement.textContent).toBe('Close actions');
  expect(container.hasAttribute('inert')).toBe(true);
  await render(false); expect(container.hasAttribute('inert')).toBe(false);
  expect(trigger.hasAttribute('inert')).toBe(true);
  expect(container.querySelector('[role=dialog]')).not.toBeNull();
  expect(portal.isConnected).toBe(false);
});

test('explicit action trigger wins over an incidental connected focus target', async () => {
  const incidental = document.createElement('button'); document.body.append(incidental); incidental.focus();
  await act(() => root.render(<ConfirmActionDialog title="Overwrite?" message="Review this action." actionLabel="Overwrite" onClose={() => {}} onConfirm={() => {}} returnFocusRef={{ current: trigger }} />));
  await act(() => root.render(null)); expect(document.activeElement).toBe(trigger); incidental.remove();
});

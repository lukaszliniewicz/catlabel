import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import ProjectSwitchDialog from './ProjectSwitchDialog';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';
import { useStore } from '../store';

const original = useStore.getState();
let root, container, trigger;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  trigger = document.createElement('button');
  trigger.textContent = 'Open project';
  document.body.append(trigger, container);
  trigger.focus();
  root = createRoot(container);
  useStore.setState(original, true);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove(); trigger.remove();
  useStore.setState(original, true);
  vi.restoreAllMocks();
});

function GuardHost() {
  const pending = useStore(state => state.pendingProjectLoad);
  return pending ? <ProjectSwitchDialog /> : null;
}

test('Keep editing and Escape preserve edits, restore focus and uncover background', async () => {
  useStore.getState().setItems([{ id: 'kept', type: 'text' }]);
  await useStore.getState().loadProject({ id: 2, name: 'Other' });
  await act(() => root.render(<GuardHost />));
  expect(container.querySelector('[role=dialog]').textContent).toContain('Other');
  expect(trigger.hasAttribute('inert')).toBe(true);
  await act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Keep editing').click());
  expect(useStore.getState().items[0].id).toBe('kept');
  expect(container.querySelector('[role=dialog]')).toBeNull();
  expect(trigger.hasAttribute('inert')).toBe(false);
  expect(document.activeElement).toBe(trigger);
  await act(() => useStore.getState().loadProject({ id: 2 }));
  await act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })));
  expect(useStore.getState().pendingProjectLoad).toBeNull();
  expect(useStore.getState().items[0].id).toBe('kept');
});

test('explicit discard opens the requested document and resets history', async () => {
  useStore.getState().setItems([{ id: 'old', type: 'text' }]);
  await useStore.getState().loadProject({ id: 2, revision: 3, name: 'Other', canvas_state: { items: [{ id: 'new', type: 'text' }] } });
  await act(() => root.render(<GuardHost />));
  await act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Discard edits and open').click());
  expect(useStore.getState()).toMatchObject({ currentProjectId: 2, currentProjectRevision: 3, isDocumentDirty: false, history: [] });
  expect(useStore.getState().items[0].id).toBe('new');
});

function Modal({ children }) {
  const ref = useDialogAccessibility(() => {});
  return <div ref={ref} role="dialog" tabIndex={-1}><button>Inside</button>{children}</div>;
}

test('nested modal cleanup keeps the remaining dialog background inert and preserves preexisting inertness', async () => {
  const alreadyCovered = document.createElement('div');
  alreadyCovered.setAttribute('inert', '');
  document.body.append(alreadyCovered);
  await act(() => root.render(<><Modal /><Modal /></>));
  expect(trigger.hasAttribute('inert')).toBe(true);
  await act(() => root.render(<><Modal /></>));
  expect(trigger.hasAttribute('inert')).toBe(true);
  await act(() => root.render(null));
  expect(trigger.hasAttribute('inert')).toBe(false);
  expect(alreadyCovered.hasAttribute('inert')).toBe(true);
  alreadyCovered.remove();
});

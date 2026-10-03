import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test } from 'vitest';
import CanvasObjectList from './CanvasObjectList';
import { useStore } from '../../store';
let root, container;
const original = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  useStore.setState({ ...original, items: [
    { id: 'legacy', type: 'text', text: 'Legacy label' },
    { id: 'group', type: 'group', pageIndex: 0, children: [{ id: 'inside', type: 'text', text: 'Grouped' }] },
    { id: 'other-page', type: 'image', pageIndex: 1 }
  ], currentPage: 0, selectedId: null, selectedIds: [] }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });
const buttons = () => [...container.querySelectorAll('[role="toolbar"] button')];
const key = async (button, value, shiftKey = false) => act(() => button.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true })));

test('only current-page objects appear; groups are selectable as one object', async () => {
  await act(() => root.render(<CanvasObjectList />));
  expect(buttons().map(button => button.textContent)).toEqual(['Text: Legacy label', 'Group: 1 grouped objects']);
  expect(buttons().filter(button => button.tabIndex === 0)).toHaveLength(1);
  await act(() => buttons()[1].click());
  expect(useStore.getState().selectedIds).toEqual(['group']);
  expect(buttons()[1].getAttribute('aria-pressed')).toBe('true');
  await act(() => useStore.setState({ currentPage: 1 }));
  expect(buttons().map(button => button.textContent)).toEqual(['Image']);
});
test('arrow/Home/End navigation and Enter/Shift+Space selection do not mutate the document', async () => {
  await act(() => root.render(<CanvasObjectList />));
  const revision = useStore.getState().documentRevision;
  buttons()[0].focus();
  await key(buttons()[0], 'ArrowDown'); expect(document.activeElement).toBe(buttons()[1]);
  await key(buttons()[1], 'Enter'); expect(useStore.getState().selectedIds).toEqual(['group']);
  await key(buttons()[1], 'Home'); expect(document.activeElement).toBe(buttons()[0]);
  await key(buttons()[0], ' ', true); expect(useStore.getState().selectedIds).toEqual(['group', 'legacy']);
  await key(buttons()[0], ' ', true); expect(useStore.getState().selectedIds).toEqual(['group']);
  await key(buttons()[0], 'End'); expect(document.activeElement).toBe(buttons()[1]);
  expect(useStore.getState().documentRevision).toBe(revision);
});
test('empty pages and explicit deselection expose meaningful controls', async () => {
  await act(() => root.render(<CanvasObjectList />));
  await act(() => buttons()[0].click());
  await act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Clear object selection').click());
  expect(useStore.getState().selectedIds).toEqual([]);
  await act(() => useStore.setState({ currentPage: 3 }));
  expect(container.textContent).toContain('No objects on this label');
});

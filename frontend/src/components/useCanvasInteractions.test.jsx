import React, { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test } from 'vitest';
import useCanvasInteractions from './useCanvasInteractions';
import { useStore } from '../store';
let root, container, interactions;
const original = useStore.getState();
function Harness({ isPanning = false }) {
  const state = useStore();
  const current = useCanvasInteractions({ ...state, isPanning });
  useEffect(() => { interactions = current; }, [current]);
  return <output>{current.snapLines.length}</output>;
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  useStore.setState({ ...original, canvasWidth: 400, canvasHeight: 400, currentPage: 0,
    items: [{ id: 'dragged', type: 'shape', x: 20, y: 60, width: 20, height: 20 },
      { id: 'legacy', type: 'shape', x: 40, y: 80, width: 50, height: 40 },
      { id: 'other-page', type: 'shape', pageIndex: 1, x: 45, y: 85, width: 50, height: 40 }], selectedId: null, selectedIds: [] }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });
test('drag snapping includes legacy page-zero objects and excludes objects from other pages', async () => {
  await act(() => root.render(<Harness />));
  let position;
  const target = { x: () => 43, y: () => 83, position: next => { position = next; } };
  await act(() => interactions.handleDragMove({ target }, useStore.getState().items[0]));
  expect(position).toEqual({ x: 40, y: 80 });
  expect(interactions.snapLines.length).toBeGreaterThan(0);
  await act(() => interactions.handleDragEnd({ target: { x: () => 40, y: () => 80 } }, useStore.getState().items[0]));
  expect(useStore.getState().items[0]).toMatchObject({ x: 40, y: 80 });
  expect(interactions.snapLines).toEqual([]);
});
test('pointer selection normalizes legacy pages and stays unchanged while panning', async () => {
  await act(() => root.render(<Harness />));
  const event = { evt: { shiftKey: true }, cancelBubble: false };
  await act(() => interactions.handleItemPointerDown(event, useStore.getState().items[1]));
  expect(event.cancelBubble).toBe(true); expect(useStore.getState().selectedIds).toEqual(['legacy']);
  await act(() => root.render(<Harness isPanning />));
  await act(() => interactions.handleItemPointerDown({ evt: {} }, useStore.getState().items[0]));
  expect(useStore.getState().selectedIds).toEqual(['legacy']);
});

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test } from 'vitest';
import useCanvasKeyboard from './useCanvasKeyboard';
import { useStore } from '../store';
let root, container;
const original = useStore.getState();
const Harness = () => <><output>{useCanvasKeyboard() ? 'Panning' : 'Idle'}</output><input aria-label="Text" /><button>Object selection</button></>;
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); useStore.setState({ ...original, items: [{ id: 'selected', type: 'text', x: 5, y: 10, text: 'Keep' }], selectedId: 'selected', selectedIds: ['selected'] }, true); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });
const key = async (target, value, options = {}) => act(() => target.dispatchEvent(new KeyboardEvent('keydown', { key: value, code: value === ' ' ? 'Space' : '', bubbles: true, cancelable: true, ...options })));
test('canvas arrows move selected objects while editable and button targets keep their own keyboard behavior', async () => {
  await act(() => root.render(<Harness />));
  await key(window, 'ArrowRight'); expect(useStore.getState().items[0].x).toBe(6);
  await key(window, 'ArrowDown', { shiftKey: true }); expect(useStore.getState().items[0].y).toBe(20);
  await key(container.querySelector('input'), 'Delete');
  await key(container.querySelector('button'), 'ArrowRight');
  expect(useStore.getState().items[0]).toMatchObject({ x: 6, y: 20 });
});
test('pan mode ends when the window loses focus and does not start from form controls', async () => {
  await act(() => root.render(<Harness />));
  await key(window, ' '); expect(container.querySelector('output').textContent).toBe('Panning');
  await act(() => window.dispatchEvent(new Event('blur'))); expect(container.querySelector('output').textContent).toBe('Idle');
  await key(container.querySelector('input'), ' '); expect(container.querySelector('output').textContent).toBe('Idle');
  await key(window, ' '); await act(() => window.dispatchEvent(new KeyboardEvent('keyup', { code: 'Space' })));
  expect(container.querySelector('output').textContent).toBe('Idle');
});

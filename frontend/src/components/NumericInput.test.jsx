import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { MmScrubberInput, ScrubberInput } from './NumericInput';
import { useStore } from '../store';
let root, container;
const original = useStore.getState();
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });
const pointer = (type, values) => {
  const event = new Event(type, { bubbles: true });
  Object.assign(event, { pointerType: 'touch', pointerId: 1, button: 0, ...values });
  return act(() => container.querySelector('label').dispatchEvent(event));
};
test('numeric controls associate labels and preserve mm-to-pixel conversion', async () => {
  useStore.setState({ currentDpi: 203 });
  const change = vi.fn();
  await act(() => root.render(<MmScrubberInput name="width" label="Paper width" value={203} onChange={change} />));
  const input = container.querySelector('input');
  expect(input.labels[0].textContent).toContain('Paper width (mm)');
  expect(input.value).toBe('25.4');
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '12.7');
  await act(() => input.dispatchEvent(new Event('input', { bubbles: true })));
  expect(change.mock.calls[0][0].target).toEqual({ name: 'width', type: 'number', value: useStore.getState().getMmToPx(12.7) });
});
test('touch drag is pointer-owned, cancels cleanly and ignores another pointer', async () => {
  const change = vi.fn();
  await act(() => root.render(<ScrubberInput name="size" label="Text size" value={10} onChange={change} />));
  await pointer('pointerdown', { clientX: 10 });
  await pointer('pointermove', { clientX: 20, pointerId: 2 });
  expect(change).not.toHaveBeenCalled();
  await pointer('pointermove', { clientX: 20 });
  expect(change.mock.calls[0][0].target.value).toBe(15);
  await pointer('pointercancel', { clientX: 20 });
  await pointer('pointermove', { clientX: 30 });
  expect(change).toHaveBeenCalledOnce();
});
test('disabled controls cannot begin a scrub', async () => {
  const change = vi.fn();
  await act(() => root.render(<MmScrubberInput name="width" label="Width" value={203} disabled onChange={change} />));
  await pointer('pointerdown', { clientX: 10 }); await pointer('pointermove', { clientX: 20 });
  expect(change).not.toHaveBeenCalled();
  expect(container.querySelector('input').disabled).toBe(true);
});

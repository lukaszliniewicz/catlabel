import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import IconPicker from './IconPicker';

test('icon results stay bounded and searching resets pagination without aliases', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(() => root.render(<IconPicker onClose={vi.fn()} onSelect={vi.fn()} />));
    const dialog = document.querySelector('[role=dialog]');
    const results = () => [...dialog.querySelectorAll('button[title]')];
    expect(results()).toHaveLength(80);
    expect(results().every(button => !button.title.endsWith('Icon'))).toBe(true);
    const first = results()[0].title;
    await act(() => [...dialog.querySelectorAll('button')].find(button => button.textContent === 'Next').click());
    expect(results()).toHaveLength(80);
    expect(results()[0].title).not.toBe(first);
    const search = dialog.querySelector('input');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'cat');
    await act(() => search.dispatchEvent(new Event('input', { bubbles: true })));
    expect(dialog.querySelector('[role=status]').textContent).toContain('Page 1 of');
    expect(results().length).toBeLessThanOrEqual(80);
    expect(results().some(button => button.title === 'Cat')).toBe(true);
    expect(results().every(button => button.title.toLowerCase().includes('cat'))).toBe(true);
  } finally {
    await act(() => root.unmount());
    container.remove();
  }
});

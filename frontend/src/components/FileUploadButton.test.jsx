import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import FileUploadButton from './FileUploadButton';
let root, container;
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); });
test('a named native button activates the file input and keeps the input change contract', async () => {
  const onChange = vi.fn();
  const open = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
  await act(() => root.render(<FileUploadButton label="Import project package" accept=".json" onChange={onChange} />));
  const button = container.querySelector('button'), input = container.querySelector('input');
  expect(button.type).toBe('button'); expect(button.getAttribute('aria-label')).toBe('Import project package'); expect(input.hidden).toBe(true);
  button.focus(); expect(document.activeElement).toBe(button);
  await act(() => button.click()); expect(open).toHaveBeenCalledOnce();
  await act(() => input.dispatchEvent(new Event('change', { bubbles: true }))); expect(onChange.mock.calls[0][0].target).toBe(input);
});

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import Toolbar from './Toolbar';
import { useStore } from '../store';
import * as apiClient from '../utils/apiClient';

let root, container, readers, images;
const original = useStore.getState();
const png = 'data:image/png;base64,iVBORw0KGgo=';
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  readers = []; images = [];
  vi.useFakeTimers();
  vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ templates: [] }) });
  vi.stubGlobal('FileReader', class {
    readyState = 0;
    readAsDataURL() { this.readyState = 1; readers.push(this); }
    abort() { this.readyState = 2; this.aborted = true; this.onabort?.(); }
    complete() { this.readyState = 2; this.result = png; this.onload?.(); }
  });
  vi.stubGlobal('Image', class {
    naturalWidth = 200;
    naturalHeight = 100;
    set src(value) { this.source = value; if (value) images.push(this); }
    get src() { return this.source; }
  });
  useStore.setState({ ...original, items: [], selectedId: null, selectedIds: [], canvasWidth: 100, currentPage: 2 }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
  useStore.setState(original, true);
});
const mount = () => act(() => root.render(<Toolbar />));
const choose = async (kind, file = new File(['fixture'], kind === 'pdf' ? 'fixture.pdf' : 'fixture.png')) => {
  const input = container.querySelector(`input[accept="${kind === 'pdf' ? 'application/pdf' : 'image/*'}"]`);
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
};
const load = async index => act(() => images[index].onload?.());

test('PDF pages commit atomically on the captured page after all images decode', async () => {
  const json = vi.spyOn(apiClient, 'apiJson').mockResolvedValue({ images: [png, png] });
  await mount(); const revision = useStore.getState().documentRevision;
  await choose('pdf');
  expect(container.querySelector('[aria-label="Upload Image"]').disabled).toBe(true);
  expect(useStore.getState().items).toEqual([]);
  await load(0); expect(useStore.getState().items).toEqual([]);
  await load(1);
  expect(useStore.getState().items).toMatchObject([{ pageIndex: 2, width: 100, height: 50, y: 0 }, { pageIndex: 2, width: 100, height: 50, y: 60 }]);
  expect(useStore.getState().documentRevision).toBe(revision + 1);
  expect(new Set(useStore.getState().items.map(item => item.id)).size).toBe(2);
  expect(images.every(image => image.src === '')).toBe(true);
  expect(container.textContent).toContain('2 images imported.');
  expect(json.mock.calls[0][2].timeoutMs).toBe(120_000);
  const validate = json.mock.calls[0][2].validate;
  expect(validate({ images: [png] })).toBe(true);
  expect(validate({ images: [] })).toBe(false);
  expect(validate({ images: ['https://example.com/image.png'] })).toBe(false);
});

test('a later PDF decode failure leaves the canvas untouched and releases images', async () => {
  vi.spyOn(apiClient, 'apiJson').mockResolvedValue({ images: [png, png] });
  await mount(); await choose('pdf'); await load(0);
  await act(() => images[1].onerror());
  expect(useStore.getState().items).toEqual([]);
  expect(container.querySelector('[role="alert"]').textContent).toContain('could not be decoded');
  expect(images.every(image => image.src === '')).toBe(true);
});

test('a different document cancels pending conversion and rejects a noncooperative late response', async () => {
  let resolve;
  const json = vi.spyOn(apiClient, 'apiJson').mockImplementation(() => new Promise(done => { resolve = done; }));
  await mount(); await choose('pdf');
  await act(() => useStore.getState().hydrateCanvasState({ document_version: 1, dpi: 203, width: 250, height: 125, items: [] }, { resetHistory: true }));
  expect(json.mock.calls[0][1].signal.aborted).toBe(true);
  await act(() => resolve({ images: [png] }));
  expect(useStore.getState().items).toEqual([]); expect(images).toEqual([]);
  expect(container.querySelector('[role="alert"]').textContent).toContain('design changed');
});

test.each(['edit', 'page'])('an intervening %s cancels image preparation and preserves the current state', async kind => {
  await mount(); await choose('image'); await act(() => readers[0].complete());
  const late = images[0].onload;
  await act(() => kind === 'edit' ? useStore.getState().addItem({ id: 'keep', type: 'text', text: 'Keep this' }) : useStore.setState({ currentPage: 3 }));
  expect(images[0].src).toBe('');
  await act(() => late());
  expect(useStore.getState().items.length).toBe(kind === 'edit' ? 1 : 0);
  if (kind === 'edit') expect(useStore.getState().items[0].id).toBe('keep');
  expect(container.querySelector('[role="alert"]').textContent).toContain('design changed');
});

test('explicit cancellation aborts reading, releases busy state and permits another import', async () => {
  await mount(); await choose('image');
  await act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Cancel import').click());
  expect(readers[0].aborted).toBe(true);
  expect(container.querySelector('[role="alert"]').textContent).toContain('cancelled');
  await choose('image'); await act(() => readers[1].complete()); await load(0);
  expect(useStore.getState().items).toHaveLength(1);
});

test('an image that never loads times out without partial changes', async () => {
  await mount(); await choose('image'); await act(() => readers[0].complete());
  await act(async () => vi.advanceTimersByTimeAsync(8_000));
  expect(useStore.getState().items).toEqual([]);
  expect(images[0].src).toBe('');
  expect(container.querySelector('[role="alert"]').textContent).toContain('timed out');
});

test('unmount aborts the owned reader and a late callback cannot modify the document', async () => {
  await mount(); await choose('image'); const late = readers[0].onload;
  await act(() => root.render(null));
  expect(readers[0].aborted).toBe(true);
  readers[0].result = png; await act(() => late());
  expect(useStore.getState().items).toEqual([]); expect(images).toEqual([]);
});

test('oversized image files are rejected before reading', async () => {
  const file = new File(['fixture'], 'large.png'); Object.defineProperty(file, 'size', { value: 8 * 1024 * 1024 + 1 });
  await mount(); await choose('image', file);
  expect(readers).toEqual([]);
  expect(container.querySelector('[role="alert"]').textContent).toContain('8 MiB');
});

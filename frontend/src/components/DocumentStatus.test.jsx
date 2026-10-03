import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { useStore } from '../store';
import DocumentStatus from './DocumentStatus';
import { serializeCanvasDocument } from '../domain/document';

let root;
let container;
const original = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  useStore.setState(original, true);
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  useStore.setState(original, true);
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const mount = () => act(() => root.render(<DocumentStatus open onClose={() => {}} />));
const click = text => act(() => [...container.querySelectorAll('button')].find(button => button.textContent === text).click());

test('draft recovery creates an unsaved copy and does not retain ancestor write identity', async () => {
  const canvas = serializeCanvasDocument({ ...original, items: [{ id: 'recovered', type: 'text', text: 'Keep me' }] });
  localStorage.setItem('catlabel_document_draft_v1', JSON.stringify({ draft_schema: 1,
    project_id: 42, project_revision: 2, canvas_state: canvas }));
  await mount();
  await click('Recover as new design');
  expect(useStore.getState()).toMatchObject({ currentProjectId: null, currentProjectRevision: null,
    isDocumentDirty: true, items: [{ id: 'recovered', text: 'Keep me' }] });
  expect(container.textContent).toContain('Recovered as a new unsaved design');
  expect(JSON.parse(localStorage.getItem('catlabel_document_draft_v1')).project_id).toBeNull();
});

test('new edits cannot replace a pending recovery copy and malformed copies keep the editor', async () => {
  vi.useFakeTimers();
  localStorage.setItem('catlabel_document_draft_v1', '{broken');
  await mount();
  await act(() => useStore.getState().setItems([{ id: 'fresh', type: 'text' }]));
  await act(() => vi.advanceTimersByTime(600));
  expect(localStorage.getItem('catlabel_document_draft_v1')).toBe('{broken');
  expect(container.textContent).toContain('could not be read');
  await click('Discard recovery copy');
  expect(JSON.parse(localStorage.getItem('catlabel_document_draft_v1')).canvas_state.items[0].id).toBe('fresh');
});

test('storage failure keeps unsaved edits visible and unload protects them', async () => {
  vi.useFakeTimers();
  await mount();
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage full. Save your project.'); });
  await act(() => useStore.getState().setItems([{ id: 'kept', type: 'text' }]));
  await act(() => vi.advanceTimersByTime(600));
  expect(container.textContent).toContain('Storage full');
  expect(container.textContent).toContain('Unsaved changes');
  const event = new Event('beforeunload', { cancelable: true });
  await act(() => window.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  expect(useStore.getState().items[0].id).toBe('kept');
});

test('dirty recovery requires explicit replacement and fences later edits', async () => {
  const canvas = serializeCanvasDocument({ ...original, items: [{ id: 'recovered', type: 'text' }] });
  localStorage.setItem('catlabel_document_draft_v1', JSON.stringify({ draft_schema: 1, canvas_state: canvas }));
  useStore.getState().setItems([{ id: 'kept', type: 'text' }]);
  await mount(); await click('Recover as new design');
  const choice = text => act(() => [...document.querySelectorAll('[role=dialog] button')].find(button => button.textContent === text).click());
  await choice('Keep editing'); expect(useStore.getState().items[0].id).toBe('kept');
  await click('Recover as new design'); await act(() => useStore.getState().setItems([{ id: 'later', type: 'text' }]));
  await choice('Replace edits and recover'); expect(useStore.getState().items[0].id).toBe('later');
  expect(container.textContent).toContain('changed while confirmation');
  await click('Recover as new design'); await choice('Replace edits and recover');
  expect(useStore.getState()).toMatchObject({ currentProjectId: null, items: [{ id: 'recovered' }], isDocumentDirty: true });
});

test('print receipts remain visible with physical completion explicitly unverified', async () => {
  useStore.setState({ lastPrintReceipt: { status: 'submitted', submitted: 2, physical_completion: 'unverified' } });
  await mount(); expect(container.textContent).toContain('2 labels submitted'); expect(container.textContent).toContain('completion is unverified');
  await act(() => useStore.setState({ isPrinting: true })); expect(container.textContent).toContain('Submitting labels');
});

test('closing Status keeps draft persistence and unsaved unload protection active', async () => {
  vi.useFakeTimers();
  const attention = vi.fn();
  await act(() => root.render(<DocumentStatus onAttentionChange={attention} />));
  expect(document.querySelector('[role=dialog]')).toBeNull();
  await act(() => useStore.getState().setItems([{ id: 'closed-panel-edit', type: 'text' }]));
  await act(() => vi.advanceTimersByTime(600));
  expect(JSON.parse(localStorage.getItem('catlabel_document_draft_v1')).canvas_state.items[0].id).toBe('closed-panel-edit');
  const event = new Event('beforeunload', { cancelable: true });
  await act(() => window.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  await act(() => useStore.setState({ saveStatus: 'failed' }));
  expect(attention).toHaveBeenLastCalledWith(true);
});

test('Status cancels preparation through the guarded job callback before physical submission', async () => {
  const pending = { id: 88 };
  useStore.setState({ pendingPrintJob: pending, isPreparingForPrint: true,
    printPreparationProgress: { completed: 1, total: 5 } });
  await mount();
  expect(container.querySelector('progress').value).toBe(1);
  await click('Cancel preparation');
  expect(useStore.getState()).toMatchObject({ pendingPrintJob: null, isPreparingForPrint: false,
    isPrinting: false, printPreparationProgress: null });
  expect(useStore.getState().apiError).toContain('cancelled before submission');
});

test('external revision notice preserves dirty canvas and undo history', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 42, revision: 3 }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
  useStore.setState({ currentProjectId: 42, currentProjectRevision: 2 });
  useStore.getState().setItems([{ id: 'local-edit', type: 'text', text: 'Keep this' }]);
  const before = useStore.getState();
  await mount();
  expect(container.textContent).toContain('changed outside the editor');
  expect(useStore.getState().items).toBe(before.items);
  expect(useStore.getState().history).toBe(before.history);
  expect(useStore.getState().currentProjectRevision).toBe(2);
  expect(useStore.getState().isDocumentDirty).toBe(true);
  vi.unstubAllGlobals();
});

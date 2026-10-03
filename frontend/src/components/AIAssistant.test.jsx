import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import AIAssistant from './AIAssistant';
import { useStore } from '../store';
const api = vi.hoisted(() => ({ handler: null, json: vi.fn() }));
vi.mock('../utils/apiClient', async importOriginal => ({ ...await importOriginal(), apiJson: api.json }));
let root, container;
const original = useStore.getState();
const canvas = (extra = {}) => ({ document_version: 1, dpi: 203, width: 384, height: 384,
  items: [{ id: 'new-text', type: 'text', text: 'AI result', x: 0, y: 0, size: 24 }], pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: null }], ...extra });
const chat = extra => ({ new_messages: [{ role: 'assistant', content: 'Reply received' }], canvas_state: canvas(extra), usage: { total_tokens: 10, prompt_tokens: 6, completion_tokens: 4, cost: 0.001 } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const settle = () => act(async () => {});
const click = async selector => { await act(() => container.querySelector(selector).click()); await settle(); };
const clickText = async text => { await act(() => [...container.querySelectorAll('button')].find(button => button.textContent.trim() === text).click()); await settle(); };
const send = async () => { await act(() => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); await settle(); };
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  api.json.mockReset();
  api.handler = url => url === '/api/ai/history' ? [] : { status: 'ok' };
  api.json.mockImplementation(async (url, init, options) => {
    const value = await api.handler(url, init, options);
    if (options?.validate && !options.validate(value)) throw new Error('Unexpected server response.');
    return value;
  });
  useStore.setState({ ...original, aiMode: 'live', aiInput: 'Design a label', aiMessages: [{ role: 'assistant', content: 'Welcome' }], aiConvId: 1, aiSessionVersion: 0,
    aiSessionUsage: { tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 }, aiExternalPrompt: '', aiExternalPromptContext: null,
    aiExternalIntent: 'Make a label', aiExternalResponse: '[{"tool":"add_text_element","arguments":{"text":"Sample"}}]', aiExternalError: '', aiExternalNotice: '', aiExternalResults: [],
    currentPage: 0, items: [], pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: null }], selectedPrinter: null, selectedPrinterInfo: null,
    getStageB64: vi.fn(async () => 'data:image/png;base64,fixture'), printPages: vi.fn(), fetchProjects: vi.fn() }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); vi.useRealTimers(); });
const mount = () => act(() => root.render(<AIAssistant />));

test.each(['edit', 'project', 'page', 'printer', 'mode', 'new-chat', 'unmount'])('a noncooperative late chat reply cannot alter the %s context', async change => {
  const response = deferred(); api.handler = url => url === '/api/ai/chat' ? response.promise : url === '/api/ai/history' ? [] : { status: 'ok' };
  await mount(); await send();
  const call = api.json.mock.calls.find(([url]) => url === '/api/ai/chat'); expect(call).toBeDefined();
  await act(() => {
    const state = useStore.getState();
    if (change === 'edit') state.addItem({ id: 'user-edit', type: 'text', text: 'Keep this' });
    if (change === 'project') state.hydrateCanvasState(canvas({ items: [{ id: 'other-project', type: 'text', text: 'Other' }] }), { resetHistory: true });
    if (change === 'page') state.setCurrentPage(2);
    if (change === 'printer') useStore.setState({ selectedPrinter: 'new-device' });
    if (change === 'mode') state.setAiMode('external');
    if (change === 'new-chat') state.resetAiChat();
    if (change === 'unmount') root.render(null);
  });
  expect(call[1].signal.aborted).toBe(true);
  const expected = { items: useStore.getState().items, revision: useStore.getState().documentRevision, messages: useStore.getState().aiMessages };
  await act(() => response.resolve(chat({ __actions__: [{ action: 'print' }] })));
  expect(useStore.getState().items).toEqual(expected.items); expect(useStore.getState().documentRevision).toBe(expected.revision);
  expect(useStore.getState().aiMessages).toEqual(expected.messages); expect(useStore.getState().printPages).not.toHaveBeenCalled();
  expect(api.json.mock.calls.filter(([url, init]) => url.includes('/history/') && init?.method === 'PUT')).toHaveLength(0);
});

test('duplicate submits share one request and accepted replies apply only after acknowledged history save', async () => {
  const response = deferred(); api.handler = url => url === '/api/ai/chat' ? response.promise : url === '/api/ai/history' ? [] : { status: 'ok' };
  await mount(); await send(); await send(); expect(api.json.mock.calls.filter(([url]) => url === '/api/ai/chat')).toHaveLength(1);
  await act(() => response.resolve(chat())); await settle();
  expect(useStore.getState().items[0].text).toBe('AI result'); expect(useStore.getState().aiMessages.at(-1).content).toBe('Reply received');
  expect(useStore.getState().aiSessionUsage).toMatchObject({ tokens: 10, cost: 0.001 });
  expect(container.textContent).not.toContain('late assistant reply');
  const call = api.json.mock.calls.find(([url]) => url === '/api/ai/chat'); expect(call[2].timeoutMs).toBe(120_000);
});

test('reset during eager conversation creation cannot attach the late id or call the provider', async () => {
  useStore.setState({ aiConvId: null }); const created = deferred();
  api.handler = (url, init) => url === '/api/ai/history' && init?.method === 'POST' ? created.promise : [];
  await mount(); await send(); await click('[title="New Chat"]'); await act(() => created.resolve({ id: 22 }));
  expect(useStore.getState().aiConvId).toBeNull(); expect(api.json.mock.calls.some(([url]) => url === '/api/ai/chat')).toBe(false);
});

test('a malformed provider response fails visibly without hydrating the document', async () => {
  api.handler = url => url === '/api/ai/chat' ? { new_messages: [{}], canvas_state: { items: [] } } : [];
  await mount(); await send(); expect(container.textContent).toContain('Unexpected server response'); expect(useStore.getState().items).toEqual([]);
});

test('external prompts belong to the captured design and become unusable after an edit', async () => {
  useStore.setState({ aiMode: 'external' }); api.handler = () => ({ prompt: 'Owned prompt' });
  await mount(); await clickText('Generate Prompt');
  expect(useStore.getState().aiExternalPrompt).toBe('Owned prompt');
  await act(() => useStore.getState().addItem({ id: 'later', type: 'text', text: 'New edit' }));
  const apply = [...container.querySelectorAll('button')].find(button => button.textContent.trim() === 'Apply Tool Calls');
  expect(apply.disabled).toBe(true); expect(container.textContent).toContain('Generate a fresh prompt');
  expect(api.json.mock.calls.some(([url]) => url === '/api/ai/manual/execute')).toBe(false);
});

test('an empty first external prompt shows its error before a response field exists', async () => {
  useStore.setState({ aiMode: 'external' }); api.handler = () => ({ prompt: '' }); await mount();
  await clickText('Generate Prompt');
  expect(container.querySelector('[role="alert"]').textContent).toContain('Unexpected server response');
});

test('a late external prompt cannot attach to a replacement document', async () => {
  useStore.setState({ aiMode: 'external' }); const response = deferred(); api.handler = () => response.promise;
  await mount(); await clickText('Generate Prompt');
  await act(() => useStore.getState().hydrateCanvasState(canvas(), { resetHistory: true }));
  await act(() => response.resolve({ prompt: 'Old prompt' }));
  expect(useStore.getState().aiExternalPrompt).toBe('');
  expect(container.textContent).toContain('late assistant reply will not be applied');
});

test('cancelling an external execution discards its late canvas and print action', async () => {
  useStore.setState({ aiMode: 'external' }); const response = deferred();
  api.handler = url => url.endsWith('prompt-builder') ? { prompt: 'Owned prompt' } : response.promise;
  await mount(); await clickText('Generate Prompt'); await clickText('Apply Tool Calls'); await clickText('Cancel assistant request');
  await act(() => response.resolve({ canvas_state: canvas({ __actions__: [{ action: 'print' }] }), execution_results: [] }));
  expect(useStore.getState().items).toEqual([]); expect(useStore.getState().printPages).not.toHaveBeenCalled();
});

test('a deletion review is shown without issuing a delete request', async () => {
  useStore.setState({ aiMode: 'external' });
  api.handler = url => url.endsWith('prompt-builder') ? { prompt: 'Owned prompt' } : {
    canvas_state: canvas({ __actions__: [{ action: 'deletion_review_required', target_kind: 'folder', target_id: 8, name: 'Saved labels' }] }),
    execution_results: [{ index: 0, tool: 'delete_category', status: 'confirmation_required', result: 'Confirmation required: review Saved labels.' }]
  };
  await mount(); await clickText('Generate Prompt'); await clickText('Apply Tool Calls');
  expect(container.textContent).toContain('No saved content was deleted by the assistant');
  expect(container.textContent).toContain('Needs confirmation');
  expect(api.json.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
});

test.each(['print', 'print_review_required'])('an accepted %s action requires visible print review', async action => {
  api.handler = url => url === '/api/ai/chat' ? chat({ __actions__: [{ action }] }) : url === '/api/ai/history' ? [] : { status: 'ok' };
  await mount(); await send();
  expect(container.textContent).toContain('The assistant has not sent a print job');
  expect(useStore.getState().items[0].text).toBe('AI result'); expect(useStore.getState().printPages).not.toHaveBeenCalled();
});

test('history deletion requires confirmation and cancellation preserves the conversation', async () => {
  api.handler = () => [{ id: 1, title: 'Saved chat' }]; await mount(); await settle();
  await click('[title="Chat History"]'); await click('[aria-label="Delete conversation Saved chat"]');
  const dialog = document.querySelector('[role="dialog"]'); expect(dialog).not.toBeNull();
  await act(() => [...dialog.querySelectorAll('button')].find(button => button.textContent === 'Cancel').click()); await settle();
  expect(useStore.getState().aiConvId).toBe(1); expect(api.json.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
});

test('visual review captures a fresh image for each round and stops after three follow-ups', async () => {
  vi.useFakeTimers(); api.handler = url => url === '/api/ai/chat' ? chat({ __actions__: [{ action: 'frontend_visual_preview' }] }) : url === '/api/ai/history' ? [] : { status: 'ok' };
  await mount(); await send();
  for (let index = 0; index < 5; index++) await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(api.json.mock.calls.filter(([url]) => url === '/api/ai/chat')).toHaveLength(4);
  expect(useStore.getState().getStageB64).toHaveBeenCalledTimes(4);
  expect(container.textContent).toContain('Visual review stopped after three rounds');
});

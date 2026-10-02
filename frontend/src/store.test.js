import { afterEach, describe, expect, test, vi } from 'vitest';
import { useStore } from './store';
import * as apiClient from './utils/apiClient';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  useStore.setState({
    items: [],
    pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: null }],
    batchRecords: [{}],
    currentPage: 0,
    currentProjectId: null,
    currentProjectRevision: null,
    projects: [],
    apiError: null,
    history: [],
    historyIndex: -1,
    canUndo: false,
    canRedo: false
  });
});

describe('editor store correctness', () => {
  test('AI setters accept React-style functional updaters', () => {
    useStore.setState({ aiMessages: [], aiSessionUsage: { tokens: 1 } });
    useStore.getState().setAiMessages((messages) => [...messages, { role: 'user', content: 'hello' }]);
    useStore.getState().setAiSessionUsage((usage) => ({ ...usage, tokens: usage.tokens + 4 }));
    expect(useStore.getState().aiMessages).toEqual([{ role: 'user', content: 'hello' }]);
    expect(useStore.getState().aiSessionUsage.tokens).toBe(5);
  });

  test('selects a newly added item on its target page', () => {
    useStore.setState({ currentPage: 2 });
    useStore.getState().addItem({ id: 'created', type: 'text', text: 'New' });
    expect(useStore.getState()).toMatchObject({
      selectedId: 'created', selectedIds: ['created'], currentPage: 2
    });
    expect(useStore.getState().items[0].pageIndex).toBe(2);
  });

  test('hydrates rotation and geometry atomically without double-swapping', () => {
    useStore.getState().hydrateCanvasState({
      width: 200,
      height: 100,
      isRotated: true,
      items: [{ id: 'one', type: 'text', text: 'A', pageIndex: 0 }]
    });
    expect(useStore.getState()).toMatchObject({ canvasWidth: 200, canvasHeight: 100, isRotated: true });
  });

  test('loading a project clears the previous document history', async () => {
    vi.useFakeTimers();
    useStore.getState().setItems([{ id: 'old', type: 'text', text: 'Old', pageIndex: 0 }]);
    await vi.advanceTimersByTimeAsync(450);
    expect(useStore.getState().canUndo).toBe(true);

    useStore.getState().loadProject({
      id: 42,
      canvas_state: { width: 300, height: 150, items: [{ id: 'new', type: 'text', text: 'New', pageIndex: 0 }] }
    });
    expect(useStore.getState()).toMatchObject({ currentProjectId: 42, history: [], canUndo: false });

    useStore.getState().undo();
    expect(useStore.getState().items[0].id).toBe('new');
  });

  test('clamps persisted copies and batch records while normalizing pages', () => {
    const records = Array.from({ length: 1_100 }, (_, index) => ({ index }));
    useStore.getState().hydrateCanvasState({
      printCopies: 999,
      batchRecords: records,
      pageLayouts: [{ pageIndex: -10, htmlContent: 'first' }]
    });
    expect(useStore.getState().printCopies).toBe(100);
    expect(useStore.getState().batchRecords).toHaveLength(1_000);
    expect(useStore.getState().pageLayouts[0].pageIndex).toBe(0);
  });

  test.each([
    ['rename', 'Renamed', undefined],
    ['move', undefined, 7]
  ])('%s updates send a revision without replacing the saved canvas', async (_kind, name, category) => {
    useStore.setState({ projects: [{ id: 42, revision: 3 }], items: [{ id: 'unrelated' }] });
    const fetch = vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ id: 42, revision: 4 }) });
    vi.spyOn(apiClient, 'apiJson').mockResolvedValue([]);
    await useStore.getState().updateProject(42, name, category);
    const payload = JSON.parse(fetch.mock.calls[0][1].body);
    expect(payload.expected_revision).toBe(3);
    expect(payload).not.toHaveProperty('canvas_state');
    if (name) expect(payload.name).toBe(name);
    if (category !== undefined) expect(payload.category_id).toBe(category);
  });

  test('canvas saves use the loaded revision rather than a refreshed listing', async () => {
    useStore.getState().loadProject({ id: 42, revision: 3, canvas_state: { items: [] } });
    useStore.setState({ projects: [{ id: 42, revision: 9 }] });
    const fetch = vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ id: 42, revision: 4 }) });
    vi.spyOn(apiClient, 'apiJson').mockResolvedValue([]);
    await useStore.getState().updateProject(42);
    const payload = JSON.parse(fetch.mock.calls[0][1].body);
    expect(payload.expected_revision).toBe(3);
    expect(payload.canvas_state.items).toEqual([]);
    expect(useStore.getState().currentProjectRevision).toBe(4);
  });

  test('a conflict preserves the loaded revision and edited canvas', async () => {
    useStore.getState().loadProject({ id: 42, revision: 3, canvas_state: { items: [{ id: 'draft' }] } });
    vi.spyOn(apiClient, 'apiFetch').mockRejectedValue(new Error('A newer revision is saved.'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    await useStore.getState().updateProject(42);
    expect(useStore.getState()).toMatchObject({ currentProjectRevision: 3, items: [{ id: 'draft' }], apiError: 'A newer revision is saved.' });
  });
});

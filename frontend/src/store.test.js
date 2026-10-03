import { beforeEach, afterEach, describe, expect, test, vi } from 'vitest';
import { useStore } from './store';
import * as apiClient from './utils/apiClient';

beforeEach(() => { useStore.setState({ pendingProjectLoad: null }, false, { history: 'skip' }); });
const openProject = (summary) => {
  const result = useStore.getState().loadProject(summary);
  return useStore.getState().pendingProjectLoad ? useStore.getState().confirmProjectLoad() : result;
};
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
    canRedo: false,
    currentDpi: 203,
    canvasWidth: 384,
    canvasHeight: 384,
    selectedPrinter: null,
    selectedPrinterInfo: null
  }, false, { document: 'replace' });
});

describe('editor store correctness', () => {
  test('project tree pages summaries without fetching embedded documents', async () => {
    const api = vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url) => {
      if (url === '/api/categories') return [];
      if (url.endsWith('after_id=0')) return { projects: [{ id: 7, name: 'A', revision: 1 }], next_after_id: 7 };
      if (url.endsWith('after_id=7')) return { projects: [{ id: 9, name: 'B', revision: 2 }], next_after_id: null };
      throw new Error('Unexpected document fetch');
    });
    await useStore.getState().fetchProjects();
    expect(useStore.getState().projects.map(project => project.id)).toEqual([7, 9]);
    expect(api).toHaveBeenCalledTimes(3);
  });

  test('opening summaries fetches detail and ignores an older delayed selection', async () => {
    let resolveOld;
    const old = new Promise(resolve => { resolveOld = resolve; });
    vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url) => url.endsWith('/1') ? old : {
      id: 2, revision: 3, canvas_state: { items: [{ id: 'new', type: 'text' }] }
    });
    const openingOld = openProject({ id: 1 });
    await openProject({ id: 2 });
    resolveOld({ id: 1, revision: 1, canvas_state: { items: [{ id: 'old', type: 'text' }] } });
    await openingOld;
    expect(useStore.getState()).toMatchObject({ currentProjectId: 2, currentProjectRevision: 3, items: [{ id: 'new' }] });
  });

  test('saved DPI survives loading without a selected printer', () => {
    useStore.setState({ currentDpi: 203 });
    openProject({ id: 1, revision: 2, canvas_state: {
      document_version: 1, dpi: 300, width: 600, height: 300, items: []
    } });
    expect(useStore.getState()).toMatchObject({ currentDpi: 300, canvasWidth: 600, canvasHeight: 300 });
    expect(useStore.getState().getPxToMm(600)).toBe('50.8');
  });

  test('legacy documents retain the current resolution without inventing a saved DPI', () => {
    useStore.setState({ currentDpi: 300 });
    openProject({ id: 1, canvas_state: { width: 600, height: 300, items: [] } });
    expect(useStore.getState()).toMatchObject({ currentDpi: 300, canvasWidth: 600, canvasHeight: 300 });
  });

  test('document hydration and history reset notify subscribers atomically', async () => {
    vi.useFakeTimers();
    useStore.getState().setItems([{ id: 'old', type: 'text' }]);
    await vi.advanceTimersByTimeAsync(450);
    const observed = [];
    const unsubscribe = useStore.subscribe((state, previous) => { if (state.items === previous.items) return; observed.push({ id: state.currentProjectId,
      item: state.items[0]?.id, canUndo: state.canUndo, history: state.history.length }); });
    openProject({ id: 99, canvas_state: { items: [{ id: 'new', type: 'text' }] } });
    unsubscribe();
    expect(observed).toEqual([{ id: 99, item: 'new', canUndo: false, history: 0 }]);
  });

  test('loading against a selected printer preserves millimetres and nested geometry', () => {
    useStore.setState({ currentDpi: 203, selectedPrinter: 'offline', selectedPrinterInfo: { dpi: 203 } });
    openProject({ id: 1, canvas_state: {
      document_version: 1, dpi: 300, width: 600, height: 300, items: [{
        id: 'group', type: 'group', x: 300, rotation: 30,
        children: [{ id: 'text', type: 'text', size: 30, x: 150, width: '50%' }]
      }]
    } });
    expect(useStore.getState()).toMatchObject({ currentDpi: 203, canvasWidth: 406, canvasHeight: 203 });
    expect(useStore.getState().getPxToMm(406)).toBe('50.8');
    expect(useStore.getState().items[0]).toMatchObject({ x: 203, rotation: 30,
      children: [{ size: 20.3, x: 101.5, width: '50%' }] });
  });

  test.each(['save', 'overwrite'])('%s serializes document version and DPI', async (operation) => {
    useStore.setState({ currentProjectId: 42, currentProjectRevision: 3, currentDpi: 300,
      canvasWidth: 600, canvasHeight: 300 });
    const fetch = vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ id: 42, revision: 4 }) });
    vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url) => url.startsWith('/api/projects/summaries') ? { projects: [], next_after_id: null } : []);
    if (operation === 'save') await useStore.getState().saveProject('DPI fixture');
    else await useStore.getState().updateProject(42);
    expect(JSON.parse(fetch.mock.calls[0][1].body).canvas_state).toMatchObject({
      document_version: 1, dpi: 300, width: 600, height: 300
    });
  });

  test('unsupported or over-limit documents preserve the current editor', () => {
    useStore.setState({ currentProjectId: 42, items: [{ id: 'retained', type: 'text' }], currentDpi: 203 });
    openProject({ id: 99, canvas_state: { document_version: 2, items: [] } });
    expect(useStore.getState()).toMatchObject({ currentProjectId: 42, items: [{ id: 'retained' }] });
    expect(useStore.getState().apiError).toContain('document version');
    openProject({ id: 99, canvas_state: { width: 20_001, items: [] } });
    expect(useStore.getState()).toMatchObject({ currentProjectId: 42, items: [{ id: 'retained' }] });
    expect(useStore.getState().apiError).toContain('dimension limit');
  });

  test('printer selection and deselection preserve existing document geometry', async () => {
    vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ speed: 0, energy: 0, feed_lines: 50 }) });
    useStore.setState({ currentDpi: 300, canvasWidth: 600, canvasHeight: 300,
      items: [{ id: 'text', type: 'text', size: 30 }], pageLayouts: [] });
    await useStore.getState().setSelectedPrinter('offline', { address: 'offline', dpi: 203,
      media_type: 'pre-cut', model_id: 'd110', width_px: 384 });
    expect(useStore.getState()).toMatchObject({ currentDpi: 203, canvasWidth: 406, canvasHeight: 203 });
    await useStore.getState().setSelectedPrinter(null, null);
    expect(useStore.getState()).toMatchObject({ currentDpi: 203, canvasWidth: 406, canvasHeight: 203 });
  });

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

    openProject({
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
    vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url) => url.startsWith('/api/projects/summaries') ? { projects: [], next_after_id: null } : []);
    await useStore.getState().updateProject(42, name, category);
    const payload = JSON.parse(fetch.mock.calls[0][1].body);
    expect(payload.expected_revision).toBe(3);
    expect(payload).not.toHaveProperty('canvas_state');
    if (name) expect(payload.name).toBe(name);
    if (category !== undefined) expect(payload.category_id).toBe(category);
  });

  test('canvas saves use the loaded revision rather than a refreshed listing', async () => {
    openProject({ id: 42, revision: 3, canvas_state: { items: [] } });
    useStore.setState({ projects: [{ id: 42, revision: 9 }] });
    const fetch = vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ id: 42, revision: 4 }) });
    vi.spyOn(apiClient, 'apiJson').mockImplementation(async (url) => url.startsWith('/api/projects/summaries') ? { projects: [], next_after_id: null } : []);
    await useStore.getState().updateProject(42);
    const payload = JSON.parse(fetch.mock.calls[0][1].body);
    expect(payload.expected_revision).toBe(3);
    expect(payload.canvas_state.items).toEqual([]);
    expect(useStore.getState().currentProjectRevision).toBe(4);
  });

  test('a conflict preserves the loaded revision and edited canvas', async () => {
    openProject({ id: 42, revision: 3, canvas_state: { items: [{ id: 'draft' }] } });
    vi.spyOn(apiClient, 'apiFetch').mockRejectedValue(new Error('A newer revision is saved.'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    await useStore.getState().updateProject(42);
    expect(useStore.getState()).toMatchObject({ currentProjectRevision: 3, items: [{ id: 'draft' }], apiError: 'A newer revision is saved.' });
  });
});

test('undo returns to the saved baseline and active page changes stay clean', async () => {
  vi.useFakeTimers();
  useStore.getState().hydrateCanvasState({ items: [{ id: 'base', type: 'text' }] }, { resetHistory: true });
  useStore.getState().setCurrentPage(1);
  expect(useStore.getState().isDocumentDirty).toBe(false);
  useStore.getState().setItems([{ id: 'edited', type: 'text' }]);
  expect(useStore.getState().isDocumentDirty).toBe(true);
  await vi.advanceTimersByTimeAsync(450);
  useStore.getState().undo();
  expect(useStore.getState().isDocumentDirty).toBe(false);
});

test('edits during save remain dirty and a late save cannot attach to another project', async () => {
  let resolveSave;
  vi.spyOn(apiClient, 'apiFetch').mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
  vi.spyOn(apiClient, 'apiJson').mockImplementation(async url => url.startsWith('/api/projects/summaries') ? { projects: [], next_after_id: null } : []);
  useStore.getState().hydrateCanvasState({ items: [{ id: 'first', type: 'text' }] }, { resetHistory: true });
  const saving = useStore.getState().saveProject('First');
  useStore.getState().setItems([{ id: 'later', type: 'text' }]);
  resolveSave({ json: async () => ({ id: 7, revision: 1 }) });
  await saving;
  expect(useStore.getState()).toMatchObject({ currentProjectId: 7, saveStatus: 'dirty', isDocumentDirty: true });
  const oldSave = useStore.getState().saveProject('Old');
  useStore.getState().hydrateCanvasState({ items: [{ id: 'second', type: 'text' }] }, {
    resetHistory: true, currentProjectId: 8, currentProjectRevision: 2
  });
  resolveSave({ json: async () => ({ id: 9, revision: 1 }) });
  await oldSave;
  expect(useStore.getState()).toMatchObject({ currentProjectId: 8, currentProjectRevision: 2, isDocumentDirty: false });
});

test('opening a project protects declined and newly made unsaved edits', async () => {
  useStore.getState().setItems([{ id: 'kept', type: 'text' }]);
  const fetch = vi.spyOn(apiClient, 'apiJson');
  await useStore.getState().loadProject({ id: 2 });
  expect(fetch).not.toHaveBeenCalled();
  useStore.getState().cancelProjectLoad();
  expect(useStore.getState().items[0].id).toBe('kept');
  let resolveLoad;
  fetch.mockImplementation(() => new Promise(resolve => { resolveLoad = resolve; }));
  const opening = openProject({ id: 2 });
  useStore.getState().setItems([{ id: 'newer', type: 'text' }]);
  resolveLoad({ id: 2, revision: 1, canvas_state: { items: [] } });
  await opening;
  expect(useStore.getState().items[0].id).toBe('newer');
  expect(useStore.getState().apiError).toContain('changed while');
});

test('clearing during a save detaches the old request and leaves a saveable new design', async () => {
  let resolveSave;
  vi.spyOn(apiClient, 'apiFetch').mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
  vi.spyOn(apiClient, 'apiJson').mockImplementation(async url => url.startsWith('/api/projects/summaries') ? { projects: [], next_after_id: null } : []);
  useStore.getState().setItems([{ id: 'old', type: 'text' }]);
  const saving = useStore.getState().saveProject('Old');
  useStore.getState().clearCanvas();
  expect(useStore.getState().saveStatus).toBe('dirty');
  resolveSave({ json: async () => ({ id: 70, revision: 1 }) });
  await saving;
  expect(useStore.getState()).toMatchObject({ currentProjectId: null, saveStatus: 'dirty', isDocumentDirty: true });
});

 test('confirmation cannot discard edits made while the guard was open', async () => {
  const fetch = vi.spyOn(apiClient, 'apiJson');
  useStore.getState().setItems([{ id: 'before', type: 'text' }]);
  await useStore.getState().loadProject({ id: 9 });
  useStore.getState().setItems([{ id: 'after', type: 'text' }]);
  await useStore.getState().confirmProjectLoad();
  expect(fetch).not.toHaveBeenCalled();
  expect(useStore.getState().pendingProjectLoad).toBeNull();
  expect(useStore.getState().items[0].id).toBe('after');
  expect(useStore.getState().apiError).toContain('confirmation was open');
 });

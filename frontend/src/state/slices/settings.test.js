import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useStore } from '../../store';
import * as apiClient from '../../utils/apiClient';

const initialSettings = () => ({
  paper_width_mm: 58,
  print_width_mm: 48,
  default_dpi: 203,
  speed: 0,
  energy: 0,
  feed_lines: 50,
  default_font: 'RobotoCondensed.ttf',
  intended_media_type: 'unknown'
});

const resetStore = () => useStore.setState({
  settings: initialSettings(),
  settingsLoaded: false,
  settingsSaveStatus: 'idle',
  settingsSaveError: '',
  currentDpi: 203,
  canvasWidth: 384,
  canvasHeight: 256,
  items: [],
  pageLayouts: [{ pageIndex: 0, htmlContent: 'baseline', activeTemplate: null }],
  batchRecords: [{}],
  selectedPrinter: null,
  selectedPrinterInfo: null,
  apiError: null,
  currentProjectId: null,
  currentProjectRevision: null,
  history: [],
  historyIndex: -1,
  canUndo: false,
  canRedo: false
}, false, { document: 'replace', history: 'skip' });

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

beforeEach(() => {
  resetStore();
});

afterEach(() => {
  vi.restoreAllMocks();
  resetStore();
});

describe('settings API saves', () => {
  test('moves from pending to saved and resolves true', async () => {
    const request = deferred();
    const apiFetch = vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const submittedSettings = { ...initialSettings(), feed_lines: 60 };
    const initialDocumentRevision = useStore.getState().documentRevision;
    const initialHistory = useStore.getState().history;

    const save = useStore.getState().updateSettingsAPI(submittedSettings);

    expect(useStore.getState()).toMatchObject({
      settingsSaveStatus: 'saving',
      settingsSaveError: ''
    });
    expect(useStore.getState().settings).toBe(submittedSettings);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(submittedSettings)
    });

    request.resolve({ status: 200 });
    await expect(save).resolves.toBe(true);

    expect(useStore.getState()).toMatchObject({
      settingsSaveStatus: 'saved',
      settingsSaveError: ''
    });
    expect(useStore.getState().documentRevision).toBe(initialDocumentRevision);
    expect(useStore.getState().history).toBe(initialHistory);
  });

  test('returns false with the error message and restores unchanged optimistic DPI geometry', async () => {
    const request = deferred();
    vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const initial = useStore.getState();
    const submittedSettings = { ...initial.settings, default_dpi: 300 };

    const save = useStore.getState().updateSettingsAPI(submittedSettings);
    const submittedDocument = useStore.getState();
    expect(submittedDocument).toMatchObject({
      settingsSaveStatus: 'saving',
      currentDpi: 300,
      canvasWidth: 567,
      canvasHeight: 378
    });

    request.reject(new Error('settings service unavailable'));
    await expect(save).resolves.toBe(false);

    const failed = useStore.getState();
    expect(failed).toMatchObject({
      settings: initial.settings,
      currentDpi: initial.currentDpi,
      canvasWidth: initial.canvasWidth,
      canvasHeight: initial.canvasHeight,
      items: initial.items,
      pageLayouts: initial.pageLayouts,
      settingsSaveStatus: 'failed',
      settingsSaveError: 'settings service unavailable',
      apiError: 'settings service unavailable'
    });
    expect(failed.documentSessionId).toBe(submittedDocument.documentSessionId);
    expect(failed.documentRevision).toBeGreaterThan(submittedDocument.documentRevision);
  });

  test('rejects a duplicate pending save without a second request or optimistic update', async () => {
    const request = deferred();
    const apiFetch = vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const firstSettings = { ...initialSettings(), default_dpi: 300, feed_lines: 61 };
    const secondSettings = { ...initialSettings(), default_dpi: 600, feed_lines: 80 };

    const firstSave = useStore.getState().updateSettingsAPI(firstSettings);
    const firstSnapshot = useStore.getState();
    await expect(useStore.getState().updateSettingsAPI(secondSettings)).resolves.toBe(false);

    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(useStore.getState().settings).toBe(firstSettings);
    expect(useStore.getState().settingsSaveStatus).toBe('saving');
    expect(useStore.getState().currentDpi).toBe(firstSnapshot.currentDpi);
    expect(useStore.getState().canvasWidth).toBe(firstSnapshot.canvasWidth);
    expect(useStore.getState().canvasHeight).toBe(firstSnapshot.canvasHeight);

    request.resolve({ status: 200 });
    await expect(firstSave).resolves.toBe(true);
  });

  test('keeps document edits made after the optimistic DPI update when the request fails', async () => {
    const request = deferred();
    vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const submittedSettings = { ...initialSettings(), default_dpi: 300 };

    const save = useStore.getState().updateSettingsAPI(submittedSettings);
    const submittedDocument = useStore.getState();
    const editedItems = [{ id: 'edited-during-save', type: 'text', text: 'Keep this edit' }];
    useStore.getState().setItems(editedItems);
    const editedDocument = useStore.getState();
    expect(editedDocument.documentRevision).toBeGreaterThan(submittedDocument.documentRevision);

    request.reject(new Error('save rejected'));
    await expect(save).resolves.toBe(false);

    expect(useStore.getState()).toMatchObject({
      settings: initialSettings(),
      currentDpi: submittedDocument.currentDpi,
      canvasWidth: submittedDocument.canvasWidth,
      canvasHeight: submittedDocument.canvasHeight,
      items: editedDocument.items,
      pageLayouts: editedDocument.pageLayouts,
      settingsSaveStatus: 'failed'
    });
  });

  test('keeps a different hydrated document when the request fails', async () => {
    const request = deferred();
    vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const submittedSettings = { ...initialSettings(), default_dpi: 300 };

    const save = useStore.getState().updateSettingsAPI(submittedSettings);
    const submittedDocument = useStore.getState();
    useStore.getState().hydrateCanvasState({
      document_version: 1,
      dpi: 203,
      width: 250,
      height: 125,
      items: [{ id: 'hydrated-document', type: 'text', text: 'New document' }]
    }, { resetHistory: true });
    const hydratedDocument = useStore.getState();
    expect(hydratedDocument.documentSessionId).toBeGreaterThan(submittedDocument.documentSessionId);

    request.reject(new Error('save rejected'));
    await expect(save).resolves.toBe(false);

    expect(useStore.getState()).toMatchObject({
      settings: initialSettings(),
      currentDpi: hydratedDocument.currentDpi,
      canvasWidth: hydratedDocument.canvasWidth,
      canvasHeight: hydratedDocument.canvasHeight,
      items: hydratedDocument.items,
      pageLayouts: hydratedDocument.pageLayouts,
      documentSessionId: hydratedDocument.documentSessionId,
      documentRevision: hydratedDocument.documentRevision,
      settingsSaveStatus: 'failed'
    });
  });

  test('does not roll back a newer settings snapshot after an older request fails', async () => {
    const request = deferred();
    vi.spyOn(apiClient, 'apiFetch').mockReturnValue(request.promise);
    const submittedSettings = { ...initialSettings(), default_dpi: 300, feed_lines: 61 };
    const newerSettings = { ...initialSettings(), default_dpi: 300, feed_lines: 75 };

    const save = useStore.getState().updateSettingsAPI(submittedSettings);
    useStore.getState().setSettings(newerSettings);

    request.reject(new Error('save rejected'));
    await expect(save).resolves.toBe(false);

    expect(useStore.getState()).toMatchObject({
      settings: newerSettings,
      currentDpi: 203,
      canvasWidth: 384,
      canvasHeight: 256,
      settingsSaveStatus: 'failed'
    });
    expect(useStore.getState().settings).toBe(newerSettings);
  });
});

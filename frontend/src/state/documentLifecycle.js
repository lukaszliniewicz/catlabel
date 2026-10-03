// View selection, zoom and active page are deliberately not document edits.
const DOCUMENT_KEYS = [
  'items', 'pageLayouts', 'batchRecords', 'printCopies', 'canvasWidth',
  'canvasHeight', 'currentDpi', 'canvasBorder', 'canvasBorderThickness',
  'isRotated', 'splitMode'
];

export const documentSnapshot = (state) => Object.fromEntries(
  DOCUMENT_KEYS.map(key => [key, state[key]])
);

export const withDocumentLifecycle = (config) => (set, get, api) => {
  let baseline;
  const update = (args, replace, options = {}) => {
    const previous = get();
    const patch = typeof args === 'function' ? args(previous) : args;
    if (!patch || patch === previous) return;
    const next = replace ? patch : { ...previous, ...patch };
    const changed = DOCUMENT_KEYS.some(key => previous[key] !== next[key]);
    const replacement = options.document === 'replace' || replace;
    const detached = options.document === 'detach';
    if (detached) baseline = null;
    if (replacement) baseline = options.dirty ? null : documentSnapshot(next);
    if (options.savedDocument) baseline = options.savedDocument;
    const dirty = !baseline || DOCUMENT_KEYS.some(key => baseline[key] !== next[key]);
    const sessionChanged = replacement || detached;
    const saveStatus = options.savedDocument ? (dirty ? 'dirty' : 'saved')
      : replacement || detached ? (dirty ? 'dirty' : 'saved')
      : changed && next.saveStatus !== 'saving' ? (dirty ? 'dirty' : 'saved')
      : next.saveStatus;
    set({ ...patch,
      documentSessionId: (previous.documentSessionId || 0) + Number(sessionChanged),
      documentRevision: (previous.documentRevision || 0) + Number(changed || sessionChanged),
      isDocumentDirty: dirty,
      saveStatus
    }, replace);
  };
  api.setState = update;
  const state = { documentSessionId: 0, documentRevision: 0,
    isDocumentDirty: false, saveStatus: 'saved', ...config(update, get, api) };
  baseline = documentSnapshot(state);
  return state;
};

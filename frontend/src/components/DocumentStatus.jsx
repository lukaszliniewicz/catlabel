import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { serializeCanvasDocument } from '../domain/document';

const DRAFT_KEY = 'catlabel_document_draft_v1';
const MAX_DRAFT_CHARACTERS = 1_500_000;

const readDraft = () => {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    if (raw.length > MAX_DRAFT_CHARACTERS) return { invalid: true };
    const draft = JSON.parse(raw);
    if (draft?.draft_schema !== 1 || draft.canvas_state?.document_version !== 1
      || !Array.isArray(draft.canvas_state.items) || !Array.isArray(draft.canvas_state.pageLayouts)) {
      return { invalid: true };
    }
    return draft;
  } catch { return { invalid: true }; }
};

export default function DocumentStatus() {
  const dirty = useStore(state => state.isDocumentDirty);
  const status = useStore(state => state.saveStatus);
  const projectId = useStore(state => state.currentProjectId);
  const updateProject = useStore(state => state.updateProject);
  const [draft, setDraft] = useState(readDraft);
  const [notice, setNotice] = useState('');
  const pendingDraft = useRef(draft);
  const flushDraft = useRef(null);

  useEffect(() => {
    let timer;
    const persist = () => {
      if (pendingDraft.current) return;
      const state = useStore.getState();
      try {
        if (!state.isDocumentDirty) {
          localStorage.removeItem(DRAFT_KEY);
          return;
        }
        const value = JSON.stringify({ draft_schema: 1, project_id: state.currentProjectId,
          project_revision: state.currentProjectRevision, updated_at: new Date().toISOString(),
          canvas_state: serializeCanvasDocument(state) });
        if (value.length > MAX_DRAFT_CHARACTERS) throw new Error('This design is too large for a browser recovery copy. Save it as a project.');
        localStorage.setItem(DRAFT_KEY, value);
      } catch (error) {
        setNotice(error.message || 'Browser recovery storage is unavailable. Save your design as a project.');
      }
    };
    flushDraft.current = persist;
    const unsubscribe = useStore.subscribe((state, previous) => {
      if (state.documentRevision !== previous.documentRevision
        || state.isDocumentDirty !== previous.isDocumentDirty || state.saveStatus !== previous.saveStatus) {
        clearTimeout(timer);
        timer = setTimeout(persist, 500);
      }
    });
    const beforeUnload = event => {
      persist();
      if (useStore.getState().isDocumentDirty) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    const pageHide = () => persist();
    window.addEventListener('beforeunload', beforeUnload);
    window.addEventListener('pagehide', pageHide);
    return () => {
      clearTimeout(timer);
      unsubscribe();
      window.removeEventListener('beforeunload', beforeUnload);
      window.removeEventListener('pagehide', pageHide);
    };
  }, []);

  const releaseDraft = () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* Storage errors remain visible through the next persistence attempt. */ }
    pendingDraft.current = null;
    setDraft(null);
    flushDraft.current?.();
  };
  const recover = () => {
    const state = useStore.getState();
    if (state.isDocumentDirty && !window.confirm('Recover this copy and replace your current unsaved edits?')) return;
    try {
      // Always recover as a new design, even offline. Never overwrite its saved ancestor.
      state.hydrateCanvasState(draft.canvas_state, { currentProjectId: null,
        currentProjectRevision: null, resetHistory: true, dirty: true });
      releaseDraft();
      setNotice('Recovered as a new unsaved design. Save it as a new project when ready.');
    } catch (error) { setNotice(error.message || 'The recovery copy could not be opened. Your current design was kept.'); }
  };

  return <div className="shrink-0 border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 px-3 py-2 text-xs">
    <div className="flex flex-wrap items-center gap-3">
      <span role="status" aria-live="polite">{status === 'saving' ? 'Saving…' : status === 'failed'
        ? 'Save failed — your edits are still here' : dirty ? 'Unsaved changes' : projectId ? 'Saved' : 'New design'}</span>
      {projectId != null && <button type="button" disabled={status === 'saving' || !dirty}
        onClick={() => updateProject(projectId)} className="border border-neutral-400 dark:border-neutral-600 px-3 py-1 disabled:opacity-50">Save changes</button>}
      {projectId == null && dirty && <span>Use Projects → Save to name this design.</span>}
    </div>
    {draft && <div className="mt-2 flex flex-wrap items-center gap-2" role="status">
      <span>{draft.invalid ? 'A browser recovery copy could not be read.' : 'A browser recovery copy is available. Recovering creates a new design.'}</span>
      {!draft.invalid && <button type="button" onClick={recover} className="border border-blue-500 px-3 py-1">Recover as new design</button>}
      <button type="button" onClick={releaseDraft} className="border border-neutral-400 dark:border-neutral-600 px-3 py-1">Discard recovery copy</button>
    </div>}
    {notice && (dirty || !notice.startsWith('Recovered as a new unsaved design.')) && <p role="status" className="mt-2 text-amber-800 dark:text-amber-200">{notice}</p>}
  </div>;
}

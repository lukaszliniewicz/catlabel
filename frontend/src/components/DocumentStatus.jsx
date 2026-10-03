import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { apiFetch } from '../utils/apiClient';
import { serializeCanvasDocument } from '../domain/document';
import ConfirmActionDialog from './ConfirmActionDialog';
import EditorDrawer from './EditorDrawer';

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

export default function DocumentStatus({ open = false, onClose, onAttentionChange }) {
  const lastPrintReceipt = useStore(state => state.lastPrintReceipt);
  const isPrinting = useStore(state => state.isPrinting);
  const isPreparing = useStore(state => state.isPreparingForPrint);
  const progress = useStore(state => state.printPreparationProgress);
  const pendingPrintJob = useStore(state => state.pendingPrintJob);
  const onLocalRenderComplete = useStore(state => state.onLocalRenderComplete);
  const dirty = useStore(state => state.isDocumentDirty);
  const status = useStore(state => state.saveStatus);
  const projectId = useStore(state => state.currentProjectId);
  const updateProject = useStore(state => state.updateProject);
  const [draft, setDraft] = useState(readDraft);
  const [notice, setNotice] = useState('');
  const [revisionNotice, setRevisionNotice] = useState(null);
  const externalRevision = revisionNotice?.projectId === projectId ? revisionNotice.revision : null;
  const [recoveryConfirmation, setRecoveryConfirmation] = useState(null);
  const pendingDraft = useRef(draft);
  const flushDraft = useRef(null);
  const documentMessage = status === 'saving' ? 'Saving…' : status === 'failed'
    ? 'Save failed — your edits are still here' : dirty ? 'Unsaved changes' : projectId ? 'Saved' : 'New design';
  const printMessage = isPreparing ? progress ? `Preparing ${progress.completed} of ${progress.total} labels…` : 'Preparing labels…' : isPrinting ? 'Submitting labels…' : lastPrintReceipt
    ? lastPrintReceipt.status === 'submitted'
      ? `${lastPrintReceipt.submitted} label${lastPrintReceipt.submitted === 1 ? '' : 's'} submitted. Check the physical output; completion is unverified.`
      : 'No labels were submitted.' : '';
  const needsAttention = Boolean(externalRevision || draft || notice || status === 'failed');
  useEffect(() => { onAttentionChange?.(needsAttention); }, [needsAttention, onAttentionChange]);

  useEffect(() => {
    if (projectId == null) return undefined;
    let active = true;
    const controller = new AbortController();
    const inspect = async () => {
      try {
        const response = await apiFetch(`/api/projects/${projectId}/revision`, { signal: controller.signal });
        const project = await response.json();
        const current = useStore.getState();
        if (active && current.currentProjectId === projectId && Number.isInteger(project.revision)) {
          setRevisionNotice(project.revision !== current.currentProjectRevision ? { projectId, revision: project.revision } : null);
        }
      } catch { /* Revision polling must not disrupt editing or offline recovery. */ }
    };
    void inspect();
    const interval = window.setInterval(inspect, 15000);
    window.addEventListener('focus', inspect);
    return () => { active = false; controller.abort(); window.clearInterval(interval); window.removeEventListener('focus', inspect); };
  }, [projectId]);


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
  const recover = approval => {
    const state = useStore.getState();
    if (approval && (state.documentSessionId !== approval.session || state.documentRevision !== approval.revision)) {
      setRecoveryConfirmation(null);
      setNotice('The design changed while confirmation was open. Your edits were kept. Review the recovery copy again when ready.');
      return;
    }
    if (state.isDocumentDirty && !approval) {
      setRecoveryConfirmation({ session: state.documentSessionId, revision: state.documentRevision });
      return;
    }
    setRecoveryConfirmation(null);
    try {
      // Always recover as a new design, even offline. Never overwrite its saved ancestor.
      state.hydrateCanvasState(draft.canvas_state, { currentProjectId: null,
        currentProjectRevision: null, resetHistory: true, dirty: true });
      releaseDraft();
      setNotice('Recovered as a new unsaved design. Save it as a new project when ready.');
    } catch (error) { setNotice(error.message || 'The recovery copy could not be opened. Your current design was kept.'); }
  };

  // Stay mounted even with the drawer closed: recovery persistence and unload
  // protection belong to the editor session, not to the panel's visibility.
  return <>
    <span role="status" aria-live="polite" className="sr-only">{documentMessage} {printMessage}{needsAttention ? ' Open Status for recovery or save details.' : ''}</span>
    {open && <EditorDrawer label="Status" side="left" width={320} onClose={onClose}>
    <div className="h-full overflow-y-auto p-4 text-xs space-y-5">
    <h3 className="text-sm font-semibold">Design</h3>
    <div className="flex flex-wrap items-center gap-3">
      <span>{documentMessage}</span>
      {projectId != null && <button type="button" disabled={status === 'saving' || !dirty}
        onClick={() => updateProject(projectId)} className="border border-neutral-400 dark:border-neutral-600 px-3 py-1 disabled:opacity-50">Save changes</button>}
      {projectId == null && dirty && <span>Use Projects → Save to name this design.</span>}
    </div>
    {externalRevision != null && <section role="status" className="border-t border-amber-400 pt-3">
      <p>This saved design changed outside the editor. Your current canvas and undo history have been kept.</p>
      <button type="button" className="mt-2 min-h-10 border border-neutral-400 px-3" onClick={() => useStore.getState().loadProject({ id: projectId })}>Review and reload saved design</button>
    </section>}
    {printMessage && <section className="border-t border-neutral-200 pt-4 dark:border-neutral-800"><h3 className="mb-2 text-sm font-semibold">Printing</h3><p>{printMessage}</p>
      {isPreparing && <>
        {progress && <progress aria-label="Label rendering progress" max={progress.total} value={progress.completed} className="mt-2 w-full accent-blue-600" />}
        <button type="button" onClick={() => onLocalRenderComplete([], new Error('Print preparation cancelled before submission.'), pendingPrintJob?.id)} className="mt-3 min-h-10 border border-neutral-400 px-3">Cancel preparation</button>
        <p className="mt-2">Nothing has been sent to the printer yet.</p>
      </>}
    </section>}
    {draft && <div className="mt-2 flex flex-wrap items-center gap-2" role="status">
      <span>{draft.invalid ? 'A browser recovery copy could not be read.' : 'A browser recovery copy is available. Recovering creates a new design.'}</span>
      {!draft.invalid && <button type="button" onClick={() => recover()} className="border border-blue-500 px-3 py-1">Recover as new design</button>}
      <button type="button" onClick={releaseDraft} className="border border-neutral-400 dark:border-neutral-600 px-3 py-1">Discard recovery copy</button>
    </div>}
    {notice && (dirty || !notice.startsWith('Recovered as a new unsaved design.')) && <p role="status" className="mt-2 text-amber-800 dark:text-amber-200">{notice}</p>}
    </div></EditorDrawer>}
    {recoveryConfirmation && <ConfirmActionDialog title="Recover the browser copy?" message="Recovery creates a new design and replaces the unsaved edits currently in the editor. Save those edits first if you want to keep them."
      actionLabel="Replace edits and recover" cancelLabel="Keep editing" onClose={() => setRecoveryConfirmation(null)} onConfirm={() => recover(recoveryConfirmation)} />}
  </>;
}

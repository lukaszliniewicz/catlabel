import { serializeCanvasDocument } from '../domain/document';
import { useStore } from '../store';

export const buildAiCanvasSnapshot = state => ({
  ...serializeCanvasDocument(state), __project_id__: state.currentProjectId,
  __project_revision__: state.currentProjectRevision,
  __dpi__: state.currentDpi || state.selectedPrinterInfo?.dpi || 203
});

// The request owner must accept the response before this synchronous apply.
export function applyAiCanvasResult(canvasState, notify) {
  if (!canvasState) return false;
  const store = useStore.getState();
  store.hydrateCanvasState(canvasState);
  let previewRequested = false;
  for (const action of canvasState.__actions__ || []) {
    if (action.action === 'print' || action.action === 'print_review_required') notify?.('The assistant requested printing. Review the labels, copies and printer, then use Print to submit the job. The assistant has not sent a print job.');
    else if (action.action === 'refresh_projects') store.fetchProjects();
    else if (action.action === 'loaded_project_id') store.setCurrentProjectId(action.project_id, action.revision);
    else if (action.action === 'frontend_visual_preview') previewRequested = true;
    else if (action.action === 'deletion_review_required') notify?.(`The assistant requested deletion review for ${action.target_kind} “${action.name}” (ID ${action.target_id}). Open Projects → Actions → Delete to review and confirm. No saved content was deleted by the assistant.`);
  }
  return previewRequested;
}

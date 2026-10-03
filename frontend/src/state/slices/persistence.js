import { serializeCanvasDocument } from '../../domain/document';
import { apiFetch, apiJson, isArrayPayload, isObjectPayload } from '../../utils/apiClient';
import { documentSnapshot } from '../documentLifecycle';
import { errorMessage } from '../errors';

let projectLoadRequestId = 0;

export const createPersistenceSlice = (set, get) => ({
  projects: [],
  categories: [],
  currentProjectId: null,
  currentProjectRevision: null,
  pendingProjectLoad: null,
  cancelProjectLoad: () => set({ pendingProjectLoad: null }, false, { history: 'skip' }),
  confirmProjectLoad: () => {
    const pending = get().pendingProjectLoad;
    if (!pending) return false;
    return get().loadProject(pending.summary, pending);
  },
  setCurrentProjectId: (id, revision = null) => set({
    currentProjectId: id,
    currentProjectRevision: Number.isInteger(revision) && revision > 0 ? revision : null
  }),
  fetchProjects: async () => {
    try {
      const loadSummaries = async () => {
        const projects = [];
        let afterId = 0;
        for (let page = 0; page < 50; page += 1) {
          const result = await apiJson(`/api/projects/summaries?limit=200&after_id=${afterId}`, {}, {
            validate: isObjectPayload, validationMessage: 'Project summary data is malformed.'
          });
          if (!Array.isArray(result.projects)) throw new Error('Project summary data is malformed.');
          projects.push(...result.projects);
          if (result.next_after_id == null) return projects;
          if (!Number.isInteger(result.next_after_id) || result.next_after_id <= afterId) {
            throw new Error('Project pagination returned an invalid cursor.');
          }
          afterId = result.next_after_id;
        }
        throw new Error('The project tree exceeds the 10,000-project limit.');
      };
      const [projects, categories] = await Promise.all([
        loadSummaries(),
        apiJson('/api/categories', {}, { validate: isArrayPayload, validationMessage: 'Category data is malformed.' })
      ]);
      set({ projects, categories });
    } catch (e) {
      console.error("Failed to fetch projects/categories", e);
      set({ apiError: errorMessage(e, 'Failed to load projects and folders.') });
    }
  },
  createCategory: async (name, parentId = null) => {
    try {
      await apiFetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, parent_id: parentId })
      });
      get().fetchProjects();
    } catch (e) {
      console.error(e);
      set({ apiError: errorMessage(e, 'Failed to create the folder.') });
    }
  },
  updateCategory: async (id, name = undefined, parentId = undefined) => {
    try {
      await apiFetch(`/api/categories/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, parent_id: parentId })
      });
      get().fetchProjects();
    } catch (e) {
      console.error(e);
      set({ apiError: errorMessage(e, 'Failed to update the folder.') });
    }
  },
  deleteCategory: async (id) => {
    if (!window.confirm("Delete this folder AND all its contents recursively?")) return;
    try {
      await apiFetch(`/api/categories/${id}`, { method: 'DELETE' });
      get().fetchProjects();
    } catch (e) {
      console.error(e);
      set({ apiError: errorMessage(e, 'Failed to delete the folder.') });
    }
  },
  saveProject: async (name, categoryId = null) => {
    const state = get();
    if (state.saveStatus === 'saving') return false;
    const snapshot = documentSnapshot(state);
    const session = state.documentSessionId;
    set({ saveStatus: 'saving' }, false, { history: 'skip' });

    try {
      const res = await apiFetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          category_id: categoryId,
          canvas_state: serializeCanvasDocument(state)
        })
      });
      const data = await res.json();
      if (!isObjectPayload(data) || data.id === undefined) throw new Error('The saved project response is malformed.');
      if (!Number.isInteger(data.revision) || data.revision < 1) throw new Error('The saved project revision is missing.');
      if (get().documentSessionId === session) {
        set({ currentProjectId: data.id, currentProjectRevision: data.revision }, false,
          { history: 'skip', savedDocument: snapshot });
      }
      get().fetchProjects();
      return true;
    } catch (e) {
      console.error(e);
      if (get().documentSessionId === session) {
        set({ saveStatus: 'failed', apiError: errorMessage(e, 'Failed to save the project.') }, false, { history: 'skip' });
      }
      return false;
    }
  },
  updateProject: async (id, newName = null, newCategoryId = undefined) => {
    const state = get();

    const session = state.documentSessionId;
    const snapshot = documentSnapshot(state);
    const writesCanvas = newName == null && newCategoryId === undefined;
    if (writesCanvas && state.saveStatus === 'saving') return false;
    const expectedRevision = state.currentProjectId === id
      ? state.currentProjectRevision
      : state.projects.find((project) => project.id === id)?.revision;
    if (!Number.isInteger(expectedRevision) || expectedRevision < 1) {
      set({ apiError: 'Reload the saved project before updating it; its revision is unavailable.' });
      return;
    }
    const payload = { expected_revision: expectedRevision };
    if (writesCanvas) payload.canvas_state = serializeCanvasDocument(state);
    if (newName != null) payload.name = newName;
    if (newCategoryId !== undefined) payload.category_id = newCategoryId;

    if (writesCanvas) set({ saveStatus: 'saving' }, false, { history: 'skip' });
    try {
      const response = await apiFetch(`/api/projects/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!isObjectPayload(data) || !Number.isInteger(data.revision) || data.revision < 1) {
        throw new Error('The updated project response is malformed. Reload before saving again.');
      }
      if (get().currentProjectId === id && get().documentSessionId === session) {
        set({ currentProjectRevision: data.revision }, false,
          { history: 'skip', ...(writesCanvas ? { savedDocument: snapshot } : {}) });
      }
      if (writesCanvas && get().documentSessionId === session && get().currentProjectId !== id) {
        set({ saveStatus: get().isDocumentDirty ? 'dirty' : 'saved' }, false, { history: 'skip' });
      }
      get().fetchProjects();
      return true;
    } catch (e) {
      console.error(e);
      if (get().documentSessionId === session) {
        set({ ...(writesCanvas ? { saveStatus: 'failed' } : {}),
          apiError: errorMessage(e, 'Failed to update the project.') }, false, { history: 'skip' });
      }
      return false;
    }
  },
  deleteProject: async (id) => {
    if (!window.confirm("Are you sure you want to delete this project?")) return;
    try {
      await apiFetch(`/api/projects/${id}`, { method: 'DELETE' });
      get().fetchProjects();
      if (get().currentProjectId === id) {
        set({ currentProjectId: null, currentProjectRevision: null }, false, { history: 'skip', document: 'detach' });
      }
    } catch (e) {
      console.error(e);
      set({ apiError: errorMessage(e, 'Failed to delete the project.') });
    }
  },
  loadProject: async (summary, approval = null) => {
    const requestId = ++projectLoadRequestId;
    if (approval && (get().documentSessionId !== approval.session || get().documentRevision !== approval.revision)) {
      set({ pendingProjectLoad: null, apiError: 'The design changed while confirmation was open. Your edits were kept; open the project again when ready.' }, false, { history: 'skip' });
      return false;
    }
    if (get().isDocumentDirty && !approval) {
      set({ pendingProjectLoad: { summary, session: get().documentSessionId, revision: get().documentRevision } }, false, { history: 'skip' });
      return false;
    }
    if (get().pendingProjectLoad) set({ pendingProjectLoad: null }, false, { history: 'skip' });
    const { documentSessionId: session, documentRevision: revision } = get();
    try {
      const proj = summary.canvas_state !== undefined ? summary : await apiJson(`/api/projects/${summary.id}`, {}, {
        validate: isObjectPayload, validationMessage: 'Project data is malformed.'
      });
      if (requestId !== projectLoadRequestId) return false;
      if (get().documentSessionId !== session || get().documentRevision !== revision) {
        set({ apiError: 'The design changed while this project was opening. Your edits were kept; open the project again when ready.' }, false, { history: 'skip' });
        return false;
      }
      if (!isObjectPayload(proj.canvas_state)) throw new Error('The project document is malformed.');
      get().hydrateCanvasState(proj.canvas_state, {
        currentProjectId: proj.id,
        currentProjectRevision: proj.revision ?? null,
        resetHistory: true
      });
    } catch (error) {
      if (requestId !== projectLoadRequestId) return;
      set({ apiError: errorMessage(error, 'Failed to open the project.') }, false, { history: 'skip' });
    }
  }
});

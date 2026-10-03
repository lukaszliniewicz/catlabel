import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useStore } from '../../store';
import * as apiClient from '../../utils/apiClient';
const original = useStore.getState();
beforeEach(() => useStore.setState({ ...original, fetchProjects: vi.fn(), apiError: null }, true));
afterEach(() => { useStore.setState(original, true); vi.restoreAllMocks(); });
test('overwrite rejects a changed saved revision before sending any update', async () => {
  useStore.setState({ projects: [{ id: 8, revision: 4 }] });
  const request = vi.spyOn(apiClient, 'apiFetch');
  expect(await useStore.getState().updateProject(8, null, undefined, 3)).toBe(false);
  expect(request).not.toHaveBeenCalled();
  expect(useStore.getState().apiError).toContain('changed while confirmation');
});
test('recursive folder deletion detaches saved identity while retaining canvas and dirty recovery state', async () => {
  useStore.getState().hydrateCanvasState({ items: [{ id: 'kept', type: 'text' }] }, { currentProjectId: 8, currentProjectRevision: 4 });
  useStore.setState({ categories: [{ id: 1 }, { id: 3, parent_id: 2 }, { id: 2, parent_id: 1 }], projects: [{ id: 8, category_id: 3 }] });
  const request = vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({});
  expect(await useStore.getState().deleteCategory(1)).toBe(true);
  expect(request).toHaveBeenCalledWith('/api/categories/1', { method: 'DELETE' });
  expect(useStore.getState()).toMatchObject({ currentProjectId: null, currentProjectRevision: null, items: [{ id: 'kept' }], isDocumentDirty: true });
});
test.each(['deleteProject', 'deleteCategory'])('%s failure retains identity and canvas and reports false', async method => {
  useStore.setState({ currentProjectId: 8, currentProjectRevision: 4, items: [{ id: 'kept' }] });
  vi.spyOn(apiClient, 'apiFetch').mockRejectedValue(new Error('Delete refused'));
  expect(await useStore.getState()[method](8)).toBe(false);
  expect(useStore.getState()).toMatchObject({ currentProjectId: 8, currentProjectRevision: 4, items: [{ id: 'kept' }], apiError: 'Delete refused' });
});

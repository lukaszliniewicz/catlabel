export const createSelectionSlice = (set) => ({
  selectedId: null,
  selectedIds: [],
  selectItem: (id, multi = false) => set((state) => {
    if (!id) return { selectedId: null, selectedIds: [] };
    if (multi) {
      const newIds = state.selectedIds.includes(id)
        ? state.selectedIds.filter((itemId) => itemId !== id)
        : [...state.selectedIds, id];
      return {
        selectedIds: newIds,
        selectedId: newIds.length > 0 ? newIds[newIds.length - 1] : null
      };
    }
    return { selectedId: id, selectedIds: [id] };
  }),
  selectItems: (ids, multi = false) => set((state) => {
    if (!ids || ids.length === 0) return state;
    if (multi) {
      const newIds = [...new Set([...state.selectedIds, ...ids])];
      return {
        selectedIds: newIds,
        selectedId: newIds.length > 0 ? newIds[newIds.length - 1] : null
      };
    }
    return {
      selectedIds: ids,
      selectedId: ids.length > 0 ? ids[ids.length - 1] : null
    };
  })
});

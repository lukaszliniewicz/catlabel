import { buildCanvasDocumentPatch, buildTemplateHtml, recalcAutoFit } from '../../domain/normalization';
import { normalizePageIndex } from '../../utils/canvasPages';
import { calculateAutoFitItem } from '../../utils/rendering';

export const createDocumentSlice = (set, get) => ({
  history: [],
  historyIndex: -1,
  canUndo: false,
  canRedo: false,
  undo: () => set((state) => {
    if (state.historyIndex > 0) {
      const newIndex = state.historyIndex - 1;
      const snap = state.history[newIndex];
      return {
        ...snap,
        historyIndex: newIndex,
        selectedId: null,
        selectedIds: [],
        _isUndoRedo: true,
        canUndo: newIndex > 0,
        canRedo: true
      };
    }
    return state;
  }),
  redo: () => set((state) => {
    if (state.history && state.historyIndex < state.history.length - 1) {
      const newIndex = state.historyIndex + 1;
      const snap = state.history[newIndex];
      return {
        ...snap,
        historyIndex: newIndex,
        selectedId: null,
        selectedIds: [],
        _isUndoRedo: true,
        canUndo: true,
        canRedo: newIndex < state.history.length - 1
      };
    }
    return state;
  }),
  items: [],
  canvasWidth: 384,
  canvasHeight: 384,
  canvasBorder: 'none',
  canvasBorderThickness: 4,
  splitMode: false,
  isRotated: false,
  pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: null }],
  setHtmlContent: (val) => set((state) => {
    const layouts = [...state.pageLayouts];
    const idx = layouts.findIndex(l => l.pageIndex === state.currentPage);
    if (idx >= 0) layouts[idx] = { ...layouts[idx], htmlContent: val, activeTemplate: null };
    else layouts.push({ pageIndex: state.currentPage, htmlContent: val, activeTemplate: null });
    return { pageLayouts: layouts };
  }),
  setTemplateConfig: (id, params = {}) => set((state) => ({
    pageLayouts: [...state.pageLayouts.filter(l => l.pageIndex !== state.currentPage), {
      pageIndex: state.currentPage,
      activeTemplate: { id, params },
      htmlContent: buildTemplateHtml(id, params, state.canvasWidth, state.canvasHeight)
    }]
  })),
  updateTemplateParams: (newParams) => set((state) => {
    const layout = state.pageLayouts.find(l => l.pageIndex === state.currentPage);
    if (!layout || !layout.activeTemplate) return state;
    const params = { ...layout.activeTemplate.params, ...newParams };

    const layouts = [...state.pageLayouts];
    const idx = layouts.findIndex(l => l.pageIndex === state.currentPage);
    layouts[idx] = {
      ...layout,
      activeTemplate: { ...layout.activeTemplate, params },
      htmlContent: buildTemplateHtml(layout.activeTemplate.id, params, state.canvasWidth, state.canvasHeight)
    };
    return { pageLayouts: layouts };
  }),
  ejectTemplate: () => set((state) => {
    const layouts = [...state.pageLayouts];
    const idx = layouts.findIndex(l => l.pageIndex === state.currentPage);
    if (idx >= 0) layouts[idx] = { ...layouts[idx], activeTemplate: null };
    return { pageLayouts: layouts };
  }),
  currentDpi: 203,
  currentPage: 0,
  setCurrentPage: (idx) => set({ currentPage: Math.max(0, Number(idx) || 0), selectedId: null, selectedIds: [] }),
  addPage: () => set((state) => {
    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0)),
      ...state.pageLayouts.map((l) => Number(l.pageIndex ?? 0))
    );
    return {
      currentPage: maxPage + 1,
      pageLayouts: [...state.pageLayouts, { pageIndex: maxPage + 1, htmlContent: '', activeTemplate: null }],
      selectedId: null,
      selectedIds: []
    };
  }),
  deletePage: (pageIndex) => set((state) => {
    const targetPage = Math.max(0, Number(pageIndex) || 0);

    const newItems = state.items
      .filter((item) => Number(item.pageIndex ?? 0) !== targetPage)
      .map((item) => {
        const itemPage = Number(item.pageIndex ?? 0);
        return itemPage > targetPage ? { ...item, pageIndex: itemPage - 1 } : item;
      });

    const newLayouts = state.pageLayouts
      .filter(l => l.pageIndex !== targetPage)
      .map(l => l.pageIndex > targetPage ? { ...l, pageIndex: l.pageIndex - 1 } : l);

    if (newLayouts.length === 0) newLayouts.push({ pageIndex: 0, htmlContent: '', activeTemplate: null });

    const adjustedCurrentPage = state.currentPage > targetPage
      ? state.currentPage - 1
      : state.currentPage === targetPage
        ? Math.max(0, targetPage - 1)
        : state.currentPage;

    const newSelectedPages = state.selectedPagesForPrint
      .filter((p) => p !== targetPage)
      .map((p) => (p > targetPage ? p - 1 : p));

    return {
      items: newItems,
      pageLayouts: newLayouts,
      currentPage: adjustedCurrentPage,
      selectedId: null,
      selectedIds: [],
      selectedPagesForPrint: newSelectedPages
    };
  }),
  duplicatePage: (pageIndex) => set((state) => {
    const targetPage = Math.max(0, Number(pageIndex) || 0);

    const itemsToClone = state.items.filter((item) => Number(item.pageIndex ?? 0) === targetPage);
    const layoutToClone = state.pageLayouts.find(l => l.pageIndex === targetPage) || { htmlContent: '' };

    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0)),
      ...state.pageLayouts.map((l) => Number(l.pageIndex ?? 0))
    );
    const newPageIdx = maxPage + 1;

    const clones = itemsToClone.map((item) => ({
      ...item,
      id: Date.now().toString() + '-' + Math.random().toString(36).substring(2, 7),
      pageIndex: newPageIdx
    }));

    return {
      items: [...state.items, ...clones],
      pageLayouts: [...state.pageLayouts, { ...layoutToClone, pageIndex: newPageIdx }],
      currentPage: newPageIdx,
      selectedId: null,
      selectedIds: []
    };
  }),
  getPxToMm: (px) => {
    const dpi = get().currentDpi || get().settings?.default_dpi || 203;
    return (Number(px || 0) / (dpi / 25.4)).toFixed(1);
  },
  getMmToPx: (mm) => {
    const dpi = get().currentDpi || get().settings?.default_dpi || 203;
    return Math.round(Number(mm || 0) * (dpi / 25.4));
  },
  pxToMm: (px) => parseFloat(get().getPxToMm(px)),
  mmToPx: (mm) => get().getMmToPx(mm),
  getActivePreset: () => {
    const state = get();
    const { labelPresets, canvasWidth, canvasHeight, isRotated, getMmToPx, selectedPrinterInfo } = state;
    const vendor = (selectedPrinterInfo?.vendor || '').toLowerCase();

    const matches = labelPresets.filter((p) => {
      const presetWidthPx = getMmToPx(p.width_mm);
      const presetHeightPx = getMmToPx(p.height_mm);
      const directMatch = Math.abs(presetWidthPx - canvasWidth) <= 2 && Math.abs(presetHeightPx - canvasHeight) <= 2;
      const swappedMatch = Math.abs(presetWidthPx - canvasHeight) <= 2 && Math.abs(presetHeightPx - canvasWidth) <= 2;
      return p.is_rotated === isRotated && (directMatch || swappedMatch);
    });

    if (matches.length === 0) return null;

    if (vendor) {
      const vendorMatch = matches.find((p) => p.name.toLowerCase().includes(vendor));
      if (vendorMatch) return vendorMatch;
    }

    return matches[0];
  },
  hydrateCanvasState: (canvasState, options = {}) => set(
    (state) => ({
      ...buildCanvasDocumentPatch(canvasState, state),
      ...(options.currentProjectId !== undefined
        ? { currentProjectId: options.currentProjectId }
        : {}),
      ...(options.currentProjectRevision !== undefined
        ? { currentProjectRevision: options.currentProjectRevision }
        : {})
    }),
    false,
    { history: options.resetHistory ? 'reset' : 'record' }
  ),
  applyPreset: (preset) => set((state) => {
    const widthMm = preset.width_mm ?? preset.w ?? 48;
    const heightMm = preset.height_mm ?? preset.h ?? 48;
    const isRotated = preset.is_rotated ?? preset.rotated ?? false;
    const splitMode = preset.split_mode ?? preset.splitMode ?? false;
    const nextCanvasWidth = state.getMmToPx(widthMm);
    const nextCanvasHeight = state.getMmToPx(heightMm);

    return {
      canvasWidth: nextCanvasWidth,
      canvasHeight: nextCanvasHeight,
      isRotated,
      splitMode,
      canvasBorder: preset.border || 'none',
      pageLayouts: state.pageLayouts.map(l => l.activeTemplate ? {
        ...l,
        htmlContent: buildTemplateHtml(l.activeTemplate.id, l.activeTemplate.params, nextCanvasWidth, nextCanvasHeight)
      } : l),
      items: recalcAutoFit(state.items, state.batchRecords, nextCanvasWidth, nextCanvasHeight)
    };
  }),
  setIsRotated: (val) => {
    const state = get();
    const nextRotation = Boolean(val);
    if (nextRotation === state.isRotated) return;
    state.setCanvasGeometry(state.canvasHeight, state.canvasWidth, nextRotation);
  },
  setCanvasBorder: (val) => set({ canvasBorder: val }),
  setCanvasBorderThickness: (val) => set({ canvasBorderThickness: val }),
  setSplitMode: (val) => set({ splitMode: val }),
  setItems: (items) => set((state) => ({
    items: recalcAutoFit(items, state.batchRecords, state.canvasWidth, state.canvasHeight),
    selectedId: null,
    selectedIds: [],
    selectedPagesForPrint: []
  })),
  clearCanvas: () => set({
    items: [],
    selectedId: null,
    selectedIds: [],
    currentPage: 0,
    selectedPagesForPrint: [],
    currentProjectId: null,
    currentProjectRevision: null,
    pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: null }]
    // We specifically omitted history wipes here so the user can Undo a canvas clear!
  }),
  addItem: (item) => set((state) => {
    const nextItem = item.pageIndex === undefined ? { ...item, pageIndex: state.currentPage } : item;
    return {
      items: [...state.items, nextItem],
      selectedId: nextItem.id,
      selectedIds: [nextItem.id],
      currentPage: normalizePageIndex(nextItem.pageIndex)
    };
  }),
  duplicateItem: (id, copies, gapMm) => set((state) => {
    const itemToClone = state.items.find(i => i.id === id);
    if (!itemToClone) return state;

    const newItems = [];
    const gapPx = get().getMmToPx(gapMm);
    const numLines = itemToClone.text ? String(itemToClone.text).split('\n').length : 1;
    const pad = itemToClone.padding !== undefined ? Number(itemToClone.padding) : 0;
    const actualLineHeight = itemToClone.lineHeight ?? (numLines > 1 ? 1.15 : 1);
    const approxHeight = itemToClone.height || (itemToClone.type === 'text' ? (itemToClone.size * actualLineHeight * numLines) + (pad * 2) : 50);

    let currentY = itemToClone.y;

    for (let i = 1; i <= copies; i++) {
      currentY += approxHeight + gapPx;
      newItems.push({
        ...itemToClone,
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substring(2, 7),
        y: currentY
      });
    }
    return { items: [...state.items, ...newItems] };
  }),
  multiplyWorkspace: (copies) => set((state) => {
    const totalCopies = Math.max(1, Number(copies) || 1);

    const currentItems = state.items.filter((item) => Number(item.pageIndex ?? 0) === state.currentPage);
    const currentLayout = state.pageLayouts.find(l => l.pageIndex === state.currentPage) || { htmlContent: '' };

    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0)),
      ...state.pageLayouts.map((l) => Number(l.pageIndex ?? 0))
    );
    const newItems = [...state.items];
    const newLayouts = [...state.pageLayouts];

    for (let i = 1; i <= totalCopies; i++) {
      const targetPage = maxPage + i;
      const clones = currentItems.map((item) => ({
        ...item,
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substring(2, 7),
        pageIndex: targetPage
      }));
      newItems.push(...clones);
      newLayouts.push({ ...currentLayout, pageIndex: targetPage });
    }

    return {
      items: newItems,
      pageLayouts: newLayouts,
      selectedId: null
    };
  }),
  updateItem: (id, newAttrs) => set((state) => {
    const newItems = state.items.map((item) => {
      if (item.id === id) {
        const updatedItem = { ...item, ...newAttrs };
        if (updatedItem.fit_to_width) {
          return calculateAutoFitItem(updatedItem, state.batchRecords, state.canvasWidth, state.canvasHeight);
        }
        return updatedItem;
      }
      return item;
    });

    return { items: newItems };
  }),
  moveItemZ: (dir) => set((state) => {
    if (!state.selectedId) return state;

    const items = [...state.items];
    const idx = items.findIndex((item) => item.id === state.selectedId);
    if (idx < 0) return state;

    const item = items[idx];
    const pageItems = items.filter((candidate) => candidate.pageIndex === item.pageIndex);
    const pageIdx = pageItems.findIndex((candidate) => candidate.id === item.id);

    if (dir === 'up' && pageIdx < pageItems.length - 1) {
      const targetId = pageItems[pageIdx + 1].id;
      const targetIdx = items.findIndex((candidate) => candidate.id === targetId);
      [items[idx], items[targetIdx]] = [items[targetIdx], items[idx]];
    } else if (dir === 'down' && pageIdx > 0) {
      const targetId = pageItems[pageIdx - 1].id;
      const targetIdx = items.findIndex((candidate) => candidate.id === targetId);
      [items[idx], items[targetIdx]] = [items[targetIdx], items[idx]];
    }

    return { items };
  }),
  groupSelected: () => set((state) => {
    if (state.selectedIds.length < 2) return state;

    const selectedItems = state.items.filter((item) => state.selectedIds.includes(item.id));
    if (selectedItems.length < 2) return state;

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    selectedItems.forEach((item) => {
      const pad = item.padding !== undefined ? Number(item.padding) : 0;
      const numLines = item.text ? String(item.text).split('\n').length : 1;
      const actualLineHeight = item.lineHeight ?? (numLines > 1 ? 1.15 : 1);
      const approxHeight = item.height || (item.type === 'text' ? (item.size * actualLineHeight * numLines) + (pad * 2) : 50);
      const width = item.width || 100;

      if (item.x < minX) minX = item.x;
      if (item.y < minY) minY = item.y;
      if (item.x + width > maxX) maxX = item.x + width;
      if (item.y + approxHeight > maxY) maxY = item.y + approxHeight;
    });

    const children = selectedItems.map((item) => ({
      ...item,
      x: item.x - minX,
      y: item.y - minY
    }));

    const newGroup = {
      id: Date.now().toString(),
      type: 'group',
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
      pageIndex: selectedItems[0].pageIndex,
      children
    };

    const newItems = state.items.filter((item) => !state.selectedIds.includes(item.id));
    newItems.push(newGroup);

    return {
      items: newItems,
      selectedIds: [newGroup.id],
      selectedId: newGroup.id
    };
  }),
  ungroupSelected: () => set((state) => {
    const group = state.items.find((item) => item.id === state.selectedId && item.type === 'group');
    if (!group) return state;

    const newItems = state.items.filter((item) => item.id !== group.id);
    const ungroupedIds = [];

    group.children.forEach((child) => {
      const newId = Date.now().toString() + Math.random().toString(36).substring(2, 7);
      ungroupedIds.push(newId);
      newItems.push({
        ...child,
        id: newId,
        x: child.x + group.x,
        y: child.y + group.y,
        pageIndex: group.pageIndex
      });
    });

    return {
      items: newItems,
      selectedIds: ungroupedIds,
      selectedId: ungroupedIds[0] || null
    };
  }),
  fitGroupToWidth: () => set((state) => {
    const group = state.items.find((item) => item.id === state.selectedId && item.type === 'group');
    if (!group || !group.width) return state;

    const scale = state.canvasWidth / group.width;

    const scaledChildren = group.children.map((child) => {
      const nextChild = {
        ...child,
        x: child.x * scale,
        y: child.y * scale
      };

      if (nextChild.width) nextChild.width *= scale;
      if (nextChild.height) nextChild.height *= scale;

      if (child.type === 'text') {
        nextChild.size = Math.round(child.size * scale);
        if (child.padding !== undefined) {
          nextChild.padding = Math.round(child.padding * scale);
        }
      }

      if (child.type === 'icon_text') {
        nextChild.size = Math.round(child.size * scale);
        nextChild.icon_size = Math.round(child.icon_size * scale);
        nextChild.icon_x = child.icon_x * scale;
        nextChild.icon_y = child.icon_y * scale;
        nextChild.text_x = child.text_x * scale;
        nextChild.text_y = child.text_y * scale;
      }

      if (child.border_thickness) {
        nextChild.border_thickness = Math.round(child.border_thickness * scale);
      }

      return nextChild;
    });

    const newGroup = {
      ...group,
      x: 0,
      width: state.canvasWidth,
      height: group.height * scale,
      children: scaledChildren
    };

    return {
      items: state.items.map((item) => item.id === group.id ? newGroup : item)
    };
  }),
  deleteItem: (id) => set((state) => {
    const newItems = state.items.filter((item) => item.id !== id);
    const newIds = state.selectedIds.filter((itemId) => itemId !== id);
    return {
      items: newItems,
      selectedIds: newIds,
      selectedId: newIds.length > 0 ? newIds[newIds.length - 1] : null
    };
  }),
  deleteSelectedItems: () => set((state) => {
    const newItems = state.items.filter((item) => !state.selectedIds.includes(item.id));
    return {
      items: newItems,
      selectedIds: [],
      selectedId: null
    };
  }),
  moveSelectedItems: (dx, dy) => set((state) => {
    if (state.selectedIds.length === 0) return state;
    const newItems = state.items.map(item => {
      if (state.selectedIds.includes(item.id)) {
        return { ...item, x: item.x + dx, y: item.y + dy };
      }
      return item;
    });
    return { items: newItems };
  }),
  setCanvasGeometry: (width, height, isRotated = get().isRotated) => set((state) => {
    const nextWidth = Math.min(20_000, Math.max(1, Number(width) || 1));
    const nextHeight = Math.min(20_000, Math.max(1, Number(height) || 1));
    return {
      canvasWidth: nextWidth,
      canvasHeight: nextHeight,
      isRotated: Boolean(isRotated),
      pageLayouts: state.pageLayouts.map(l => l.activeTemplate ? {
        ...l,
        htmlContent: buildTemplateHtml(l.activeTemplate.id, l.activeTemplate.params, nextWidth, nextHeight)
      } : l),
      items: recalcAutoFit(state.items, state.batchRecords, nextWidth, nextHeight)
    };
  }),
  setCanvasSize: (width, height) => get().setCanvasGeometry(width, height, get().isRotated)
});

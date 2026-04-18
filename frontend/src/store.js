import { create } from 'zustand';
import { toPng } from 'html-to-image';
import { calculateAutoFitItem } from './utils/rendering';

const recalcAutoFit = (items, batchRecords, cw, ch) => {
  let changed = false;

  const nextItems = items.map((item) => {
    if (item.fit_to_width) {
      const optimizedItem = calculateAutoFitItem(item, batchRecords, cw, ch);
      if (optimizedItem.size !== item.size) {
        changed = true;
        return optimizedItem;
      }
    }
    return item;
  });

  return changed ? nextItems : items;
};

const withHistory = (config) => {
  let historyTimeout;
  let storedPrevState = null;

  return (set, get, api) => {
    const historySet = (args, replace) => {
      if (!storedPrevState) {
        storedPrevState = get();
      }

      set(args, replace);
      const nextState = get();

      if (nextState._isUndoRedo) {
        set({ _isUndoRedo: false });
        storedPrevState = null;
        return;
      }

      if (nextState.historyIndex === -1 && nextState.history && nextState.history.length === 0) {
        return;
      }

      clearTimeout(historyTimeout);
      historyTimeout = setTimeout(() => {
        const finalState = get();
        const relevantKeys = ['items', 'canvasWidth', 'canvasHeight', 'isRotated', 'splitMode', 'canvasBorder', 'canvasBorderThickness', 'designMode', 'htmlContent'];
        let changed = false;

        for (const key of relevantKeys) {
          if (storedPrevState[key] !== finalState[key]) {
            changed = true;
            break;
          }
        }

        if (changed) {
          const snap = {};
          for (const key of relevantKeys) {
            snap[key] = finalState[key];
          }

          const currentHistory = finalState.history || [];
          const currentIndex = finalState.historyIndex !== undefined ? finalState.historyIndex : -1;

          let newHistory = currentHistory.slice(0, currentIndex + 1);

          if (newHistory.length === 0) {
            const prevSnap = {};
            for (const key of relevantKeys) {
              prevSnap[key] = storedPrevState[key];
            }
            newHistory.push(prevSnap);
          }

          newHistory.push(snap);
          if (newHistory.length > 50) newHistory.shift();

          set({
            history: newHistory,
            historyIndex: newHistory.length - 1,
            canUndo: newHistory.length > 1,
            canRedo: false
          });
        }

        storedPrevState = null;
      }, 400);
    };

    return config(historySet, get, api);
  };
};

export const useStore = create(withHistory((set, get) => ({
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
  selectedId: null,
  selectedIds: [],
  zoomScale: 1,
  canvasWidth: 384,
  canvasHeight: 384,
  canvasBorder: 'none',
  canvasBorderThickness: 4,
  splitMode: false,
  isRotated: false,
  selectedPrinter: null,
  selectedPrinterInfo: null,
  designMode: 'canvas',
  htmlContent: '',
  showAiConfig: false,
  setShowAiConfig: (val) => set({ showAiConfig: val }),
  setDesignMode: (val) => set({ designMode: val }),
  setHtmlContent: (val) => set({ htmlContent: val }),
  getStageB64: async () => {
    if (typeof window !== 'undefined' && window.__getStageB64) {
      return await window.__getStageB64();
    }
    return null;
  },
  setZoomScale: (scale) => set({ zoomScale: Math.max(0.1, Math.min(5, scale)) }),
  manualPrinters: (() => {
    if (typeof window === 'undefined') return [];
    try {
      return JSON.parse(window.localStorage.getItem('catlabel_manual_printers') || '[]');
    } catch (e) {
      console.error('Failed to load manual printers', e);
      return [];
    }
  })(),
  addManualPrinter: (printer) => set((state) => {
    const newManual = [...state.manualPrinters.filter((p) => p.address !== printer.address), printer];
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('catlabel_manual_printers', JSON.stringify(newManual));
    }
    return { manualPrinters: newManual };
  }),
  removeManualPrinter: (address) => set((state) => {
    const newManual = state.manualPrinters.filter((p) => p.address !== address);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('catlabel_manual_printers', JSON.stringify(newManual));
    }
    return { manualPrinters: newManual };
  }),
  batchRecords: [{}],
  printCopies: 1,
  theme: 'auto',
  dither: true,
  setDither: (val) => set({ dither: val }),
  snapLines: [],
  fonts: [],
  labelPresets: [],
  currentDpi: 203,
  printerProfile: { speed: 0, energy: 0, feed_lines: 50 },
  currentPage: 0,
  
  setCurrentPage: (idx) => set({ currentPage: Math.max(0, Number(idx) || 0), selectedId: null, selectedIds: [] }),
  
  addPage: () => set((state) => {
    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0))
    );
    return { currentPage: maxPage + 1, selectedId: null, selectedIds: [] };
  }),
  
  deletePage: (pageIndex) => set((state) => {
    const targetPage = Math.max(0, Number(pageIndex) || 0);
    const newItems = state.items
      .filter((item) => Number(item.pageIndex ?? 0) !== targetPage)
      .map((item) => {
        const itemPage = Number(item.pageIndex ?? 0);
        return itemPage > targetPage ? { ...item, pageIndex: itemPage - 1 } : item;
      });

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
      currentPage: adjustedCurrentPage,
      selectedId: null,
      selectedIds: [],
      selectedPagesForPrint: newSelectedPages
    };
  }),
  
  duplicatePage: (pageIndex) => set((state) => {
    const targetPage = Math.max(0, Number(pageIndex) || 0);
    const itemsToClone = state.items.filter((item) => Number(item.pageIndex ?? 0) === targetPage);
    if (!itemsToClone.length) return state;

    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0))
    );
    const newPageIdx = maxPage + 1;

    const clones = itemsToClone.map((item) => ({
      ...item,
      id: Date.now().toString() + '-' + Math.random().toString(36).substring(2, 7),
      pageIndex: newPageIdx
    }));

    return {
      items: [...state.items, ...clones],
      currentPage: newPageIdx,
      selectedId: null,
      selectedIds: []
    };
  }),

  selectedPagesForPrint: [],
  isPreparingForPrint: false,
  pendingPrintJob: null,
  isPrinting: false,
  setIsPrinting: (val) => set({ isPrinting: val }),
  
  togglePageForPrint: (pageIndex) => set((state) => {
    const current = state.selectedPagesForPrint;
    if (current.includes(pageIndex)) {
      return { selectedPagesForPrint: current.filter((p) => p !== pageIndex) };
    }
    return { selectedPagesForPrint: [...current, pageIndex] };
  }),

  printPages: async (pageIndices) => {
    const state = get();

    if (state.isPreparingForPrint || state.isPrinting) {
      return;
    }

    if (!state.selectedPrinter) {
      alert("Please select a printer first!");
      return;
    }

    if (state.selectedPrinterInfo?.transport === 'offline') {
      alert("This is an offline/manual printer profile. Scan and select a connected printer before printing.");
      return;
    }

    const normalizedPageIndices = Array.from(
      new Set((pageIndices || []).map((pageIndex) => Math.max(0, Number(pageIndex) || 0)))
    ).sort((a, b) => a - b);
    if (normalizedPageIndices.length === 0) return;

    const itemsToPrint = state.items.filter((item) =>
      normalizedPageIndices.includes(Number(item.pageIndex ?? 0))
    );

    set({
      isPreparingForPrint: true,
      pendingPrintJob: {
        macAddress: state.selectedPrinter,
        splitMode: state.splitMode,
        pageIndices: normalizedPageIndices,
        copies: state.printCopies || 1,
        batchRecords: state.batchRecords || [{}],
        dither: state.dither,
        canvasState: {
          width: state.canvasWidth,
          height: state.canvasHeight,
          isRotated: state.isRotated,
          canvasBorder: state.canvasBorder,
          canvasBorderThickness: state.canvasBorderThickness || 4,
          splitMode: state.splitMode,
          designMode: state.designMode,
          htmlContent: state.htmlContent,
          items: itemsToPrint
        }
      }
    });
  },

  onLocalRenderComplete: async (images) => {
    const state = get();
    const pendingPrintJob = state.pendingPrintJob;

    set({ isPreparingForPrint: false });

    if (!pendingPrintJob) {
      return;
    }

    if (!images || images.length === 0) {
      set({ pendingPrintJob: null });
      return;
    }

    set({ isPrinting: true });

    try {
      const printRes = await fetch(`/api/print/images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: pendingPrintJob.macAddress,
          images,
          split_mode: pendingPrintJob.splitMode,
          is_rotated: pendingPrintJob.canvasState.isRotated || false,
          dither: pendingPrintJob.dither
        })
      });

      if (!printRes.ok) {
        const err = await printRes.json();
        throw new Error(err.detail || "Print failed");
      }
    } catch (e) {
      console.error(e);
      alert(`Failed to print: ${e.message}`);
    } finally {
      set({ isPrinting: false, pendingPrintJob: null });
    }
  },

  isSidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  
  addresses: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 50, default_font: 'RobotoCondensed.ttf', intended_media_type: 'unknown' },
  settingsLoaded: false,
  
  // Refined DPI Math logic that safely falls back
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

  // --- AI CHAT STATE ---
  aiMessages: [{ role: 'assistant', content: 'Hi! I am the CatLabel AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }],
  aiInput: '',
  aiConvId: null,
  aiSessionUsage: { tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 },
  setAiMessages: (msgs) => set({ aiMessages: msgs }),
  setAiInput: (input) => set({ aiInput: input }),
  setAiConvId: (id) => set({ aiConvId: id }),
  setAiSessionUsage: (usage) => set({ aiSessionUsage: usage }),
  resetAiChat: () => set({
    aiMessages: [{ role: 'assistant', content: 'Hi! I am the CatLabel AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }],
    aiInput: '',
    aiConvId: null,
    aiSessionUsage: { tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 }
  }),

  // --- HIERARCHICAL PROJECT MANAGEMENT ---
  projects: [],
  categories: [],
  currentProjectId: null,
  
  setCurrentProjectId: (id) => set({ currentProjectId: id }),

  setBatchRecords: (records) => set((state) => {
    const validRecords = Array.isArray(records) && records.length ? records : [{}];
    return {
      batchRecords: validRecords,
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  generateBatchMatrix: (matrixDef) => set((state) => {
    const keys = Object.keys(matrixDef || {});
    if (keys.length === 0) {
      return {};
    }

    const parsedArrays = keys.map((key) => {
      const values = String(matrixDef[key] || '')
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
      return values.length > 0 ? values : [''];
    });

    const combinations = parsedArrays.reduce(
      (accumulator, values) =>
        accumulator.flatMap((recordPrefix) =>
          values.map((value) => [...recordPrefix, value])
        ),
      [[]]
    );

    const records = combinations.map((combo) => {
      const record = {};
      keys.forEach((key, index) => {
        record[key] = combo[index];
      });
      return record;
    });

    const validRecords = records.length ? records : [{}];
    return {
      batchRecords: validRecords,
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  generateBatchSequence: (seqDef) => set((state) => {
    const { varName, start, end, prefix = '', suffix = '', padding = 0 } = seqDef || {};
    if (!varName) return {};

    const s = parseInt(start, 10) || 0;
    const e = parseInt(end, 10) || 0;
    const pad = Math.max(0, parseInt(padding, 10) || 0);
    const step = s <= e ? 1 : -1;

    const records = [];
    for (let i = s; step > 0 ? i <= e : i >= e; i += step) {
      const numStr = String(i).padStart(pad, '0');
      records.push({ [varName]: `${prefix}${numStr}${suffix}` });
    }

    const validRecords = records.length ? records : [{}];
    return {
      batchRecords: validRecords,
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  updateBatchRecord: (index, newRecord) => set((state) => {
    const newRecords = [...state.batchRecords];
    newRecords[index] = newRecord;
    return {
      batchRecords: newRecords,
      items: recalcAutoFit(state.items, newRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  addBatchRecord: (record = {}) => set((state) => {
    const newRecords = [...state.batchRecords, record];
    return {
      batchRecords: newRecords,
      items: recalcAutoFit(state.items, newRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  removeBatchRecord: (index) => set((state) => {
    const newRecords = state.batchRecords.filter((_, i) => i !== index);
    const validRecords = newRecords.length ? newRecords : [{}];
    return {
      batchRecords: validRecords,
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  setPrintCopies: (n) => set({
    printCopies: Math.max(1, Number(n) || 1)
  }),

  fetchPresets: async () => {
    try {
      const res = await fetch('/api/presets');
      let data = await res.json();

      const standard48 = data.find((p) => p.name.includes('Standard Square (48x48mm)'));
      const a6Shipping = data.find((p) => p.name.includes('A6 Shipping'));

      data = data.filter((p) => p !== standard48 && p !== a6Shipping);

      if (standard48) data.unshift(standard48);
      if (a6Shipping) data.push(a6Shipping);

      set({ labelPresets: data });
    } catch (e) {
      console.error("Failed to fetch presets", e);
    }
  },

  fetchProjects: async () => {
    try {
      const [projRes, catRes] = await Promise.all([
        fetch('/api/projects'),
        fetch('/api/categories')
      ]);
      const projects = await projRes.json();
      const categories = await catRes.json();
      set({ projects, categories });
    } catch (e) {
      console.error("Failed to fetch projects/categories", e);
    }
  },

  createCategory: async (name, parentId = null) => {
    try {
      await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, parent_id: parentId })
      });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  },

  updateCategory: async (id, name = undefined, parentId = undefined) => {
    try {
      await fetch(`/api/categories/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, parent_id: parentId })
      });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  },

  deleteCategory: async (id) => {
    if (!window.confirm("Delete this folder AND all its contents recursively?")) return;
    try {
      await fetch(`/api/categories/${id}`, { method: 'DELETE' });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  },

  saveProject: async (name, categoryId = null) => {
    const state = useStore.getState();
    const thickness = state.canvasBorderThickness || 4;
    const batchRecords = state.batchRecords || [{}];
    const printCopies = state.printCopies || 1;
    
    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          category_id: categoryId,
          canvas_state: {
            width: state.canvasWidth, height: state.canvasHeight,
            isRotated: state.isRotated, canvasBorder: state.canvasBorder,
            canvasBorderThickness: thickness, splitMode: state.splitMode,
            designMode: state.designMode, htmlContent: state.htmlContent,
            items: state.items, currentPage: state.currentPage,
            batchRecords, printCopies
          }
        })
      });
      const data = await res.json();
      set({ currentProjectId: data.id });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  },

  updateProject: async (id, newName = null, newCategoryId = undefined) => {
    const state = useStore.getState();
    const thickness = state.canvasBorderThickness || 4;
    const batchRecords = state.batchRecords || [{}];
    const printCopies = state.printCopies || 1;
    
    const payload = {
      canvas_state: {
        width: state.canvasWidth, height: state.canvasHeight,
        isRotated: state.isRotated, canvasBorder: state.canvasBorder,
        canvasBorderThickness: thickness, splitMode: state.splitMode,
        designMode: state.designMode, htmlContent: state.htmlContent,
        items: state.items, currentPage: state.currentPage,
        batchRecords, printCopies
      }
    };
    if (newName) payload.name = newName;
    if (newCategoryId !== undefined) payload.category_id = newCategoryId;

    try {
      await fetch(`/api/projects/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  },

  deleteProject: async (id) => {
    if (!window.confirm("Are you sure you want to delete this project?")) return;
    try {
      await fetch(`/api/projects/${id}`, { method: 'DELETE' });
      useStore.getState().fetchProjects();
      if (useStore.getState().currentProjectId === id) {
        set({ currentProjectId: null });
      }
    } catch (e) {
      console.error(e);
    }
  },

  loadProject: (proj) => {
    set({ currentProjectId: proj.id });
    const s = proj.canvas_state;
    const batchRecords = s.batchRecords || [{}];
    set({
      canvasWidth: s.width || 384,
      canvasHeight: s.height || 384,
      canvasBorder: s.canvasBorder || 'none',
      canvasBorderThickness: s.canvasBorderThickness || 4,
      splitMode: s.splitMode || false,
      designMode: s.designMode || 'canvas',
      htmlContent: s.htmlContent || '',
      isRotated: s.isRotated || false,
      batchRecords,
      printCopies: s.printCopies || 1,
      currentPage: s.currentPage || 0,
      items: recalcAutoFit(s.items || [], batchRecords, s.width || 384, s.height || 384),
      selectedId: null,
      selectedIds: [],
      selectedPagesForPrint: [],
      history: [],
      historyIndex: -1,
      canUndo: false,
      canRedo: false
    });
  },

  savePreset: async (presetData) => {
    const { name, description, media_type } = presetData;
    const state = get();
    const widthMm = parseFloat(state.getPxToMm(state.canvasWidth));
    const heightMm = parseFloat(state.getPxToMm(state.canvasHeight));

    try {
      await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: description || null,
          media_type: media_type || 'any',
          width_mm: widthMm,
          height_mm: heightMm,
          is_rotated: state.isRotated,
          split_mode: state.splitMode,
          border: state.canvasBorder
        })
      });
      await state.fetchPresets();
    } catch (e) {
      console.error("Failed to save preset", e);
    }
  },

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
      items: recalcAutoFit(state.items, state.batchRecords, nextCanvasWidth, nextCanvasHeight)
    };
  }),
  
  fetchAddresses: async () => {
    try {
      const res = await fetch('/api/addresses');
      const data = await res.json();
      set({ addresses: data });
    } catch (e) {
      console.error("Failed to fetch addresses", e);
    }
  },

  saveAddress: async (addr) => {
    try {
      await fetch('/api/addresses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addr)
      });
      useStore.getState().fetchAddresses();
    } catch (e) {
      console.error("Failed to save address", e);
    }
  },

  deleteAddress: async (id) => {
    try {
      await fetch(`/api/addresses/${id}`, { method: 'DELETE' });
      useStore.getState().fetchAddresses();
    } catch (e) {
      console.error("Failed to delete address", e);
    }
  },

  fetchSettings: async () => {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      set({ settings: data, settingsLoaded: true });
    } catch (e) {
      console.error("Failed to fetch settings", e);
    }
  },

  fetchFonts: async () => {
    try {
      const res = await fetch('/api/fonts');
      const data = await res.json();
      set({ fonts: data });
      
      const style = document.createElement('style');
      let css = '';
      data.forEach(font => {
        const fontName = font.name.split('.')[0];
        css += `@font-face { font-family: '${fontName}'; src: url('/${font.file_path}'); }\n`;
      });
      style.appendChild(document.createTextNode(css));
      document.head.appendChild(style);
    } catch (e) {
      console.error("Failed to fetch fonts", e);
    }
  },

  uploadFont: async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch('/api/fonts', {
        method: 'POST',
        body: formData
      });
      if (!res.ok) throw new Error("Failed to upload font");
      await get().fetchFonts();
    } catch (e) {
      console.error("Failed to upload font", e);
      alert("Failed to upload font file.");
    }
  },

  setIsRotated: (val) => set((state) => {
    if (val !== state.isRotated) {
      return {
        isRotated: val,
        canvasWidth: state.canvasHeight,
        canvasHeight: state.canvasWidth,
        items: recalcAutoFit(state.items, state.batchRecords, state.canvasHeight, state.canvasWidth)
      };
    }
    return { isRotated: val };
  }),

  setCanvasBorder: (val) => set({ canvasBorder: val }),
  setCanvasBorderThickness: (val) => set({ canvasBorderThickness: val }),
  setSplitMode: (val) => set({ splitMode: val }),
  setTheme: (theme) => set({ theme }),
  setSnapLines: (lines) => set({ snapLines: lines }),
  setSettings: (settings) => set({ settings }),
  
  updateSettingsAPI: async (newSettings) => {
    set({ settings: newSettings });
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings)
      });
    } catch (e) {
      console.error("Failed to save settings", e);
    }
  },
  
  setSelectedPrinter: async (mac, info) => {
    const currentState = get();
    let newW = currentState.canvasWidth;
    let newH = currentState.canvasHeight;
    let rot = currentState.isRotated;
    let border = currentState.canvasBorder;

    // Use the exact DPI passed by the hardware info payload
    const activeDpi = info?.dpi || 203;
    const calcMmToPx = (mm) => Math.round(mm * (activeDpi / 25.4));

    if (info) {
      const isNewPrinter = currentState.selectedPrinterInfo?.address !== mac;
      const isPreCutMedia = info.media_type === 'pre-cut';

      if (isNewPrinter) {
        if (isPreCutMedia) {
          const model = info.model_id ? info.model_id.toLowerCase() : '';

          if (model === 'd11' || model === 'd110' || model === 'd101') {
            newW = calcMmToPx(40);
            newH = calcMmToPx(15);
            rot = true;
          } else if (model === 'b1' || model === 'b21' || model === 'b18') {
            newW = calcMmToPx(50);
            newH = calcMmToPx(30);
            rot = true;
          } else {
            newW = info.width_px || calcMmToPx(48);
            newH = info.width_px || calcMmToPx(48);
            rot = false;
          }
          border = 'none';
        } else {
          const hardwareWidth = info.width_px || 384;

          if (hardwareWidth === 384) {
            newW = hardwareWidth;
            newH = hardwareWidth;
            rot = false;
          } else if (hardwareWidth > 384) {
            newW = hardwareWidth;
            newH = Math.round(hardwareWidth * 1.5);
            rot = false;
          } else {
            newW = calcMmToPx(40);
            newH = hardwareWidth;
            rot = true;
            border = 'none';
          }
        }
      }
    }

    set({
      selectedPrinter: mac,
      selectedPrinterInfo: info,
      currentDpi: activeDpi,
      canvasWidth: newW,
      canvasHeight: newH,
      isRotated: rot,
      canvasBorder: border
    });

    if (!mac) {
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 50 } });
      return;
    }

    try {
      const res = await fetch(`/api/printers/${mac}/profile`);
      const profile = await res.json();
      const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
      const caps = info?.capabilities || {};

      const normalizedEnergy = caps.density?.available
        ? clamp(
            (profile?.energy > 0 ? profile.energy : caps.density.default) || 3,
            caps.density.min || 1,
            caps.density.max || 8
          )
        : (caps.energy?.available
            ? clamp(
                (profile?.energy > 0 ? profile.energy : caps.energy.default) || 5000,
                caps.energy.min || 1,
                caps.energy.max || 65535
              )
            : 0);

      const normalizedSpeed = caps.speed?.available
        ? clamp(
            profile?.speed > 0 ? profile.speed : (caps.speed.default || 0),
            caps.speed.min || 0,
            caps.speed.max || 100
          )
        : 0;

      const normalizedFeed = caps.feed?.available
        ? Math.max(0, profile?.feed_lines ?? (caps.feed.default || 50))
        : 0;

      set({
        printerProfile: {
          ...profile,
          speed: normalizedSpeed,
          energy: normalizedEnergy,
          feed_lines: normalizedFeed
        }
      });
    } catch (e) {
      console.error("Failed to fetch printer profile", e);
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 50 } });
    }
  },
  
  setItems: (items) => set((state) => ({
    items: recalcAutoFit(items, state.batchRecords, state.canvasWidth, state.canvasHeight),
    selectedId: null,
    selectedIds: [],
    selectedPagesForPrint: []
  })),
  clearCanvas: () => set({ items: [], selectedId: null, selectedIds: [], currentPage: 0, selectedPagesForPrint: [], currentProjectId: null, designMode: 'canvas', htmlContent: '', history: [], historyIndex: -1, canUndo: false, canRedo: false }),
  
  addItem: (item) => set((state) => ({
    items: [
      ...state.items,
      item.pageIndex === undefined ? { ...item, pageIndex: state.currentPage } : item
    ]
  })),
  
  duplicateItem: (id, copies, gapMm) => set((state) => {
    const itemToClone = state.items.find(i => i.id === id);
    if (!itemToClone) return state;
    
    const newItems = [];
    const gapPx = Math.round(gapMm * 8);
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
    if (!currentItems.length) return state;

    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0))
    );
    const newItems = [...state.items];

    for (let i = 1; i <= totalCopies; i++) {
      const targetPage = maxPage + i;
      const clones = currentItems.map((item) => ({
        ...item,
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substring(2, 7),
        pageIndex: targetPage
      }));
      newItems.push(...clones);
    }

    return {
      items: newItems,
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
  
  setCanvasSize: (width, height) => set((state) => ({
    canvasWidth: width,
    canvasHeight: height,
    items: recalcAutoFit(state.items, state.batchRecords, width, height)
  })),
})));

import { create } from 'zustand';

export const useStore = create((set, get) => ({
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
  showAiConfig: false,
  stageRef: null,
  setShowAiConfig: (val) => set({ showAiConfig: val }),
  setStageRef: (ref) => {
    if (get().stageRef === ref) return;
    set({ stageRef: ref });
  },
  getStageB64: () => {
    const stage = get().stageRef;
    const zoomScale = get().zoomScale || 1;
    return stage
      ? stage.toDataURL({ pixelRatio: 1 / Math.max(zoomScale, 0.1) })
      : null;
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
  batchRecords: [{}],
  printCopies: 1,
  theme: 'auto',
  snapLines: [],
  fonts: [],
  labelPresets: [],
  currentDpi: 203,
  printerProfile: { speed: 0, energy: 0, feed_lines: 100 },
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
        canvasState: {
          width: state.canvasWidth,
          height: state.canvasHeight,
          isRotated: state.isRotated,
          canvasBorder: state.canvasBorder,
          canvasBorderThickness: state.canvasBorderThickness || 4,
          splitMode: state.splitMode,
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
          is_rotated: pendingPrintJob.canvasState.isRotated || false
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
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 100, default_font: 'Roboto.ttf', intended_media_type: 'unknown' },
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

  // --- HIERARCHICAL PROJECT MANAGEMENT ---
  projects: [],
  categories: [],
  currentProjectId: null,
  
  setCurrentProjectId: (id) => set({ currentProjectId: id }),

  setBatchRecords: (records) => set({
    batchRecords: Array.isArray(records) && records.length ? records : [{}]
  }),
  generateBatchMatrix: (matrixDef) => set(() => {
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

    return {
      batchRecords: records.length ? records : [{}]
    };
  }),
  generateBatchSequence: (seqDef) => set(() => {
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

    return {
      batchRecords: records.length ? records : [{}]
    };
  }),
  updateBatchRecord: (index, newRecord) => set((state) => {
    const newRecords = [...state.batchRecords];
    newRecords[index] = newRecord;
    return { batchRecords: newRecords };
  }),
  addBatchRecord: (record = {}) => set((state) => ({
    batchRecords: [...state.batchRecords, record]
  })),
  removeBatchRecord: (index) => set((state) => {
    const newRecords = state.batchRecords.filter((_, i) => i !== index);
    return { batchRecords: newRecords.length ? newRecords : [{}] };
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
    useStore.setState({
      canvasWidth: s.width || 384,
      canvasHeight: s.height || 384,
      canvasBorder: s.canvasBorder || 'none',
      canvasBorderThickness: s.canvasBorderThickness || 4,
      splitMode: s.splitMode || false,
      isRotated: s.isRotated || false,
      batchRecords: s.batchRecords || [{}],
      printCopies: s.printCopies || 1,
      currentPage: s.currentPage || 0,
      items: s.items || [],
      selectedId: null,
      selectedIds: [],
      selectedPagesForPrint: []
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

    return {
      canvasWidth: state.getMmToPx(widthMm),
      canvasHeight: state.getMmToPx(heightMm),
      isRotated,
      splitMode,
      canvasBorder: preset.border || 'none'
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

  setIsRotated: (val) => set((state) => {
    if (val !== state.isRotated) {
      return { isRotated: val, canvasWidth: state.canvasHeight, canvasHeight: state.canvasWidth };
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
      const isPreCutMedia = info.media_type === 'pre-cut' || info.vendor === 'niimbot';

      if (isNewPrinter) {
        if (isPreCutMedia) {
          const model = info.model_id ? info.model_id.toLowerCase() : '';

          if (model === 'd11' || model === 'd110' || model === 'd101') {
            newW = calcMmToPx(40);
            newH = calcMmToPx(12);
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
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 100 } });
      return;
    }

    try {
      const res = await fetch(`/api/printers/${mac}/profile`);
      const profile = await res.json();
      const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

      const normalizedEnergy = info?.vendor === 'niimbot'
        ? clamp(
            (profile?.energy ?? 0) > 0 ? profile.energy : (info?.default_energy ?? 3),
            1,
            info?.max_density ?? 5
          )
        : ((profile?.energy ?? 0) > 0
            ? clamp(
                profile.energy,
                info?.min_energy ?? 1,
                info?.max_energy ?? 65535
              )
            : 0);

      const normalizedSpeed = (profile?.speed ?? 0) > 0
        ? clamp(
            profile.speed,
            0,
            info?.max_speed ?? 100
          )
        : 0;

      set({
        printerProfile: {
          ...profile,
          speed: normalizedSpeed,
          energy: normalizedEnergy,
          feed_lines: Math.max(0, profile?.feed_lines ?? 100)
        }
      });
    } catch (e) {
      console.error("Failed to fetch printer profile", e);
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 100 } });
    }
  }, // <-- The syntax error is fixed right here
  
  setItems: (items) => set({ items, selectedId: null, selectedIds: [], selectedPagesForPrint: [] }),
  clearCanvas: () => set({ items: [], selectedId: null, selectedIds: [], currentPage: 0, selectedPagesForPrint: [], currentProjectId: null }),
  
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
    const pad = itemToClone.padding !== undefined ? Number(itemToClone.padding) : ((itemToClone.invert || itemToClone.bg_white) ? 4 : 0);
    const approxHeight = itemToClone.height || (itemToClone.type === 'text' ? (itemToClone.size * 1.15 * numLines) + (pad * 2) : 50);
    
    let currentY = itemToClone.y;
    
    for (let i = 1; i <= copies; i++) {
      currentY += approxHeight + gapPx;
      newItems.push({
        ...itemToClone,
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substr(2, 5),
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
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substr(2, 5),
        pageIndex: targetPage
      }));
      newItems.push(...clones);
    }

    return {
      items: newItems,
      selectedId: null
    };
  }),

  updateItem: (id, newAttrs) => set((state) => ({
    items: state.items.map((item) => item.id === id ? { ...item, ...newAttrs } : item)
  })),
  
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
      const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
      const numLines = item.text ? String(item.text).split('\n').length : 1;
      const approxHeight = item.height || (item.type === 'text' ? (item.size * 1.15 * numLines) + (pad * 2) : 50);
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
      const newId = Date.now().toString() + Math.random().toString(36).substr(2, 5);
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
  
  setCanvasSize: (width, height) => set({ canvasWidth: width, canvasHeight: height }),
}));

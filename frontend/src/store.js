import { create } from 'zustand';

export const useStore = create((set, get) => ({
  items: [],
  selectedId: null,
  canvasWidth: 384,
  canvasHeight: 384,
  canvasBorder: 'none',
  canvasBorderThickness: 4,
  splitMode: false,
  isRotated: false,
  selectedPrinter: null,
  selectedPrinterInfo: null,
  batchRecords: [{}],
  printCopies: 1,
  theme: 'auto',
  snapLines: [],
  fonts: [],
  labelPresets: [],
  currentDpi: 203,
  printerProfile: { speed: 0, energy: 0, feed_lines: 100 },
  currentPage: 0,
  setCurrentPage: (idx) => set({ currentPage: Math.max(0, Number(idx) || 0), selectedId: null }),
  addPage: () => set((state) => {
    const maxPage = Math.max(
      state.currentPage,
      ...state.items.map((item) => Number(item.pageIndex ?? 0))
    );
    return { currentPage: maxPage + 1, selectedId: null };
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
      selectedId: null
    };
  }),
  selectedPagesForPrint: [],
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
    if (!state.selectedPrinter) {
      alert("Please select a printer first!");
      return;
    }

    const normalizedPageIndices = Array.from(
      new Set((pageIndices || []).map((pageIndex) => Math.max(0, Number(pageIndex) || 0)))
    );
    if (normalizedPageIndices.length === 0) return;

    set({ isPrinting: true });

    try {
      const itemsToPrint = state.items.filter((item) =>
        normalizedPageIndices.includes(Number(item.pageIndex ?? 0))
      );
      const printRes = await fetch(`/api/print/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: state.selectedPrinter,
          canvas_state: {
            width: state.canvasWidth,
            height: state.canvasHeight,
            isRotated: state.isRotated,
            canvasBorder: state.canvasBorder,
            canvasBorderThickness: state.canvasBorderThickness || 4,
            splitMode: state.splitMode,
            items: itemsToPrint
          },
          copies: state.printCopies || 1,
          variables_list: state.batchRecords || [{}]
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
      set({ isPrinting: false });
    }
  },
  isSidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  addresses: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 100, default_font: 'Roboto.ttf' },
  
  getPxToMm: (px) => {
    const dpi = get().currentDpi || 203;
    return (Number(px || 0) / (dpi / 25.4)).toFixed(1);
  },
  getMmToPx: (mm) => {
    const dpi = get().currentDpi || 203;
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
  setPrintCopies: (n) => set({
    printCopies: Math.max(1, Number(n) || 1)
  }),

  fetchPresets: async () => {
    try {
      const res = await fetch('/api/presets');
      const data = await res.json();
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
      selectedPagesForPrint: []
    });
  },
  // --- END HIERARCHICAL PROJECT MANAGEMENT ---

  savePreset: async (name) => {
    const state = get();
    const widthMm = parseFloat(state.getPxToMm(state.canvasWidth));
    const heightMm = parseFloat(state.getPxToMm(state.canvasHeight));

    try {
      await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
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

  // NEW: Fetch initial settings from SQLite 
  fetchSettings: async () => {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      set({ settings: data });
    } catch (e) {
      console.error("Failed to fetch settings", e);
    }
  },

  fetchFonts: async () => {
    try {
      const res = await fetch('/api/fonts');
      const data = await res.json();
      set({ fonts: data });
      
      // Dynamically inject @font-face rules
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
    const state = get();
    let newW = state.canvasWidth;
    let newH = state.canvasHeight;
    let rot = state.isRotated;
    let border = state.canvasBorder;
    const activeDpi = info?.dpi || 203;
    const mmToPx = (mm) => Math.round(mm * (activeDpi / 25.4));

    if (info) {
      const model = info.model_id ? info.model_id.toLowerCase() : '';
      const isNewPrinter = !state.selectedPrinterInfo || state.selectedPrinterInfo.address !== mac;
      const isPreCutMedia = info.media_type === 'pre-cut' || info.vendor === 'niimbot';

      if (isNewPrinter) {
        if (isPreCutMedia) {
          if (model === 'd11' || model === 'd110' || model === 'd101') {
            newW = mmToPx(40);
            newH = mmToPx(12);
            rot = true;
            border = 'none';
          } else if (model === 'b1' || model === 'b21' || model === 'b18') {
            newW = mmToPx(50);
            newH = mmToPx(30);
            rot = true;
            border = 'none';
          } else {
            newW = info.width_px || mmToPx(48);
            newH = info.width_px || mmToPx(48);
            rot = false;
            border = 'none';
          }
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
            newW = mmToPx(40);
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
      set({
        printerProfile: {
          ...profile,
          speed: profile?.speed ?? 0,
          energy: profile?.energy ?? 0,
          feed_lines: profile?.feed_lines ?? 100
        }
      });
    } catch (e) {
      console.error("Failed to fetch printer profile", e);
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 100 } });
    }
  }),
  
  setItems: (items) => set({ items, selectedId: null, selectedPagesForPrint: [] }),
  clearCanvas: () => set({ items: [], selectedId: null, currentPage: 0, selectedPagesForPrint: [], currentProjectId: null }),
  
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
  
  selectItem: (id) => set({ selectedId: id }),
  
  deleteItem: (id) => set((state) => ({
    items: state.items.filter((item) => item.id !== id),
    selectedId: state.selectedId === id ? null : state.selectedId
  })),
  
  setCanvasSize: (width, height) => set({ canvasWidth: width, canvasHeight: height }),
}));

import { create } from 'zustand';

export const useStore = create((set) => ({
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

    return {
      items: newItems,
      currentPage: adjustedCurrentPage,
      selectedId: null
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
  isSidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  addresses: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 100, default_font: 'Roboto.ttf' },
  
  pxToMm: (px) => px / 8,
  mmToPx: (mm) => Math.round(mm * 8),

  projects: [],

  setBatchRecords: (records) => set({
    batchRecords: Array.isArray(records) && records.length ? records : [{}]
  }),
  setPrintCopies: (n) => set({
    printCopies: Math.max(1, Number(n) || 1)
  }),

  fetchProjects: async () => {
    try {
      const res = await fetch('/api/projects');
      const data = await res.json();
      set({ projects: data });
    } catch (e) {
      console.error("Failed to fetch projects", e);
    }
  },

  applyPreset: (preset) => set((state) => {
    const w = Math.round(preset.w * 8);
    const h = Math.round(preset.h * 8);
    return {
      canvasWidth: w,
      canvasHeight: h,
      isRotated: preset.rotated,
      splitMode: preset.splitMode || false,
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
  
  setSelectedPrinter: (mac, info) => set((state) => {
    let newW = state.canvasWidth;
    let newH = state.canvasHeight;
    let rot = state.isRotated;
    let border = state.canvasBorder;

    if (info) {
       const model = info.model_id ? info.model_id.toLowerCase() : '';
       const isNewPrinter = !state.selectedPrinterInfo || state.selectedPrinterInfo.address !== mac;
       
       if (isNewPrinter) {
           if (info.vendor === 'niimbot') {
               if (model === 'd11' || model === 'd110') {
                   newW = Math.round(40 * 8);
                   newH = Math.round(12 * 8);
                   rot = true;
                   border = 'none';
               } else if (model === 'b1' || model === 'b21' || model === 'b18') {
                   newW = Math.round(50 * 8);
                   newH = Math.round(30 * 8);
                   rot = true;
                   border = 'none';
               }
           } else {
               // Generic printer fallback
               const hardwareWidth = info.width_px || 384;
               
               // For standard Chinese cat printers (usually ~48mm/384px or 576px)
               if (hardwareWidth === 384) {
                   newW = 384;
                   newH = 384;
                   rot = false;
               } else if (hardwareWidth > 384) {
                   // Shipping label style
                   newW = hardwareWidth;
                   newH = Math.round(hardwareWidth * 1.5);
                   rot = false;
               } else {
                   // Narrow tape (like D11 clones)
                   newW = Math.round(40 * 8);
                   newH = hardwareWidth;
                   rot = true;
                   border = 'none';
               }
           }
       }
    }

    return { 
      selectedPrinter: mac, 
      selectedPrinterInfo: info,
      canvasWidth: newW,
      canvasHeight: newH,
      isRotated: rot,
      canvasBorder: border
    };
  }),
  
  setItems: (items) => set({ items, selectedId: null }),
  clearCanvas: () => set({ items: [], selectedId: null, currentPage: 0 }),
  
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

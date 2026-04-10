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
  theme: 'auto',
  snapLines: [],
  fonts: [],
  isSidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  addresses: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 100, default_font: 'Roboto.ttf' },
  
  pxToMm: (px) => px / 8,
  mmToPx: (mm) => Math.round(mm * 8),

  projects: [],

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

    // Smart Defaults for Niimbot
    if (info && info.vendor === 'niimbot') {
       if (!state.selectedPrinterInfo || state.selectedPrinterInfo.vendor !== 'niimbot') {
           if (info.model === 'd11' || info.model === 'd110') {
               newW = Math.round(40 * 8); // 40mm length
               newH = Math.round(12 * 8); // 12mm width
               rot = true;
           } else if (info.model === 'b1' || info.model === 'b21') {
               newW = Math.round(50 * 8); // 50mm length
               newH = Math.round(30 * 8); // 30mm width
               rot = true;
           }
       }
    } else {
       // Generic printer fallback
       const hardwareWidth = info ? info.width_px : 384;
       if (!state.selectedPrinterInfo || state.selectedPrinterInfo.width_px !== hardwareWidth) {
           if (rot) newH = hardwareWidth;
           else newW = hardwareWidth;
       }
    }

    return { 
      selectedPrinter: mac, 
      selectedPrinterInfo: info,
      canvasWidth: newW,
      canvasHeight: newH,
      isRotated: rot
    };
  }),
  
  setItems: (items) => set({ items }),
  clearCanvas: () => set({ items: [], selectedId: null }),
  
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  
  duplicateItem: (id, copies, gapMm) => set((state) => {
    const itemToClone = state.items.find(i => i.id === id);
    if (!itemToClone) return state;
    
    const newItems = [];
    const gapPx = Math.round(gapMm * 8);
    const numLines = itemToClone.text ? String(itemToClone.text).split('\n').length : 1;
    const pad = itemToClone.padding !== undefined ? Number(itemToClone.padding) : ((itemToClone.invert || itemToClone.bg_white) ? 4 : 0);
    const approxHeight = itemToClone.height || (itemToClone.type === 'text' ? (itemToClone.size * 1.2 * numLines) + (pad * 2) : 50);
    
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

  // Superb utility to clone the entire workspace multiple times downwards!
  multiplyWorkspace: (copies, gapMm, addCutLines) => set((state) => {
    const gapPx = Math.round(gapMm * 8);
    const feedAxis = state.isRotated ? 'x' : 'y';
    const singleLength = state.isRotated ? state.canvasWidth : state.canvasHeight;
    const step = singleLength + gapPx;
    
    const originalItems = [...state.items];
    let newItems = [...originalItems];
    
    for (let i = 1; i <= copies; i++) {
      const offset = i * step;
      
      const clones = originalItems.map(item => ({
        ...item,
        id: Date.now().toString() + '-' + i + '-' + Math.random().toString(36).substr(2, 5),
        [feedAxis]: item[feedAxis] + offset
      }));
      
      newItems = [...newItems, ...clones];
      
      if (addCutLines && gapPx > 0) {
         newItems.push({
           id: Date.now().toString() + '-cut-' + i,
           type: 'cut_line_indicator',
           x: state.isRotated ? offset - gapPx : 0,
           y: state.isRotated ? 0 : offset - gapPx,
           width: state.isRotated ? 1 : state.canvasWidth,
           height: state.isRotated ? state.canvasHeight : 1,
           isVertical: state.isRotated
         });
      }
    }
    
    return {
      items: newItems,
      canvasWidth: state.isRotated ? state.canvasWidth + (step * copies) : state.canvasWidth,
      canvasHeight: state.isRotated ? state.canvasHeight : state.canvasHeight + (step * copies)
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

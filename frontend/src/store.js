import { create } from 'zustand';

export const useStore = create((set) => ({
  items: [],
  selectedId: null,
  canvasWidth: 384,
  canvasHeight: 384,
  canvasBorder: 'none',
  isRotated: false,
  selectedPrinter: null,
  theme: 'auto',
  snapLines: [],
  fonts: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 100 },
  
  // NEW: Fetch initial settings from SQLite 
  fetchSettings: async () => {
    try {
      const res = await fetch('http://localhost:8000/api/settings');
      const data = await res.json();
      set({ settings: data });
    } catch (e) {
      console.error("Failed to fetch settings", e);
    }
  },

  fetchFonts: async () => {
    try {
      const res = await fetch('http://localhost:8000/api/fonts');
      const data = await res.json();
      set({ fonts: data });
      
      // Dynamically inject @font-face rules
      const style = document.createElement('style');
      let css = '';
      data.forEach(font => {
        const fontName = font.name.split('.')[0];
        css += `@font-face { font-family: '${fontName}'; src: url('http://localhost:8000/${font.file_path}'); }\n`;
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
  setTheme: (theme) => set({ theme }),
  setSnapLines: (lines) => set({ snapLines: lines }),
  setSettings: (settings) => set({ settings }),
  
  updateSettingsAPI: async (newSettings) => {
    set({ settings: newSettings });
    try {
      await fetch('http://localhost:8000/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings)
      });
    } catch (e) {
      console.error("Failed to save settings", e);
    }
  },
  
  setSelectedPrinter: (mac) => set({ selectedPrinter: mac }),
  
  setItems: (items) => set({ items }),
  clearCanvas: () => set({ items: [], selectedId: null }),
  
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  
  duplicateItem: (id, copies, gapMm) => set((state) => {
    const itemToClone = state.items.find(i => i.id === id);
    if (!itemToClone) return state;
    
    const newItems = [];
    const gapPx = Math.round(gapMm * 8);
    const numLines = itemToClone.text ? String(itemToClone.text).split('\n').length : 1;
    const approxHeight = itemToClone.height || (itemToClone.type === 'text' ? itemToClone.size * 1.2 * numLines : 50);
    
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

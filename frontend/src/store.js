import { create } from 'zustand';

export const useStore = create((set) => ({
  items: [],
  selectedId: null,
  canvasWidth: 384,
  canvasHeight: 384,
  selectedPrinter: null,
  
  setSelectedPrinter: (mac) => set({ selectedPrinter: mac }),
  
  setItems: (items) => set({ items }),
  clearCanvas: () => set({ items: [], selectedId: null }),
  
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  
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

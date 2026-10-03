export const createUiSlice = (set) => ({
  zoomScale: 1,
  showAiConfig: false,
  setShowAiConfig: (val) => set({ showAiConfig: val }),
  apiError: '',
  clearApiError: () => set({ apiError: '' }),
  setZoomScale: (scale) => set({ zoomScale: Math.max(0.1, Math.min(5, scale)) }),
  isSidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  isPropertiesOpen: true,
  toggleProperties: () => set((state) => ({ isPropertiesOpen: !state.isPropertiesOpen })),
  aiMessages: [{ role: 'assistant', content: 'Hi! I am the CatLabel AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }],
  aiInput: '',
  aiConvId: null,
  aiSessionUsage: { tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 },
  setAiInput: (input) => set({ aiInput: input }),
  setAiConvId: (id) => set({ aiConvId: id }),
  setAiMessages: (messagesOrUpdater) => set((state) => ({
    aiMessages: typeof messagesOrUpdater === 'function'
      ? messagesOrUpdater(state.aiMessages)
      : messagesOrUpdater
  })),
  setAiSessionUsage: (usageOrUpdater) => set((state) => ({
    aiSessionUsage: typeof usageOrUpdater === 'function'
      ? usageOrUpdater(state.aiSessionUsage)
      : usageOrUpdater
  })),
  aiMode: 'live',
  setAiMode: (val) => set({ aiMode: val }),
  aiExternalIntent: '',
  setAiExternalIntent: (val) => set({ aiExternalIntent: val }),
  aiExternalPrompt: '',
  setAiExternalPrompt: (val) => set({ aiExternalPrompt: val }),
  aiExternalResponse: '',
  setAiExternalResponse: (val) => set({ aiExternalResponse: val }),
  aiExternalError: '',
  setAiExternalError: (val) => set({ aiExternalError: val }),
  aiExternalNotice: '',
  setAiExternalNotice: (val) => set({ aiExternalNotice: val }),
  aiExternalResults: [],
  setAiExternalResults: (val) => set({ aiExternalResults: val }),
  resetAiChat: () => set({
    aiMessages: [{ role: 'assistant', content: 'Hi! I am the CatLabel AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }],
    aiInput: '',
    aiConvId: null,
    aiSessionUsage: { tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 },
    aiExternalIntent: '',
    aiExternalPrompt: '',
    aiExternalResponse: '',
    aiExternalError: '',
    aiExternalNotice: '',
    aiExternalResults: []
  })
});

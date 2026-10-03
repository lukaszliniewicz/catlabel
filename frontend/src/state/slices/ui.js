const readOnboardingComplete = () => {
  try { return typeof window !== 'undefined' && localStorage.getItem('catlabel_onboarding_completed_v1') === '1'; }
  catch { return false; }
};
const initiallyNarrow = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 1279px)').matches : false;

export const createUiSlice = (set) => ({
  onboardingComplete: readOnboardingComplete(),
  showOnboarding: false,
  setShowOnboarding: (value) => set({ showOnboarding: value }),
  completeOnboarding: () => {
    let apiError = '';
    try { localStorage.setItem('catlabel_onboarding_completed_v1', '1'); }
    catch { apiError = 'Setup is complete for this session. Browser storage is unavailable, so the welcome screen may return after restart.'; }
    set({ onboardingComplete: true, showOnboarding: false, ...(apiError ? { apiError } : {}) });
  },
  zoomScale: 1,
  showAiConfig: false,
  setShowAiConfig: (val) => set({ showAiConfig: val }),
  apiError: '',
  clearApiError: () => set({ apiError: '' }),
  setZoomScale: (scale) => set({ zoomScale: Math.max(0.1, Math.min(5, scale)) }),
  isNarrowLayout: initiallyNarrow,
  setLayoutViewport: (narrow) => set(state => state.isNarrowLayout === narrow ? state : {
    isNarrowLayout: narrow, isSidebarCollapsed: narrow, isPropertiesOpen: !narrow
  }),
  isSidebarCollapsed: initiallyNarrow,
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed,
    ...(state.isNarrowLayout && state.isSidebarCollapsed ? { isPropertiesOpen: false } : {}) })),
  isPropertiesOpen: !initiallyNarrow,
  toggleProperties: () => set((state) => ({ isPropertiesOpen: !state.isPropertiesOpen,
    ...(state.isNarrowLayout && !state.isPropertiesOpen ? { isSidebarCollapsed: true } : {}) })),
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

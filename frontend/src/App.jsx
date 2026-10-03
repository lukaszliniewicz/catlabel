import React, { lazy, Suspense, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Toolbar from './components/Toolbar';
import CanvasArea from './components/CanvasArea';
import PropertiesPanel from './components/PropertiesPanel';
import DocumentStatus from './components/DocumentStatus';
import HeadlessRenderer from './HeadlessRenderer';
import { useStore } from './store';

const OnboardingWizard = lazy(() => import('./components/OnboardingWizard'));
const AIConfigModal = lazy(() => import('./components/AIConfigModal'));
const LocalBatchRenderer = lazy(() => import('./components/LocalBatchRenderer'));

function App() {
  const theme = useStore((state) => state.theme);
  const fetchFonts = useStore((state) => state.fetchFonts);
  const settingsLoaded = useStore((state) => state.settingsLoaded);
  const onboardingComplete = useStore(state => state.onboardingComplete);
  const showOnboarding = useStore(state => state.showOnboarding);
  const showAiConfig = useStore((state) => state.showAiConfig);
  const setShowAiConfig = useStore((state) => state.setShowAiConfig);
  const isPreparingForPrint = useStore((state) => state.isPreparingForPrint);
  const onLocalRenderComplete = useStore((state) => state.onLocalRenderComplete);
  const apiError = useStore((state) => state.apiError);
  const clearApiError = useStore((state) => state.clearApiError);
  const isHeadless = new URLSearchParams(window.location.search).get('mode') === 'headless';

  useEffect(() => {
    if (!isHeadless) {
      fetchFonts();
      const state = useStore.getState();
      state.fetchProjects();
      state.fetchAddresses();
      state.fetchPresets();
      state.fetchSettings().then(() => state.restorePrinterChoice());
    }
  }, [fetchFonts, isHeadless]);

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');

    if (theme === 'auto') {
      const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      root.classList.add(systemTheme);
    } else {
      root.classList.add(theme);
    }
  }, [theme]);

  if (isHeadless) {
    return <HeadlessRenderer />;
  }

  return (
    <div className="flex h-screen w-full bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 overflow-hidden font-sans transition-colors duration-300">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 min-h-0 relative">
        <DocumentStatus />
        <Toolbar />
        <CanvasArea />
      </div>
      <PropertiesPanel />
      {apiError && (
        <div role="alert" className="fixed bottom-4 left-1/2 z-100 flex max-w-xl -translate-x-1/2 items-start gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 shadow-xl dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <span className="flex-1">{apiError}</span>
          <button type="button" onClick={clearApiError} className="font-bold" aria-label="Dismiss error">×</button>
        </div>
      )}
      <Suspense fallback={null}>
        {isPreparingForPrint && <LocalBatchRenderer onComplete={onLocalRenderComplete} />}
        {settingsLoaded && (!onboardingComplete || showOnboarding) && <OnboardingWizard />}
        {showAiConfig && <AIConfigModal onClose={() => setShowAiConfig(false)} />}
      </Suspense>
    </div>
  );
}

export default App;

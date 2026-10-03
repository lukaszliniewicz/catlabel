import React, { lazy, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Toolbar from './components/Toolbar';
import CanvasArea from './components/CanvasArea';
import PropertiesPanel from './components/PropertiesPanel';
import DocumentStatus from './components/DocumentStatus';
import ProjectSwitchDialog from './components/ProjectSwitchDialog';
import LazyFeature from './components/LazyFeature';
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
  const pendingPrintJob = useStore(state => state.pendingPrintJob);
  const onLocalRenderComplete = useStore((state) => state.onLocalRenderComplete);
  const apiError = useStore((state) => state.apiError);
  const clearApiError = useStore((state) => state.clearApiError);
  const pendingProjectLoad = useStore(state => state.pendingProjectLoad);
  const completeOnboarding = useStore(state => state.completeOnboarding);
  const isNarrowLayout = useStore(state => state.isNarrowLayout);
  const isSidebarCollapsed = useStore(state => state.isSidebarCollapsed);
  const isPropertiesOpen = useStore(state => state.isPropertiesOpen);
  const toggleSidebar = useStore(state => state.toggleSidebar);
  const toggleProperties = useStore(state => state.toggleProperties);
  const isHeadless = new URLSearchParams(window.location.search).get('mode') === 'headless';

  useEffect(() => {
    if (isHeadless) return;
    const media = window.matchMedia('(max-width: 1279px)');
    const update = () => useStore.getState().setLayoutViewport(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [isHeadless]);

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
    <main className="flex h-screen w-full bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 overflow-hidden font-sans transition-colors duration-300">
      {isNarrowLayout && <h1 className="sr-only">CatLabel Studio</h1>}
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 min-h-0 relative">
        {isNarrowLayout && <div className="flex shrink-0 justify-between gap-2 border-b border-neutral-300 px-2 py-1 dark:border-neutral-700">
          <button type="button" aria-expanded={!isSidebarCollapsed} onClick={toggleSidebar} className="min-h-10 rounded-sm border border-neutral-400 px-3 text-sm">Projects and printers</button>
          <button type="button" aria-expanded={isPropertiesOpen} onClick={toggleProperties} className="min-h-10 rounded-sm border border-neutral-400 px-3 text-sm">Properties</button>
        </div>}
        <DocumentStatus />
        <Toolbar />
        <CanvasArea />
      </div>
      <PropertiesPanel />
      {pendingProjectLoad && <ProjectSwitchDialog />}
      {apiError && (
        <div role="alert" className="fixed bottom-4 left-1/2 z-100 flex max-w-xl -translate-x-1/2 items-start gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 shadow-xl dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <span className="flex-1">{apiError}</span>
          <button type="button" onClick={clearApiError} className="font-bold" aria-label="Dismiss error">×</button>
        </div>
      )}
      {isPreparingForPrint && <LazyFeature label="print preparation" onClose={() => onLocalRenderComplete([], new Error('Print preparation cancelled before submission.'), pendingPrintJob?.id)} onError={error => onLocalRenderComplete([], error, pendingPrintJob?.id)}><LocalBatchRenderer onComplete={onLocalRenderComplete} /></LazyFeature>}
      {settingsLoaded && (!onboardingComplete || showOnboarding) && <LazyFeature label="welcome setup" onClose={completeOnboarding}><OnboardingWizard /></LazyFeature>}
      {showAiConfig && <LazyFeature label="AI settings" onClose={() => setShowAiConfig(false)}><AIConfigModal onClose={() => setShowAiConfig(false)} /></LazyFeature>}
    </main>
  );
}

export default App;

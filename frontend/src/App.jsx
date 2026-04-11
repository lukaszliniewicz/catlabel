import React, { useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Toolbar from './components/Toolbar';
import CanvasArea from './components/CanvasArea';
import PropertiesPanel from './components/PropertiesPanel';
import { useStore } from './store';

function App() {
  const theme = useStore((state) => state.theme);
  const fetchFonts = useStore((state) => state.fetchFonts);

  useEffect(() => {
    fetchFonts();

    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');

    if (theme === 'auto') {
      const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      root.classList.add(systemTheme);
    } else {
      root.classList.add(theme);
    }
  }, [theme, fetchFonts]);

  return (
    <div className="flex h-screen w-full bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 overflow-hidden font-sans transition-colors duration-300">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 min-h-0 relative">
        <Toolbar />
        <CanvasArea />
      </div>
      <PropertiesPanel />
    </div>
  );
}

export default App;

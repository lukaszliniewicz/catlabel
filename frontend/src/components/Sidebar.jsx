import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import ProjectTree from './ProjectTree';
import SavePresetModal from './SavePresetModal';
import PrinterDropdown from './PrinterDropdown';
import {
  ChevronDown, ChevronRight, LayoutTemplate,
  Menu, Printer, Wifi, Archive
} from 'lucide-react';

export default function Sidebar() {
  const {
    items,
    selectedPrinter,
    setSelectedPrinter,
    theme,
    setTheme,
    applyPreset,
    isSidebarCollapsed,
    toggleSidebar,
    printCopies,
    setPrintCopies,
    isPrinting,
    printPages,
    selectedPagesForPrint,
    labelPresets,
    manualPrinters,
    selectedPrinterInfo,
    designMode
  } = useStore();

  const [printers, setPrinters] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [showProjects, setShowProjects] = useState(true);
  const [showSavePresetModal, setShowSavePresetModal] = useState(false);

  const handleScan = async () => {
    setIsScanning(true);
    try {
      const res = await fetch('/api/printers/scan');
      const data = await res.json();
      setPrinters(data.devices || []);

      if (data.devices && data.devices.length > 0 && !useStore.getState().selectedPrinter) {
        await setSelectedPrinter(data.devices[0].address, data.devices[0]);
      }
    } catch (e) {
      console.error(e);
      alert('Failed to scan for printers. Is the backend running on port 8000?');
    }
    setIsScanning(false);
  };

  useEffect(() => {
    useStore.getState().fetchProjects();
    useStore.getState().fetchSettings();
    useStore.getState().fetchAddresses();
    useStore.getState().fetchPresets();

    handleScan();
  }, []);

  const maxPage = designMode === 'html'
    ? 0
    : items.reduce((max, item) => Math.max(max, Number(item.pageIndex ?? 0)), 0);
  const pageCount = maxPage + 1;

  const handlePrintCollapsed = () => {
    toggleSidebar();
  };

  const handlePrintSingle = () => {
    printPages([0]);
  };

  const handlePrintAll = () => {
    printPages(Array.from({ length: pageCount }, (_, i) => i));
  };

  const handlePrintSelected = () => {
    printPages(selectedPagesForPrint);
  };

  const SidebarButton = ({ icon: Icon, label, onClick, primary = false }) => (
    <button
      onClick={onClick}
      title={isSidebarCollapsed ? label : undefined}
      className={`w-full flex items-center ${isSidebarCollapsed ? 'justify-center' : 'justify-start'} gap-3 px-4 py-2.5 rounded-none transition-colors text-xs uppercase tracking-wider font-medium 
        ${primary
          ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 hover:bg-blue-100 dark:hover:bg-blue-900/40'
          : 'bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-50 dark:hover:bg-neutral-900'}`}
    >
      <Icon size={16} className="shrink-0" />
      {!isSidebarCollapsed && <span className="truncate">{label}</span>}
    </button>
  );

  return (
    <div className={`${isSidebarCollapsed ? 'w-20' : 'w-72'} bg-white dark:bg-neutral-950 border-r border-neutral-200 dark:border-neutral-800 p-4 flex flex-col gap-6 z-10 overflow-y-auto overflow-x-hidden transition-all duration-300 shrink-0`}>
      <div className={`flex items-center ${isSidebarCollapsed ? 'justify-center' : 'justify-between'} mb-2`}>
        {!isSidebarCollapsed && (
          <div className="flex items-center gap-3 min-w-0">
            <img
              src="/logo.webp"
              alt="CatLabel logo"
              className="w-9 h-9 object-contain shrink-0"
              draggable={false}
            />
            <h1 className="text-3xl font-serif tracking-tight text-neutral-900 dark:text-white">CatLabel.</h1>
          </div>
        )}
        <button onClick={toggleSidebar} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors flex-shrink-0">
          <Menu size={24} />
        </button>
      </div>

      {!isSidebarCollapsed && (
        <div className="flex gap-3 text-[10px] uppercase tracking-widest text-neutral-400 dark:text-neutral-500">
          <button onClick={() => setTheme('light')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'light' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Light</button>
          <button onClick={() => setTheme('dark')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'dark' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Dark</button>
          <button onClick={() => setTheme('auto')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'auto' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Auto</button>
        </div>
      )}

      {!isSidebarCollapsed ? (
        <div className="space-y-3">
          <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Printers</h2>

          <SidebarButton icon={Wifi} label={isScanning ? 'Scanning...' : 'Scan for Printers'} onClick={handleScan} />

          {(printers.length > 0 || manualPrinters.length > 0) && (
            <PrinterDropdown
              printers={printers}
              manualPrinters={manualPrinters}
              selectedPrinter={selectedPrinter}
              onSelect={(mac, info) => {
                setSelectedPrinter(mac, info);
              }}
            />
          )}

          {pageCount === 1 ? (
            <div className={`flex items-center w-full border ${isPrinting || !selectedPrinter ? 'opacity-50 cursor-not-allowed border-neutral-300 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-900 text-neutral-500' : 'border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'} rounded-none transition-colors`}>
              <div className={`flex items-center border-r ${isPrinting || !selectedPrinter ? 'border-neutral-300 dark:border-neutral-700' : 'border-blue-200 dark:border-blue-800'}`}>
                <button disabled={isPrinting || !selectedPrinter} onClick={() => setPrintCopies(Math.max(1, printCopies - 1))} className="px-3 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:pointer-events-none">-</button>
                <span className="text-xs font-bold w-6 text-center select-none">{printCopies}</span>
                <button disabled={isPrinting || !selectedPrinter} onClick={() => setPrintCopies(printCopies + 1)} className="px-3 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:pointer-events-none">+</button>
              </div>
              <button disabled={isPrinting || !selectedPrinter} onClick={handlePrintSingle} className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 text-xs uppercase tracking-wider font-bold transition-colors disabled:pointer-events-none">
                <Printer size={16} /> {isPrinting ? 'Printing...' : 'Print'}
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1 mb-1">
                <span className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest">Copies per Label</span>
                <div className={`flex items-center border rounded-sm overflow-hidden ${isPrinting || !selectedPrinter ? 'border-neutral-300 dark:border-neutral-700 opacity-50' : 'border-neutral-300 dark:border-neutral-700'}`}>
                  <button disabled={isPrinting || !selectedPrinter} onClick={() => setPrintCopies(Math.max(1, printCopies - 1))} className="px-2 py-1 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">-</button>
                  <span className="text-[10px] font-bold w-6 text-center select-none dark:text-white">{printCopies}</span>
                  <button disabled={isPrinting || !selectedPrinter} onClick={() => setPrintCopies(printCopies + 1)} className="px-2 py-1 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">+</button>
                </div>
              </div>
              <button disabled={isPrinting || !selectedPrinter} onClick={handlePrintAll} className={`flex items-center justify-center gap-2 w-full border px-4 py-2.5 text-xs uppercase tracking-wider font-bold transition-colors ${isPrinting || !selectedPrinter ? 'opacity-50 cursor-not-allowed border-neutral-300 bg-neutral-100 text-neutral-500 dark:border-neutral-700 dark:bg-neutral-900' : 'border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/40'}`}>
                <Printer size={16} /> Print All ({pageCount})
              </button>
              <button disabled={isPrinting || !selectedPrinter || selectedPagesForPrint.length === 0} onClick={handlePrintSelected} className={`flex items-center justify-center gap-2 w-full border px-4 py-2.5 text-xs uppercase tracking-wider font-bold transition-colors ${isPrinting || !selectedPrinter || selectedPagesForPrint.length === 0 ? 'opacity-50 cursor-not-allowed border-neutral-300 bg-transparent text-neutral-400 dark:border-neutral-800 dark:text-neutral-600' : 'border-blue-200 bg-transparent text-blue-600 hover:bg-blue-50 dark:border-blue-800 dark:text-blue-400 dark:hover:bg-blue-900/20'}`}>
                <Printer size={16} /> Print Selected ({selectedPagesForPrint.length})
              </button>
            </div>
          )}
        </div>
      ) : (
        <SidebarButton icon={Printer} label="Print Options" onClick={handlePrintCollapsed} primary />
      )}

      {!isSidebarCollapsed ? (
        <div className="space-y-3">
          <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Canvas Presets</h2>
          <select
            className="w-full bg-neutral-50 dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs text-neutral-900 dark:text-white focus:outline-none transition-colors mb-2"
            onChange={(e) => {
              if (e.target.value !== '') {
                const presetId = parseInt(e.target.value, 10);
                const preset = labelPresets.find((p) => p.id === presetId);
                if (preset) applyPreset(preset);
              }
              e.target.value = '';
            }}
            defaultValue=""
          >
            <option value="" disabled>Select physical layout...</option>

            {/* Continuous Media Presets */}
            <optgroup label="Continuous Roll Labels">
              {labelPresets.filter(p => p.media_type === 'continuous').map((p) => {
                const isConflict = selectedPrinterInfo?.media_type === 'pre-cut';
                return (
                  <option key={p.id} value={p.id} disabled={isConflict} title={p.description || ''}>
                    {isConflict ? '🚫 ' : ''}{p.name} ({p.width_mm}x{p.height_mm}mm)
                  </option>
                );
              })}
            </optgroup>

            {/* Pre-cut Media Presets */}
            <optgroup label="Pre-cut Labels (Niimbot)">
              {labelPresets.filter(p => p.media_type === 'pre-cut').map((p) => {
                const isConflict = selectedPrinterInfo?.media_type === 'continuous';
                return (
                  <option key={p.id} value={p.id} disabled={isConflict} title={p.description || ''}>
                    {isConflict ? '🚫 ' : ''}{p.name} ({p.width_mm}x{p.height_mm}mm)
                  </option>
                );
              })}
            </optgroup>

            {/* Any/Other Presets */}
            {labelPresets.filter(p => p.media_type !== 'continuous' && p.media_type !== 'pre-cut').length > 0 && (
              <optgroup label="Other / Universal">
                {labelPresets.filter(p => p.media_type !== 'continuous' && p.media_type !== 'pre-cut').map((p) => (
                  <option key={p.id} value={p.id} title={p.description || ''}>
                    {p.name} ({p.width_mm}x{p.height_mm}mm)
                  </option>
                ))}
              </optgroup>
            )}
          </select>

          <button
            onClick={() => setShowSavePresetModal(true)}
            className="w-full text-[10px] uppercase font-bold text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 py-1.5 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors"
          >
            Save Current as Preset
          </button>
        </div>
      ) : (
        <SidebarButton icon={LayoutTemplate} label="Presets (Expand to view)" onClick={toggleSidebar} />
      )}

      {isSidebarCollapsed ? (
        <SidebarButton icon={Archive} label="Saved Projects (Expand to view)" onClick={toggleSidebar} />
      ) : (
        <div className="space-y-3">
          <div
            className="flex items-center justify-between cursor-pointer border-b border-neutral-100 dark:border-neutral-800 pb-2 group"
            onClick={() => setShowProjects(!showProjects)}
          >
            <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest group-hover:text-neutral-900 dark:group-hover:text-white transition-colors">Saved Projects</h2>
            {showProjects ? (
              <ChevronDown size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
            ) : (
              <ChevronRight size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
            )}
          </div>

          {showProjects && (
            <ProjectTree />
          )}
        </div>
      )}

      {showSavePresetModal && (
        <SavePresetModal onClose={() => setShowSavePresetModal(false)} />
      )}
    </div>
  );
}

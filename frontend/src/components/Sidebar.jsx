import React, { useState, useEffect, useRef } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import ProjectTree from './ProjectTree';
import SavePresetModal from './SavePresetModal';
import PrinterDropdown from './PrinterDropdown';
import PresetPickerModal from './PresetPickerModal';
import EditorDrawer from './EditorDrawer';
import { getPageIndices } from '../utils/canvasPages';
import { apiJson } from '../utils/apiClient';
import { isPrinterScanResponse } from '../domain/printer';
import {
  ChevronDown, ChevronRight, LayoutTemplate,
  Menu, Printer, Wifi, Archive, Activity, Plug
} from 'lucide-react';

function SidebarButton({ icon: Icon, label, onClick, primary = false, collapsed, disabled = false }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={collapsed ? label : undefined}
      className={`w-full flex items-center ${collapsed ? 'justify-center' : 'justify-start'} gap-3 px-4 py-2.5 rounded-none transition-colors text-xs uppercase tracking-wider font-medium
        ${primary
          ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 hover:bg-blue-100 dark:hover:bg-blue-900/40'
          : 'bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-50 dark:hover:bg-neutral-900'}`}
    >
      <Icon size={16} className="shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </button>
  );
}

function scanPrinters(signal) {
  return apiJson('/api/printers/scan', { signal }, {
    validate: isPrinterScanResponse,
    validationMessage: 'Printer scan data is malformed.'
  });
}

function reportScanError(error) {
  console.error(error);
  useStore.setState({ apiError: error.message || 'Printer scan failed. Check Bluetooth access and try again, or choose an offline profile.' });
}

export default function Sidebar({ onOpenHarness, onOpenStatus, statusNeedsAttention = false }) {
  const {
    items,
    selectedPrinter,
    setSelectedPrinter,
    theme,
    setTheme,
    isSidebarCollapsed,
    toggleSidebar,
    printCopies,
    setPrintCopies,
    isPrinting,
    printPages,
    selectedPagesForPrint,
    manualPrinters,
    pageLayouts,
    currentPage
  } = useStore(useShallow((state) => ({
    items: state.items, selectedPrinter: state.selectedPrinter, setSelectedPrinter: state.setSelectedPrinter,
    theme: state.theme, setTheme: state.setTheme, isSidebarCollapsed: state.isSidebarCollapsed,
    toggleSidebar: state.toggleSidebar, printCopies: state.printCopies, setPrintCopies: state.setPrintCopies,
    isPrinting: state.isPrinting, printPages: state.printPages, selectedPagesForPrint: state.selectedPagesForPrint,
    manualPrinters: state.manualPrinters, pageLayouts: state.pageLayouts, currentPage: state.currentPage
  })));

  const [printers, setPrinters] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const scanController = useRef(null);
  const selectedPrinterInfo = useStore(state => state.selectedPrinterInfo);
  const isPreparing = useStore(state => state.isPreparingForPrint);
  const printBusy = isPreparing || isPrinting;
  const isNarrowLayout = useStore(state => state.isNarrowLayout);
  const setShowOnboarding = useStore(state => state.setShowOnboarding);
  const [showProjects, setShowProjects] = useState(true);
  const [showSavePresetModal, setShowSavePresetModal] = useState(false);
  const [showPresetPicker, setShowPresetPicker] = useState(false);
  const activePreset = useStore((state) => state.getActivePreset());

  const handleScan = async () => {
    scanController.current?.abort();
    const controller = new AbortController();
    scanController.current = controller;
    setIsScanning(true);
    try {
      const data = await scanPrinters(controller.signal);
      if (!controller.signal.aborted) setPrinters(data.devices);
    } catch (error) {
      if (!controller.signal.aborted) reportScanError(error);
    } finally {
      if (!controller.signal.aborted) setIsScanning(false);
    }
  };

  useEffect(() => () => scanController.current?.abort(), []);

  const pageIndices = getPageIndices({ items, pageLayouts, currentPage });
  const pageCount = pageIndices.length;

  const handlePrintCollapsed = () => {
    toggleSidebar();
  };

  const handlePrintSingle = () => {
    printPages([pageIndices[0]]);
  };

  const handlePrintAll = () => {
    printPages(pageIndices);
  };

  const handlePrintSelected = () => {
    printPages(selectedPagesForPrint);
  };



  const content = (
    <div className={`${isSidebarCollapsed ? 'w-20' : 'w-72'} max-w-full h-full bg-white dark:bg-neutral-950 border-r border-neutral-200 dark:border-neutral-800 p-4 flex flex-col gap-6 z-10 overflow-y-auto overflow-x-hidden transition-all duration-300 shrink-0`}>
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
        <button type="button" onClick={toggleSidebar} aria-label={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors shrink-0">
          <Menu size={24} />
        </button>
      </div>

      {!isSidebarCollapsed && (
        <div className="flex gap-3 text-[10px] uppercase tracking-widest text-neutral-600 dark:text-neutral-300">
          <button onClick={() => setTheme('light')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'light' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Light</button>
          <button onClick={() => setTheme('dark')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'dark' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Dark</button>
          <button onClick={() => setTheme('auto')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'auto' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Auto</button>
        </div>
      )}

      <SidebarButton collapsed={isSidebarCollapsed} icon={Activity} label={statusNeedsAttention ? 'Status — needs attention' : 'Status'} onClick={onOpenStatus} />

      <SidebarButton collapsed={isSidebarCollapsed} icon={Plug} label="Connect AI harness" onClick={onOpenHarness} />

      {!isSidebarCollapsed ? (
        <div className="space-y-3">
          <h2 className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Printers</h2>

          <SidebarButton collapsed={isSidebarCollapsed} icon={Wifi} disabled={isScanning} label={isScanning ? 'Scanning...' : 'Scan for Printers'} onClick={handleScan} />

          <SidebarButton collapsed={false} icon={Printer} label="Printer setup" onClick={() => setShowOnboarding(true)} />

          {(printers.length > 0 || manualPrinters.length > 0 || selectedPrinterInfo) && (
            <PrinterDropdown
              printers={printers}
              manualPrinters={manualPrinters}
              selectedPrinter={selectedPrinter}
              selectedPrinterInfo={selectedPrinterInfo}
              onSelect={(mac, info) => {
                setSelectedPrinter(mac, info);
              }}
            />
          )}

          <p className="text-xs leading-relaxed text-neutral-600 dark:text-neutral-300">
            {selectedPrinterInfo?.transport === 'offline'
              ? 'Offline profile: design and export now. Scan and select the physical printer when ready to print.'
              : selectedPrinter ? 'Discovered device: connects when printing. Check the loaded paper before submitting.'
              : 'You can design without a printer. Scan or choose an offline profile when ready.'}
          </p>

          {pageCount === 1 ? (
            <div className={`flex items-center w-full border ${printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' ? 'opacity-50 cursor-not-allowed border-neutral-300 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-900 text-neutral-500' : 'border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'} rounded-none transition-colors`}>
              <div className={`flex items-center border-r ${printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' ? 'border-neutral-300 dark:border-neutral-700' : 'border-blue-200 dark:border-blue-800'}`}>
                <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={() => setPrintCopies(Math.max(1, printCopies - 1))} className="px-3 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:pointer-events-none">-</button>
                <span className="text-xs font-bold w-6 text-center select-none">{printCopies}</span>
                <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={() => setPrintCopies(printCopies + 1)} className="px-3 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:pointer-events-none">+</button>
              </div>
              <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={handlePrintSingle} className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 hover:bg-black/5 dark:hover:bg-white/5 text-xs uppercase tracking-wider font-bold transition-colors disabled:pointer-events-none">
                <Printer size={16} /> {isPreparing ? 'Preparing…' : isPrinting ? 'Printing…' : 'Print'}
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1 mb-1">
                <span className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest">Copies per Label</span>
                <div className={`flex items-center border rounded-xs overflow-hidden ${printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' ? 'border-neutral-300 dark:border-neutral-700 opacity-50' : 'border-neutral-300 dark:border-neutral-700'}`}>
                  <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={() => setPrintCopies(Math.max(1, printCopies - 1))} className="px-2 py-1 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">-</button>
                  <span className="text-[10px] font-bold w-6 text-center select-none dark:text-white">{printCopies}</span>
                  <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={() => setPrintCopies(printCopies + 1)} className="px-2 py-1 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">+</button>
                </div>
              </div>
              <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline'} onClick={handlePrintAll} className={`flex items-center justify-center gap-2 w-full border px-4 py-2.5 text-xs uppercase tracking-wider font-bold transition-colors ${printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' ? 'opacity-50 cursor-not-allowed border-neutral-300 bg-neutral-100 text-neutral-500 dark:border-neutral-700 dark:bg-neutral-900' : 'border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/40'}`}>
                <Printer size={16} /> {isPreparing ? 'Preparing…' : isPrinting ? 'Printing…' : `Print All (${pageCount})`}
              </button>
              <button disabled={printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' || selectedPagesForPrint.length === 0} onClick={handlePrintSelected} className={`flex items-center justify-center gap-2 w-full border px-4 py-2.5 text-xs uppercase tracking-wider font-bold transition-colors ${printBusy || !selectedPrinter || selectedPrinterInfo?.transport === 'offline' || selectedPagesForPrint.length === 0 ? 'opacity-50 cursor-not-allowed border-neutral-300 bg-transparent text-neutral-400 dark:border-neutral-800 dark:text-neutral-600' : 'border-blue-200 bg-transparent text-blue-600 hover:bg-blue-50 dark:border-blue-800 dark:text-blue-400 dark:hover:bg-blue-900/20'}`}>
                <Printer size={16} /> {isPreparing ? 'Preparing…' : isPrinting ? 'Printing…' : `Print Selected (${selectedPagesForPrint.length})`}
              </button>
            </div>
          )}
        </div>
      ) : (
        <SidebarButton collapsed={isSidebarCollapsed} icon={Printer} label="Print Options" onClick={handlePrintCollapsed} primary />
      )}

      {!isSidebarCollapsed ? (
        <div className="space-y-3">
          <h2 className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Canvas Presets</h2>
          <button
            onClick={() => setShowPresetPicker(true)}
            className="w-full flex items-center justify-between bg-neutral-50 dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs text-neutral-900 dark:text-white hover:border-blue-500 transition-colors mb-2"
          >
            <span className="truncate pr-2">
              {activePreset ? `${activePreset.name} (${activePreset.width_mm}x${activePreset.height_mm}mm)` : 'Custom Size (Unsaved)'}
            </span>
            <ChevronDown size={14} className="text-neutral-500 shrink-0" />
          </button>

          <button
            onClick={() => setShowSavePresetModal(true)}
            className="w-full text-[10px] uppercase font-bold text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 py-1.5 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors"
          >
            Save Current as Preset
          </button>
        </div>
      ) : (
        <SidebarButton collapsed={isSidebarCollapsed} icon={LayoutTemplate} label="Presets (Expand to view)" onClick={toggleSidebar} />
      )}

      {isSidebarCollapsed ? (
        <SidebarButton collapsed={isSidebarCollapsed} icon={Archive} label="Saved Projects (Expand to view)" onClick={toggleSidebar} />
      ) : (
        <div className="space-y-3">
          <button
            type="button"
            aria-expanded={showProjects}
            className="flex w-full items-center justify-between cursor-pointer border-b border-neutral-100 dark:border-neutral-800 pb-2 group"
            onClick={() => setShowProjects(!showProjects)}
          >
            <h2 className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest group-hover:text-neutral-900 dark:group-hover:text-white transition-colors">Saved Projects</h2>
            {showProjects ? (
              <ChevronDown size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
            ) : (
              <ChevronRight size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
            )}
          </button>

          {showProjects && (
            <ProjectTree />
          )}
        </div>
      )}

      {showSavePresetModal && (
        <SavePresetModal onClose={() => setShowSavePresetModal(false)} />
      )}
      {showPresetPicker && (
        <PresetPickerModal onClose={() => setShowPresetPicker(false)} />
      )}
    </div>
  );
  if (!isNarrowLayout) return content;
  return isSidebarCollapsed ? null : <EditorDrawer label="Projects and printers" side="left" width={288} onClose={toggleSidebar}>{content}</EditorDrawer>;
}

import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import {
  AlignCenter, MoveHorizontal, Maximize2, Sliders, Printer, Database, Sparkles,
  Plus, Bold, Italic, Underline
} from 'lucide-react';
import { calculateAutoFitItem } from '../utils/rendering';
import { TEMPLATE_METADATA } from './templateStyles';
import { apiFetch } from '../utils/apiClient';
import BatchDataPanel from './BatchDataPanel';

const AIAssistant = React.lazy(() => import('./AIAssistant'));
const IconPicker = React.lazy(() => import('./IconPicker'));

const MmScrubberInput = ({ name, value, onChange, label, disabled }) => {
  const getPxToMm = useStore((state) => state.getPxToMm);
  const getMmToPx = useStore((state) => state.getMmToPx);
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [startVal, setStartVal] = useState(0);

  const currentMm = parseFloat(getPxToMm(value));

  const handleMouseDown = (e) => {
    if (disabled) return;
    setIsDragging(true);
    setStartX(e.clientX);
    setStartVal(currentMm);
  };

  useEffect(() => {
    if (!isDragging) return;
    const handleMouseMove = (e) => {
      const dx = e.clientX - startX;
      const newMm = Math.max(0, startVal + dx * 0.5);
      onChange({ target: { name, value: getMmToPx(newMm), type: 'number' } });
    };
    const handleMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [getMmToPx, isDragging, name, onChange, startVal, startX]);

  const handleChange = (e) => {
    const mm = parseFloat(e.target.value);
    if (!isNaN(mm)) {
      onChange({ target: { name, value: getMmToPx(mm), type: 'number' } });
    }
  };

  return (
    <div className="flex-1">
      <label 
        className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 truncate transition-colors ${disabled ? 'text-neutral-300 dark:text-neutral-700' : 'text-neutral-400 dark:text-neutral-500 cursor-ew-resize hover:text-blue-500'}`} 
        onMouseDown={handleMouseDown}
        title={disabled ? "Locked" : "Drag left/right to adjust"}
      >
        {label} (mm) {disabled ? '🔒' : '⇹'}
      </label>
      <input 
        type="number" step="0.1" name={name} value={currentMm.toFixed(1)} onChange={handleChange} disabled={disabled}
        className={`w-full bg-transparent border rounded-none p-2 text-sm focus:outline-hidden transition-colors ${disabled ? 'border-neutral-200 dark:border-neutral-800 text-neutral-400 dark:text-neutral-600' : 'border-neutral-300 dark:border-neutral-700 text-neutral-900 dark:text-white focus:border-blue-500'}`}
      />
    </div>
  );
};

const ScrubberInput = ({ name, value, onChange, label, step = 0.5, dragMultiplier = 0.5 }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [startVal, setStartVal] = useState(value);

  const handleMouseDown = (e) => {
    setIsDragging(true);
    setStartX(e.clientX);
    setStartVal(Number(value));
  };

  useEffect(() => {
    if (!isDragging) return;
    const handleMouseMove = (e) => {
      const dx = e.clientX - startX;
      const factor = 1 / step;
      const newVal = Math.max(0, Math.round((startVal + dx * dragMultiplier) * factor) / factor);
      onChange({ target: { name, value: newVal, type: 'number' } });
    };
    const handleMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, startX, startVal, onChange, name, step, dragMultiplier]);

  return (
    <div className="flex-1">
      <label 
        className="block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5 truncate cursor-ew-resize hover:text-blue-500 transition-colors" 
        onMouseDown={handleMouseDown}
        title="Drag left/right to adjust"
      >
        {label} ⇹
      </label>
      <input 
        type="number" step={step} name={name} value={value} onChange={onChange} 
        className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-hidden focus:border-blue-500 transition-colors"
      />
    </div>
  );
};

const ToggleBtn = ({ icon: Icon, active, onClick, label }) => (
  <button
    onClick={onClick}
    title={label}
    className={`flex-1 flex justify-center items-center py-1.5 transition-colors rounded-xs ${
      active
        ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white shadow-inner'
        : 'bg-transparent text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800'
    }`}
  >
    <Icon size={16} />
  </button>
);

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, canvasBorder, setCanvasBorder, canvasBorderThickness, setCanvasBorderThickness, setCanvasGeometry, getMmToPx, getPxToMm, settings, updateSettingsAPI, fonts, uploadFont, isRotated, setIsRotated, splitMode, setSplitMode, printerProfile, selectedPrinter, selectedPrinterInfo, batchRecords, pageLayouts, currentPage, setHtmlContent, updateTemplateParams, ejectTemplate, isPropertiesOpen, toggleProperties } = useStore(useShallow((state) => ({
    items: state.items, selectedId: state.selectedId, updateItem: state.updateItem, deleteItem: state.deleteItem,
    canvasWidth: state.canvasWidth, canvasHeight: state.canvasHeight, canvasBorder: state.canvasBorder,
    setCanvasBorder: state.setCanvasBorder, canvasBorderThickness: state.canvasBorderThickness,
    setCanvasBorderThickness: state.setCanvasBorderThickness, setCanvasGeometry: state.setCanvasGeometry,
    getMmToPx: state.getMmToPx, getPxToMm: state.getPxToMm, settings: state.settings,
    updateSettingsAPI: state.updateSettingsAPI, fonts: state.fonts, uploadFont: state.uploadFont,
    isRotated: state.isRotated, setIsRotated: state.setIsRotated, splitMode: state.splitMode,
    setSplitMode: state.setSplitMode, printerProfile: state.printerProfile, selectedPrinter: state.selectedPrinter,
    selectedPrinterInfo: state.selectedPrinterInfo, batchRecords: state.batchRecords,
    pageLayouts: state.pageLayouts, currentPage: state.currentPage, setHtmlContent: state.setHtmlContent,
    updateTemplateParams: state.updateTemplateParams, ejectTemplate: state.ejectTemplate,
    isPropertiesOpen: state.isPropertiesOpen, toggleProperties: state.toggleProperties
  })));
  const selectedItem = items.find(i => i.id === selectedId);
  const isPreCut = selectedPrinterInfo?.media_type === 'pre-cut';
  const pInfo = selectedPrinterInfo || {};
  const caps = pInfo.capabilities || {};
  const supportedPaperModes = Array.isArray(pInfo.supported_paper_modes) ? pInfo.supported_paper_modes : [];
  const maxSpeed = caps.speed?.max || 100;
  const minEnergy = caps.energy?.min || 1000;
  const maxEnergy = caps.energy?.max || 65535;
  const minDensity = caps.density?.min ?? 1;
  const maxDensity = caps.density?.max ?? 5;
  const allowsAutomaticDensity = Boolean(caps.density?.allow_auto);
  const usesRawDensity = caps.density?.scale === 'raw';
  const recommendedMinDensity = caps.density?.recommended_min;
  const recommendedMaxDensity = caps.density?.recommended_max;

  const [panelWidth, setPanelWidth] = useState(360);

  // Tab State
  const [activeTab, setActiveTab] = useState('canvas');
  const [showIconPicker, setShowIconPicker] = useState(false);
  const [templateIconField, setTemplateIconField] = useState(null);
  
  const currentLayout = pageLayouts.find(l => l.pageIndex === currentPage) || { htmlContent: '', activeTemplate: null };
  const activeTemplate = currentLayout.activeTemplate;
  const htmlContent = currentLayout.htmlContent;

  const [previousSelection, setPreviousSelection] = useState(selectedId);
  if (previousSelection !== selectedId) {
    setPreviousSelection(selectedId);
    if (selectedItem) setActiveTab('element');
  }

  // A new settings snapshot invalidates the draft without an effect-driven render.
  const [settingsDraft, setSettingsDraft] = useState({ source: settings, value: settings });
  const localSettings = settingsDraft.source === settings ? settingsDraft.value : settings;
  const setLocalSettings = (value) => setSettingsDraft({ source: settings, value });
  const [isSaving, setIsSaving] = useState(false);

  const [dupCopies, setDupCopies] = useState(1);
  const [dupGap, setDupGap] = useState(10);
  const [multCopies, setMultCopies] = useState(1);
  

  useEffect(() => {
    if (isPreCut && splitMode) {
      setSplitMode(false);
    }
  }, [isPreCut, splitMode, setSplitMode]);

  const handleResizeMouseDown = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = panelWidth;
    const onMouseMove = (moveEvent) => {
      const deltaX = startX - moveEvent.clientX; // Moving left makes it wider
      setPanelWidth(Math.max(250, Math.min(600, startWidth + deltaX)));
    };
    const onMouseUp = () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-hidden focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5 truncate";

  // --- Actions ---

  const handleCenterAbsolute = () => {
    if (!selectedItem) return;
    const itemW = selectedItem.width || 0;
    
    let itemH = selectedItem.height || 0;
    if (!itemH && selectedItem.type === 'text') {
      const pad = selectedItem.padding !== undefined ? Number(selectedItem.padding) : ((selectedItem.invert || selectedItem.bg_white) ? 4 : 0);
      const numLines = selectedItem.text ? String(selectedItem.text).split('\n').length : 1;
      const actualLineHeight = selectedItem.lineHeight ?? (numLines > 1 ? 1.15 : 1);
      itemH = (selectedItem.size * actualLineHeight * numLines) + (pad * 2);
    }
    
    updateItem(selectedId, { 
      x: (canvasWidth - itemW) / 2, 
      y: (canvasHeight - itemH) / 2 
    });
  };

  const handleMakeFullWidth = () => {
    if (!selectedItem) return;
    if (selectedItem.type === 'group') {
      useStore.getState().fitGroupToWidth();
      return;
    }
    
    let newHeight = selectedItem.height;
    
    if (selectedItem.type === 'qrcode') {
      newHeight = canvasWidth;
    } else if (selectedItem.type === 'image' && selectedItem.width && selectedItem.height) {
      const ratio = selectedItem.width / selectedItem.height;
      newHeight = Math.round(canvasWidth / ratio);
    }
    
    updateItem(selectedId, {
      x: 0,
      width: canvasWidth,
      height: newHeight,
      align: 'center'
    });
  };

  const handleFitToWidth = () => {
    if (!selectedItem || !selectedItem.text) return;

    const optimized = calculateAutoFitItem(
      { ...selectedItem, fit_to_width: true },
      batchRecords,
      canvasWidth,
      canvasHeight
    );

    updateItem(selectedId, {
      size: optimized.size,
      fit_to_width: true
    });
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    let parsedValue = type === 'checkbox' ? checked : (type === 'number' ? Number(value) : value);
    
    if (selectedItem.type === 'image' && (name === 'width' || name === 'height')) {
      const ratio = selectedItem.width / selectedItem.height;
      if (name === 'width') {
        updateItem(selectedId, { width: parsedValue, height: Math.round(parsedValue / ratio) });
      } else {
        updateItem(selectedId, { height: parsedValue, width: Math.round(parsedValue * ratio) });
      }
      return;
    }
    updateItem(selectedId, { [name]: parsedValue });
  };

  const handleFormatHtml = async (target) => {
    const beautify = (await import('js-beautify')).default;
    if (target === 'designMode') {
      const formatted = beautify.html(htmlContent, { indent_size: 2 });
      setHtmlContent(formatted);
    } else if (target === 'item') {
      const contentToFormat = selectedItem.html || '';
      const formatted = beautify.html(contentToFormat, { indent_size: 2 });
      if (selectedItem.type === 'html') updateItem(selectedId, { html: formatted });
    }
  };

  const handleProfileChange = (e) => {
    const { name, value } = e.target;
    if (name === 'paper_mode') {
      useStore.setState((state) => ({
        printerProfile: {
          ...state.printerProfile,
          paper_mode: value || null
        }
      }));
      return;
    }

    const rawValue = Number(value);

    let nextValue = Number.isFinite(rawValue) ? rawValue : 0;

    if (name === 'speed') {
      nextValue = Math.max(0, Math.min(nextValue, maxSpeed));
    } else if (name === 'energy') {
      nextValue = caps.density?.available
        ? Math.max(allowsAutomaticDensity ? 0 : minDensity, Math.min(nextValue, maxDensity))
        : Math.max(0, Math.min(nextValue, maxEnergy));
    } else if (name === 'feed_lines') {
      nextValue = Math.max(0, nextValue);
    }

    useStore.setState((state) => ({
      printerProfile: {
        ...state.printerProfile,
        [name]: nextValue
      }
    }));
  };

  const handleSaveProfile = async () => {
    if (!selectedPrinter) return;
    setIsSaving(true);
    try {
      await apiFetch(`/api/printers/${selectedPrinter}/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(useStore.getState().printerProfile)
      });
    } catch (e) {
      console.error("Failed to save printer profile", e);
      useStore.setState({ apiError: e.message || 'Failed to save the printer profile.' });
    }
    setTimeout(() => setIsSaving(false), 1500);
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    await updateSettingsAPI(localSettings);
    setTimeout(() => setIsSaving(false), 1500);
  };

  if (!isPropertiesOpen) return null;

  return (
    <div
      className="fixed inset-y-0 right-0 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 flex flex-col z-30 overflow-hidden transition-colors duration-300 shrink-0 shadow-2xl xl:relative xl:inset-auto xl:z-10 xl:shadow-none"
      style={{ width: panelWidth, maxWidth: '100vw' }}
    >
      <div
        role="separator"
        aria-label="Resize properties panel"
        aria-orientation="vertical"
        aria-valuemin={280}
        aria-valuemax={600}
        aria-valuenow={panelWidth}
        tabIndex={0}
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-blue-500 z-50 transition-colors"
        onMouseDown={handleResizeMouseDown}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') setPanelWidth((width) => Math.min(600, width + 10));
          if (event.key === 'ArrowRight') setPanelWidth((width) => Math.max(280, width - 10));
        }}
      />

      <button type="button" onClick={toggleProperties} aria-label="Close properties panel" className="absolute right-2 top-2 z-50 rounded-sm p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-900 dark:hover:bg-neutral-800 dark:hover:text-white xl:hidden">×</button>
      
      {/* TABS */}
      <div className="flex border-b border-neutral-200 dark:border-neutral-800" role="tablist" aria-label="Properties sections">
        <button
          type="button" role="tab" aria-selected={activeTab === 'element'} aria-label="Element and layout"
          onClick={() => setActiveTab('element')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'element' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Sliders size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded-sm opacity-0 group-hover:opacity-100 group-focus:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Element / Layout</span>
        </button>
        
        <button
          type="button" role="tab" aria-selected={activeTab === 'canvas'} aria-label="Canvas and printer"
          onClick={() => setActiveTab('canvas')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'canvas' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Printer size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded-sm opacity-0 group-hover:opacity-100 group-focus:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Canvas & Printer</span>
        </button>

        <button
          type="button" role="tab" aria-selected={activeTab === 'data'} aria-label="Batch data"
          onClick={() => setActiveTab('data')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'data' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Database size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded-sm opacity-0 group-hover:opacity-100 group-focus:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Batch Data</span>
        </button>

        <button
          type="button" role="tab" aria-selected={activeTab === 'assistant'} aria-label="AI assistant"
          onClick={() => setActiveTab('assistant')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'assistant' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Sparkles size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded-sm opacity-0 group-hover:opacity-100 group-focus:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">AI Assistant</span>
        </button>
      </div>

      <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
        
        {/* === CANVAS & PRINTER TAB === */}
        {activeTab === 'canvas' && (
          <>
            <div className="space-y-4">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Dimensions</h2>
              
              <label className={`flex items-center gap-2 text-[10px] uppercase font-bold mt-2 cursor-pointer border px-3 py-2 rounded w-full transition-colors ${
                isPreCut
                  ? 'text-neutral-400 border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 opacity-60 cursor-not-allowed'
                  : 'text-red-600 dark:text-red-400 border-red-200 dark:border-red-900/30 bg-red-50 dark:bg-red-950/20 hover:bg-red-100 dark:hover:bg-red-900/40'
              }`}>
                <input
                  type="checkbox"
                  checked={splitMode || false}
                  onChange={(e) => !isPreCut && setSplitMode(e.target.checked)}
                  disabled={isPreCut}
                />
                Oversize / Split Print Mode {isPreCut && '(Disabled for Pre-cut Media)'}
              </label>
              
              {splitMode && !isPreCut && (
                <div className="flex gap-2 mt-2">
                  <button onClick={() => setCanvasGeometry(getMmToPx(105), getMmToPx(148), false)} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A6</button>
                  <button onClick={() => setCanvasGeometry(getMmToPx(148), getMmToPx(210), false)} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A5</button>
                </div>
              )}

              <div className="flex gap-4 items-center">
                <label className="flex items-center gap-2 text-xs font-bold text-neutral-600 dark:text-neutral-400 mt-2 cursor-pointer border px-3 py-2 border-neutral-200 dark:border-neutral-800 rounded-sm hover:bg-neutral-50 dark:hover:bg-neutral-900 w-full">
                  <input type="checkbox" checked={isRotated} onChange={(e) => setIsRotated(e.target.checked)} />
                  Rotate Feed (Landscape View)
                </label>
              </div>
              <div className="flex gap-4">
                <MmScrubberInput 
                  name="width" 
                  label={isRotated ? "Paper Length" : "Print Width"} 
                  value={canvasWidth} 
                  onChange={(e) => setCanvasGeometry(Number(e.target.value), canvasHeight, isRotated)}
                  disabled={!isRotated}
                />
                <MmScrubberInput 
                  name="height" 
                  label={isRotated ? "Print Width" : "Paper Length"} 
                  value={canvasHeight} 
                  onChange={(e) => setCanvasGeometry(canvasWidth, Number(e.target.value), isRotated)}
                  disabled={isRotated}
                />
              </div>
            </div>
            
            <div className="space-y-4 mt-4">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Canvas Styling</h2>
              <div className="flex gap-4">
                <div className="flex flex-col justify-end flex-1">
                  <label className={labelClass} title="Canvas Border / Cut line">Canvas Border</label>
                  <select value={canvasBorder} onChange={(e) => setCanvasBorder(e.target.value)} className={inputClass}>
                    <option value="none">None</option>
                    <option value="box">Full Box</option>
                    <option value="top">Top Border</option>
                    <option value="bottom">Bottom Border</option>
                    <option value="cut_line">Cut Line (Dashed Bottom)</option>
                  </select>
                </div>
                <ScrubberInput 
                  name="canvasBorderThickness" 
                  label="Thickness" 
                  value={canvasBorderThickness || 4} 
                  onChange={(e) => setCanvasBorderThickness(Number(e.target.value))} 
                />
              </div>
            </div>


            <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Duplicate Label</h2>
              <p className="text-[10px] text-neutral-500">Easily create identical copies of this label as new pages.</p>
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-[10px] text-neutral-400 font-bold uppercase mb-1">Copies to Add</label>
                  <input type="number" min="1" value={multCopies} onChange={e => setMultCopies(parseInt(e.target.value) || 1)} className={inputClass} />
                </div>
              </div>
              <button onClick={() => useStore.getState().multiplyWorkspace(multCopies)} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
                Duplicate Page
              </button>
            </div>

            <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Printer Config</h2>

              <div className="text-xs text-blue-600 dark:text-blue-400 mb-2">
                {selectedPrinter
                  ? `Hardware Defaults: Speed ${caps.speed?.default ?? 'Auto'}, ${caps.density?.available ? 'Density' : 'Energy'} ${caps.density?.available ? (caps.density.default || 'Auto') : (caps.energy?.default || 'Auto')}`
                  : 'Select a printer to configure device-specific overrides.'}
              </div>

              <div>
                <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer border px-3 py-2 border-neutral-200 dark:border-neutral-800 rounded-sm hover:bg-neutral-50 dark:hover:bg-neutral-900 w-full mb-4">
                  <input type="checkbox" checked={useStore.getState().dither} onChange={(e) => useStore.getState().setDither(e.target.checked)} />
                  Enable Dithering (Best for Photos)
                </label>
              </div>

              {pInfo.media_type === 'continuous' && pInfo.protocol_family?.includes('p12') && (
                <div className="mb-4 p-3 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-sm">
                  <label className={labelClass}>Adjust Tape Length</label>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => setCanvasGeometry(Math.max(getMmToPx(5), canvasWidth - getMmToPx(5)), canvasHeight, isRotated)}
                      className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded-sm text-lg font-bold dark:text-white"
                    >
                      -
                    </button>
                    <span className="flex-1 text-center text-xs font-bold dark:text-neutral-300">
                      {parseFloat(getPxToMm(canvasWidth)).toFixed(0)} mm
                    </span>
                    <button
                      onClick={() => setCanvasGeometry(canvasWidth + getMmToPx(5), canvasHeight, isRotated)}
                      className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded-sm text-lg font-bold dark:text-white"
                    >
                      +
                    </button>
                  </div>
                </div>
              )}

              {caps.density?.available && (
                <div>
                  <label className={labelClass}>
                    {usesRawDensity ? 'Print Density Override' : 'Print Darkness'} ({minDensity} - {maxDensity})
                  </label>
                  {usesRawDensity ? (
                    <input
                      type="number"
                      name="energy"
                      min={allowsAutomaticDensity ? 0 : minDensity}
                      max={maxDensity}
                      step={1}
                      value={printerProfile?.energy ?? (allowsAutomaticDensity ? 0 : caps.density.default ?? minDensity)}
                      onChange={handleProfileChange}
                      disabled={!selectedPrinter}
                      className={inputClass}
                    />
                  ) : (
                    <select
                      name="energy"
                      value={printerProfile?.energy ?? caps.density.default ?? 3}
                      onChange={handleProfileChange}
                      disabled={!selectedPrinter}
                      className={inputClass}
                    >
                      {Array.from({ length: Math.max(0, maxDensity - minDensity + 1) }, (_, i) => minDensity + i).map((level) => (
                        <option key={level} value={level}>
                          {level} - {level <= 2 ? 'Light' : level >= (maxDensity - 1) ? 'Dark' : 'Normal'}
                        </option>
                      ))}
                    </select>
                  )}
                  {usesRawDensity && (
                    <p className="text-[9px] text-neutral-400 mt-1">
                      {allowsAutomaticDensity ? `0 = Auto${caps.density.default != null ? ` (${caps.density.default})` : ''}. ` : ''}
                      Protocol range: {minDensity} - {maxDensity}.
                      {recommendedMinDensity != null && recommendedMaxDensity != null
                        ? ` Model-tuned range: ${recommendedMinDensity} - ${recommendedMaxDensity}.`
                        : ' This model has no published tuned range.'}
                      {' '}Thermal protection may reduce the effective density while the print head is hot.
                    </p>
                  )}
                </div>
              )}

              {caps.speed?.available && (
                <div>
                  <label className={labelClass}>Speed Override (0 = Auto)</label>
                  <input
                    type="number"
                    name="speed"
                    min={0}
                    max={maxSpeed}
                    value={printerProfile?.speed || 0}
                    onChange={handleProfileChange}
                    disabled={!selectedPrinter}
                    className={inputClass}
                  />
                  <p className="text-[9px] text-neutral-400 mt-1">
                    {pInfo.model ? `Hardware Default: ${caps.speed.default || 0}. Max: ${maxSpeed}.` : 'Select a printer to view limits.'}
                  </p>
                </div>
              )}

              {caps.energy?.available && (
                <div>
                  <label className={labelClass}>Energy Override (0 = Auto)</label>
                  <input
                    type="number"
                    name="energy"
                    min={0}
                    max={maxEnergy}
                    step={caps.energy.step || 500}
                    value={printerProfile?.energy || 0}
                    onChange={handleProfileChange}
                    disabled={!selectedPrinter}
                    className={inputClass}
                  />
                  <p className="text-[9px] text-neutral-400 mt-1">
                    {pInfo.model ? `Safe Range: ${minEnergy} - ${maxEnergy}. Default: ${caps.energy.default || 5000}.` : 'Select a printer to view limits.'}
                  </p>
                </div>
              )}

              {caps.feed?.available && (
                <div>
                  <label className={labelClass}>Feed Lines (Tear Padding)</label>
                  <input
                    type="number"
                    name="feed_lines"
                    min={0}
                    value={printerProfile?.feed_lines ?? (caps.feed.default || 50)}
                    onChange={handleProfileChange}
                    disabled={!selectedPrinter}
                    className={inputClass}
                  />
                </div>
              )}

              {supportedPaperModes.length > 0 && (
                <div>
                  <label className={labelClass}>Paper Mode</label>
                  <select
                    name="paper_mode"
                    value={printerProfile?.paper_mode || supportedPaperModes[0]?.value || ''}
                    onChange={handleProfileChange}
                    disabled={!selectedPrinter}
                    className={inputClass}
                  >
                    {supportedPaperModes.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label || mode.value}
                      </option>
                    ))}
                  </select>
                  <p className="text-[9px] text-neutral-400 mt-1">
                    Controls media alignment for printers whose firmware supports labels, marks, folders, or tattoo paper.
                  </p>
                </div>
              )}

              <button
                onClick={handleSaveProfile}
                disabled={isSaving || !selectedPrinter}
                className={`w-full mt-4 py-3 rounded-none transition-colors text-xs uppercase tracking-widest font-bold border
                  ${isSaving
                    ? 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800'
                    : 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 border-transparent hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed'}`}
              >
                {isSaving ? 'Settings Saved ✓' : 'Save Printer Settings'}
              </button>
            </div>

            <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Global Defaults</h2>
              <div className="pt-2">
                <label className={labelClass}>AI Media Assumption</label>
                <select name="intended_media_type" value={localSettings.intended_media_type || 'unknown'} onChange={(e) => setLocalSettings({ ...localSettings, intended_media_type: e.target.value })} className={inputClass}>
                  <option value="unknown">Not Set (AI will ask)</option>
                  <option value="continuous">Continuous Roll (Generic)</option>
                  <option value="pre-cut">Pre-cut Labels (Niimbot)</option>
                  <option value="both">Both / Mixed</option>
                </select>
                <p className="text-[9px] text-neutral-400 mt-1 mb-2">Guides the AI Assistant if no printer is connected.</p>
              </div>
              <div className="pt-2">
                <label className={labelClass}>Global Default Font</label>
                <div className="flex gap-2">
                  <select name="default_font" value={localSettings.default_font || 'RobotoCondensed.ttf'} onChange={(e) => setLocalSettings({ ...localSettings, default_font: e.target.value })} className={inputClass}>
                    <option value="arial.ttf">System Arial</option>
                    {fonts.map(f => (
                      <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                    ))}
                  </select>
                  <label className="flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 cursor-pointer hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" title="Upload Custom Font">
                    <Plus size={16} className="text-neutral-500 dark:text-neutral-400" />
                    <input type="file" accept=".ttf,.otf" className="hidden" onClick={(e) => e.target.value = null} onChange={(e) => { if(e.target.files[0]) uploadFont(e.target.files[0]); }} />
                  </label>
                </div>
                <p className="text-[9px] text-neutral-400 mt-1">Applies to all newly created text items.</p>
              </div>
              <button 
                onClick={handleSaveSettings} 
                className="w-full py-3 rounded-none transition-colors text-xs uppercase tracking-widest font-bold border bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white border-neutral-200 dark:border-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-800"
              >
                Save Global Defaults
              </button>
            </div>
          </>
        )}

        {/* === ELEMENT TAB === */}
        {activeTab === 'element' && (
          <>
            {!selectedItem ? (
              <div className="space-y-4 h-full flex flex-col">
                {activeTemplate ? (
                  <>
                    <div className="flex items-center justify-between pb-2 border-b border-neutral-100 dark:border-neutral-800">
                      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white">Template Settings</h2>
                      <button onClick={ejectTemplate} className="text-[10px] text-amber-600 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400 px-2 py-1 rounded-sm font-bold uppercase hover:bg-amber-100 transition-colors">
                        Eject to Custom HTML
                      </button>
                    </div>

                    <div className="space-y-3 overflow-y-auto pr-2 pb-2">
                      {(() => {
                        const meta = TEMPLATE_METADATA.find((t) => t.id === activeTemplate.id) || TEMPLATE_METADATA[0];
                        return meta.fields.map((field) => {
                          const value = activeTemplate.params[field.name] ?? field.default ?? '';
                          const handleParamChange = (val) => updateTemplateParams({ [field.name]: val });

                          if (field.type === 'icon') {
                            return (
                              <div key={field.name}>
                                <label className={labelClass}>{field.label}</label>
                                <div className="flex items-center gap-3 mb-3">
                                  {value ? (
                                    <img
                                      src={value}
                                      alt={field.label}
                                      className="w-10 h-10 object-contain bg-white border border-neutral-300 dark:border-neutral-700 p-1 rounded-sm"
                                    />
                                  ) : (
                                    <div className="w-10 h-10 bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded-sm flex items-center justify-center text-[10px] text-neutral-400">
                                      None
                                    </div>
                                  )}
                                  <button
                                    onClick={() => setTemplateIconField(field.name)}
                                    className="px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 text-xs font-bold uppercase tracking-wider hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors dark:text-white rounded-sm"
                                  >
                                    Choose Icon
                                  </button>
                                </div>
                              </div>
                            );
                          }

                          if (field.type === 'textarea') {
                            return (
                              <div key={field.name}>
                                <label className={labelClass}>{field.label}</label>
                                <textarea
                                  value={value}
                                  onChange={(e) => handleParamChange(e.target.value)}
                                  className={inputClass}
                                  rows={3}
                                />
                              </div>
                            );
                          }

                          if (field.type === 'select') {
                            return (
                              <div key={field.name}>
                                <label className={labelClass}>{field.label}</label>
                                <select
                                  value={value}
                                  onChange={(e) => handleParamChange(e.target.value)}
                                  className={inputClass}
                                >
                                  {(field.options || []).map((option) => (
                                    <option key={option.value || option} value={option.value || option}>
                                      {option.label || option}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            );
                          }

                          return (
                            <div key={field.name}>
                              <label className={labelClass}>{field.label}</label>
                              <input
                                type="text"
                                value={value}
                                onChange={(e) => handleParamChange(e.target.value)}
                                className={inputClass}
                              />
                            </div>
                          );
                        });
                      })()}
                    </div>

                    <div className="mt-auto pt-4 border-t border-neutral-100 dark:border-neutral-800">
                      <label className={labelClass}>Generated HTML (Read-Only)</label>
                      <textarea value={htmlContent} readOnly className={`${inputClass} opacity-70 bg-neutral-100 dark:bg-neutral-900 cursor-not-allowed`} rows={6} />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex items-center justify-between pb-2 border-b border-neutral-100 dark:border-neutral-800">
                      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white">Background Layout (HTML)</h2>
                      <button onClick={() => handleFormatHtml('designMode')} className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded-sm font-bold uppercase hover:bg-blue-100 transition-colors">
                        Auto-Format
                      </button>
                    </div>
                    <p className="text-[10px] text-neutral-500">
                      Wrap text in <code>&lt;div class=&quot;auto-text&quot;&gt;</code> to automatically scale it to fit the container.
                    </p>
                    <textarea
                      value={htmlContent}
                      onChange={(e) => setHtmlContent(e.target.value)}
                      className="w-full flex-1 bg-neutral-50 dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-3 text-sm font-mono dark:text-white focus:outline-hidden focus:border-blue-500"
                      placeholder="<div class='auto-text'>Hello World</div>"
                    />
                  </>
                )}
              </div>
            ) : selectedItem && (
              <>
            <div className="space-y-4">
              <div>
                <div className="grid grid-cols-3 gap-2">
                  <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                  <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
                  <ScrubberInput name="rotation" label="Rot(°)" value={Math.round(selectedItem.rotation || 0)} onChange={handleChange} />
                </div>
                
                <div className="flex gap-2 mt-3">
                  <button onClick={handleCenterAbsolute} title="Center Absolutely" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <AlignCenter size={16} />
                  </button>
                  <button onClick={handleMakeFullWidth} title="Full Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <MoveHorizontal size={16} />
                  </button>
                  {selectedItem.type === 'text' && (
                    <button onClick={handleFitToWidth} title="Maximize Font to Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                      <Maximize2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {selectedItem.type === 'text' && (
                <>
                  <div>
                    <label className={labelClass}>Text Content</label>
                    <textarea name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} rows={3} />
                  </div>

                  <div className="flex gap-2 mt-2 border border-neutral-200 dark:border-neutral-800 rounded-sm p-1 bg-neutral-50 dark:bg-neutral-900/50">
                    <ToggleBtn icon={Bold} label="Bold" active={selectedItem.weight >= 700} onClick={() => updateItem(selectedId, { weight: selectedItem.weight >= 700 ? 400 : 700 })} />
                    <ToggleBtn icon={Italic} label="Italic" active={selectedItem.italic} onClick={() => updateItem(selectedId, { italic: !selectedItem.italic })} />
                    <ToggleBtn icon={Underline} label="Underline" active={selectedItem.underline} onClick={() => updateItem(selectedId, { underline: !selectedItem.underline })} />
                  </div>

                  <div className="mt-3">
                    <label className={labelClass}>Font Family</label>
                    <div className="flex gap-2">
                      <select name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                      <label className="flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 cursor-pointer hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" title="Upload Custom Font">
                        <Plus size={16} className="text-neutral-500 dark:text-neutral-400" />
                        <input type="file" accept=".ttf,.otf" className="hidden" onClick={(e) => e.target.value = null} onChange={(e) => { if(e.target.files[0]) uploadFont(e.target.files[0]); }} />
                      </label>
                    </div>
                  </div>

                  <div className="flex gap-2 mt-3">
                    <ScrubberInput name="size" label="Font Size" value={selectedItem.size} onChange={handleChange} />
                    <ScrubberInput 
                      name="lineHeight" 
                      label="Line Height" 
                      step={0.05} 
                      dragMultiplier={0.01} 
                      value={selectedItem.lineHeight ?? (String(selectedItem.text || '').includes('\n') ? 1.15 : 1)} 
                      onChange={handleChange} 
                    />
                    <ScrubberInput name="padding" label="Padding" value={selectedItem.padding !== undefined ? selectedItem.padding : 0} onChange={handleChange} />
                  </div>

                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass}>Text Color</label>
                      <select name="color" value={selectedItem.color || (selectedItem.invert ? 'white' : 'black')} onChange={handleChange} className={inputClass}>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass}>Background</label>
                      <select name="bgColor" value={selectedItem.bgColor || (selectedItem.invert ? 'black' : (selectedItem.bg_white ? 'white' : 'transparent'))} onChange={handleChange} className={inputClass}>
                        <option value="transparent">Transparent</option>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                  </div>

                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="width" label="Box Width" value={selectedItem.width || 0} onChange={handleChange} />
                  </div>

                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass}>Horizontal</label>
                      <select name="align" value={selectedItem.align || 'center'} onChange={handleChange} className={inputClass}>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass}>Vertical</label>
                      <select name="verticalAlign" value={selectedItem.verticalAlign || 'middle'} onChange={handleChange} className={inputClass}>
                        <option value="top">Top</option>
                        <option value="middle">Middle</option>
                        <option value="bottom">Bottom</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="no_wrap" checked={selectedItem.no_wrap || false} onChange={handleChange} /> Single Line
                    </label>
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="fit_to_width" checked={selectedItem.fit_to_width || false} onChange={handleChange} /> Auto-Fit to Box
                    </label>
                    {selectedItem.fit_to_width && (
                      <label className="col-span-2 flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-500 cursor-pointer bg-neutral-50 dark:bg-neutral-900 p-2 border border-neutral-200 dark:border-neutral-800 mt-1">
                        <input type="checkbox" checked={selectedItem.batch_scale_mode === 'individual'} onChange={(e) => updateItem(selectedId, { batch_scale_mode: e.target.checked ? 'individual' : 'uniform' })} />
                        Scale Individually (Varies per record)
                      </label>
                    )}
                  </div>
                </>
              )}


              {selectedItem.type === 'group' && (
                <>
                  <div className="flex gap-4">
                    <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                    <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
                  </div>
                  <div className="mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
                    <button onClick={() => useStore.getState().fitGroupToWidth()} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
                      Scale Group to Canvas Width
                    </button>
                  </div>
                </>
              )}

              {selectedItem.type === 'icon_text' && (
                <>
                  <div className="mb-4">
                    <button onClick={() => setShowIconPicker(true)} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
                      Change Icon
                    </button>
                  </div>
                  <div className="flex gap-2 mb-2 bg-neutral-50 dark:bg-neutral-900 p-1 border border-neutral-200 dark:border-neutral-800">
                    <button onClick={() => updateItem(selectedId, { fit_to_width: true })} className="flex-1 text-[10px] uppercase font-bold text-blue-600 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors">
                      Auto-Fit to Box
                    </button>
                  </div>
                  <div>
                    <label className={labelClass}>Group Text</label>
                    <input type="text" name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <ScrubberInput name="size" label="Text Size" value={Number(selectedItem.size || 0)} onChange={handleChange} />
                    <ScrubberInput name="weight" label="Weight (100-900)" value={selectedItem.weight || 700} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="icon_size" label="Icon Size" value={Number(selectedItem.icon_size || 0)} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2 pt-2 border-t border-neutral-100 dark:border-neutral-800">
                    <MmScrubberInput name="icon_x" label="Icon X" value={Math.round(selectedItem.icon_x)} onChange={handleChange} />
                    <MmScrubberInput name="icon_y" label="Icon Y" value={Math.round(selectedItem.icon_y)} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="text_x" label="Text X" value={Math.round(selectedItem.text_x)} onChange={handleChange} />
                    <MmScrubberInput name="text_y" label="Text Y" value={Math.round(selectedItem.text_y)} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem.type === 'html' && (
                <>
                  <div>
                    <label className={labelClass}>Font Family</label>
                    <div className="flex gap-2">
                      <select name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                      <label className="flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 cursor-pointer hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" title="Upload Custom Font">
                        <Plus size={16} className="text-neutral-500 dark:text-neutral-400" />
                        <input type="file" accept=".ttf,.otf" className="hidden" onClick={(e) => e.target.value = null} onChange={(e) => { if(e.target.files[0]) uploadFont(e.target.files[0]); }} />
                      </label>
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className={labelClass.replace('mb-1.5', 'mb-0')}>HTML Content</label>
                      <button onClick={() => handleFormatHtml('item')} className="text-[9px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-sm font-bold uppercase hover:bg-blue-100 transition-colors">Format</button>
                    </div>
                    <textarea name="html" value={selectedItem.html || ''} onChange={handleChange} className={inputClass} rows={8} />
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Frame Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Frame Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}


              {selectedItem.type === 'image' && (
                <div className="flex gap-4">
                  <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                  <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                </div>
              )}

              {selectedItem.type === 'shape' && (
                <>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass}>Fill</label>
                      <select name="fill" value={selectedItem.fill} onChange={handleChange} className={inputClass}>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                        <option value="transparent">Transparent</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass}>Stroke</label>
                      <select name="stroke" value={selectedItem.stroke} onChange={handleChange} className={inputClass}>
                        <option value="transparent">Transparent</option>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                    <ScrubberInput name="strokeWidth" label="Thickness" value={selectedItem.strokeWidth || 0} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem.type === 'qrcode' && (
                <>
                  <div>
                    <label className={labelClass}>QR Data (Supports {'{{ var }}'})</label>
                    <textarea name="data" value={selectedItem.data} onChange={handleChange} className={inputClass} rows={3} />
                  </div>
                  <div className="flex gap-4">
                    {/* Scrubbing one axis updates both to maintain the square aspect ratio */}
                    <MmScrubberInput name="width" label="Size" value={selectedItem.width} onChange={(e) => {
                      handleChange({ target: { name: 'width', value: e.target.value, type: 'number' } });
                      handleChange({ target: { name: 'height', value: e.target.value, type: 'number' } });
                    }} />
                  </div>
                </>
              )}

              {selectedItem.type === 'barcode' && (
                <>
                  <div>
                    <label className={labelClass}>Barcode Data</label>
                    <input type="text" name="data" value={selectedItem.data} onChange={handleChange} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Type</label>
                    <select name="barcode_type" value={selectedItem.barcode_type} onChange={handleChange} className={inputClass}>
                      <option value="code128">Code 128</option>
                      <option value="code39">Code 39</option>
                      <option value="ean13">EAN-13</option>
                    </select>
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem && (
                <div className="mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
                  <label className={labelClass}>Duplicate Element Only</label>
                  <div className="flex gap-4 mb-2">
                    <div className="flex-1">
                      <label className="block text-[10px] text-neutral-400 mb-1">Copies</label>
                      <input type="number" min="1" value={dupCopies} onChange={e => setDupCopies(parseInt(e.target.value)||1)} className={inputClass} />
                    </div>
                    <div className="flex-1">
                      <label className="block text-[10px] text-neutral-400 mb-1">Gap (mm)</label>
                      <input type="number" min="0" value={dupGap} onChange={e => setDupGap(parseInt(e.target.value)||0)} className={inputClass} />
                    </div>
                  </div>
                  <button onClick={() => useStore.getState().duplicateItem(selectedId, dupCopies, dupGap)} className="w-full bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200 text-[10px] uppercase tracking-widest font-bold">
                    Clone Item Down
                  </button>
                </div>
              )}
              <div className="mt-2 mb-2 flex gap-4">
                  <div className="flex-1">
                    <label className={labelClass}>Styling Lines</label>
                    <select name="border_style" value={selectedItem.border_style || 'none'} onChange={handleChange} className={inputClass}>
                      <option value="none">None</option>
                      <option value="box">Box (Full)</option>
                      <option value="top">Top Border</option>
                      <option value="bottom">Bottom Border</option>
                      <option value="cut_line">Cut Line (Dashed)</option>
                    </select>
                  </div>
                  <ScrubberInput name="border_thickness" label="Thickness" value={selectedItem.border_thickness || 4} onChange={handleChange} />
              </div>
            </div>

            <div className="mt-auto pt-6">
              <button 
                onClick={() => deleteItem(selectedId)} 
                className="w-full bg-transparent text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/50 px-4 py-2 rounded-none hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors text-xs uppercase tracking-widest font-medium"
              >
                Delete Item
              </button>
            </div>
              </>
            )}
          </>
        )}

        {/* === DATA TAB === */}
        {activeTab === 'data' && <BatchDataPanel />}

        {/* === ASSISTANT TAB === */}
        {activeTab === 'assistant' && (
          <React.Suspense fallback={<div className="p-4 text-sm text-neutral-500">Loading assistant…</div>}>
            <AIAssistant />
          </React.Suspense>
        )}
      </div>

      <React.Suspense fallback={null}>
        {showIconPicker && (
          <IconPicker
            onClose={() => setShowIconPicker(false)}
            onSelect={(b64) => {
              updateItem(selectedId, { icon_src: b64 });
              setShowIconPicker(false);
            }}
          />
        )}
        {templateIconField && activeTemplate && (
          <IconPicker
            onClose={() => setTemplateIconField(null)}
            onSelect={(b64) => {
              updateTemplateParams({ [templateIconField]: b64 });
              setTemplateIconField(null);
            }}
          />
        )}
      </React.Suspense>
    </div>
  );
}

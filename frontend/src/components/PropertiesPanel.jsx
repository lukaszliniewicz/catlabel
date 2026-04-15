import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import {
  AlignCenter, MoveHorizontal, Maximize2, Sliders, Printer, Database, Sparkles,
  Plus, Trash2, FileSpreadsheet, Bold, Italic, Underline
} from 'lucide-react';
import AIAssistant from './AIAssistant';
import BatchPrintModal from './BatchPrintModal';
import IconPicker from './IconPicker';
import { calculateAutoFitItem } from '../utils/rendering';

const pxToMm = (px) => (px / 8).toFixed(1);
const mmToPx = (mm) => Math.round(mm * 8);

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
        className={`w-full bg-transparent border rounded-none p-2 text-sm focus:outline-none transition-colors ${disabled ? 'border-neutral-200 dark:border-neutral-800 text-neutral-400 dark:text-neutral-600' : 'border-neutral-300 dark:border-neutral-700 text-neutral-900 dark:text-white focus:border-blue-500'}`} 
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
        className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors" 
      />
    </div>
  );
};

const ToggleBtn = ({ icon: Icon, active, onClick, label }) => (
  <button
    onClick={onClick}
    title={label}
    className={`flex-1 flex justify-center items-center py-1.5 transition-colors rounded-sm ${
      active
        ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white shadow-inner'
        : 'bg-transparent text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800'
    }`}
  >
    <Icon size={16} />
  </button>
);

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, canvasBorder, setCanvasBorder, canvasBorderThickness, setCanvasBorderThickness, setCanvasSize, getMmToPx, getPxToMm, settings, updateSettingsAPI, fonts, isRotated, setIsRotated, splitMode, setSplitMode, printerProfile, selectedPrinter, selectedPrinterInfo, batchRecords, setBatchRecords, updateBatchRecord, addBatchRecord, removeBatchRecord, generateBatchMatrix, generateBatchSequence, designMode, setDesignMode, htmlContent, setHtmlContent } = useStore();
  const selectedItem = items.find(i => i.id === selectedId);
  const isPreCut = selectedPrinterInfo?.media_type === 'pre-cut';
  const pInfo = selectedPrinterInfo || {};
  const maxSpeed = pInfo.max_speed || 100;
  const defaultSpeed = pInfo.default_speed || 0;
  const minEnergy = pInfo.min_energy || 1000;
  const maxEnergy = pInfo.max_energy || 65535;
  const defaultEnergy = pInfo.default_energy || 5000;
  const maxDensity = selectedPrinterInfo?.max_density || 5;

  const [panelWidth, setPanelWidth] = useState(320);

  // Tab State
  const [activeTab, setActiveTab] = useState('canvas');
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [showIconPicker, setShowIconPicker] = useState(false);
  const [dataMode, setDataMode] = useState('table');
  const [matrixInputs, setMatrixInputs] = useState({});
  const [seqInputs, setSeqInputs] = useState({ varName: '', start: 1, end: 10, prefix: '', suffix: '', padding: 3 });
  
  // Automatically switch tabs based on selection
  useEffect(() => {
    if (selectedItem || designMode === 'html') setActiveTab('element');
  }, [selectedId, selectedItem, designMode]);

  // Local settings state for explicit DB saving
  const [localSettings, setLocalSettings] = useState(settings);
  const [isSaving, setIsSaving] = useState(false);

  const [dupCopies, setDupCopies] = useState(1);
  const [dupGap, setDupGap] = useState(10);
  const [multCopies, setMultCopies] = useState(1);
  

  useEffect(() => {
    setLocalSettings(settings);
  }, [settings]);

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

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5 truncate";
  const labelTemplateOptions = [
    { id: 'default', label: 'Default' },
    { id: 'center', label: 'Center' },
    { id: 'maximize', label: 'Maximize' },
    { id: 'title_subtitle', label: 'Title + Subtitle' },
    { id: 'warning_banner', label: 'Warning Banner' },
    { id: 'price_tag', label: 'Price Tag' },
    { id: 'address', label: 'Address' },
    { id: 'custom', label: 'Custom HTML' }
  ];

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

  const handleProfileChange = (e) => {
    const { name, value } = e.target;
    const rawValue = Number(value);

    let nextValue = Number.isFinite(rawValue) ? rawValue : 0;

    if (name === 'speed') {
      nextValue = Math.max(0, Math.min(nextValue, maxSpeed));
    } else if (name === 'energy') {
      nextValue = Math.max(0, Math.min(nextValue, maxEnergy));
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
      await fetch(`/api/printers/${selectedPrinter}/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(useStore.getState().printerProfile)
      });
    } catch (e) {
      console.error("Failed to save printer profile", e);
    }
    setTimeout(() => setIsSaving(false), 1500);
  };

  const handleLocalSettingChange = (e) => {
    setLocalSettings({ ...localSettings, [e.target.name]: Number(e.target.value) });
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    await updateSettingsAPI(localSettings);
    setTimeout(() => setIsSaving(false), 1500);
  };
  

  // Restrict one axis strictly to the hardware print width, letting the feed axis grow infinitely.
  const dotsPerMm = localSettings.default_dpi / 25.4;
  const printPx = Math.round(localSettings.print_width_mm * dotsPerMm);

  const templateStr = items.map((i) => `${i.text || ''} ${i.title || ''} ${i.subtitle || ''} ${i.data || ''} ${i.html || ''} ${i.custom_html || ''}`).join(' ');
  const templateMatches = templateStr.match(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g) || [];
  const templateKeys = templateMatches.map((match) => match.replace(/[{}]/g, '').trim());
  const existingKeys = batchRecords.flatMap((record) => Object.keys(record || {}));
  const allBatchKeys = Array.from(new Set([...templateKeys, ...existingKeys]));
  const createEmptyBatchRecord = () => allBatchKeys.reduce((acc, key) => ({ ...acc, [key]: '' }), {});
  const batchKeySignature = allBatchKeys.join('||');

  useEffect(() => {
    setMatrixInputs((prev) => {
      const next = {};
      allBatchKeys.forEach((key) => {
        next[key] = prev[key] ?? '';
      });
      return next;
    });
  }, [batchKeySignature]);

  return (
    <div 
      className="bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 flex flex-col z-10 overflow-hidden transition-colors duration-300 relative shrink-0"
      style={{ width: panelWidth }}
    >
      <div 
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-blue-500 z-50 transition-colors"
        onMouseDown={handleResizeMouseDown}
      />
      
      {/* TABS */}
      <div className="flex border-b border-neutral-200 dark:border-neutral-800">
        <button 
          onClick={() => setActiveTab('element')}
          disabled={designMode !== 'html' && !selectedItem}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${designMode !== 'html' && !selectedItem ? 'text-neutral-300 dark:text-neutral-700 cursor-not-allowed' : 
            activeTab === 'element' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Sliders size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Element</span>
        </button>
        
        <button 
          onClick={() => setActiveTab('canvas')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'canvas' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Printer size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Canvas & Printer</span>
        </button>

        <button 
          onClick={() => setActiveTab('data')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'data' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Database size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">Batch Data</span>
        </button>

        <button 
          onClick={() => setActiveTab('assistant')}
          className={`flex-1 flex justify-center py-4 transition-colors relative group
            ${activeTab === 'assistant' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          <Sparkles size={20} />
          <span className="absolute top-full mt-1 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 z-50 pointer-events-none whitespace-nowrap font-bold uppercase tracking-widest">AI Assistant</span>
        </button>
      </div>

      <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
        
        {/* === CANVAS & PRINTER TAB === */}
        {activeTab === 'canvas' && (
          <>
            <div className="space-y-4">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Design Mode</h2>
              <div className="flex gap-2">
                <button
                  onClick={() => setDesignMode('canvas')}
                  className={`flex-1 py-2 text-[10px] uppercase font-bold tracking-widest border transition-colors ${
                    designMode === 'canvas'
                      ? 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400'
                      : 'bg-neutral-50 text-neutral-500 border-transparent dark:bg-neutral-900 hover:bg-neutral-100 dark:hover:bg-neutral-800'
                  }`}
                >
                  Canvas (WYSIWYG)
                </button>
                <button
                  onClick={() => setDesignMode('html')}
                  className={`flex-1 py-2 text-[10px] uppercase font-bold tracking-widest border transition-colors ${
                    designMode === 'html'
                      ? 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400'
                      : 'bg-neutral-50 text-neutral-500 border-transparent dark:bg-neutral-900 hover:bg-neutral-100 dark:hover:bg-neutral-800'
                  }`}
                >
                  HTML/CSS
                </button>
              </div>
            </div>

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
                  <button onClick={() => { setCanvasSize(840, 1184); setIsRotated(false); }} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A6</button>
                  <button onClick={() => { setCanvasSize(1184, 1680); setIsRotated(false); }} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A5</button>
                </div>
              )}

              <div className="flex gap-4 items-center">
                <label className="flex items-center gap-2 text-xs font-bold text-neutral-600 dark:text-neutral-400 mt-2 cursor-pointer border px-3 py-2 border-neutral-200 dark:border-neutral-800 rounded hover:bg-neutral-50 dark:hover:bg-neutral-900 w-full">
                  <input type="checkbox" checked={isRotated} onChange={(e) => setIsRotated(e.target.checked)} />
                  Rotate Feed (Landscape View)
                </label>
              </div>
              <div className="flex gap-4">
                <MmScrubberInput 
                  name="width" 
                  label={isRotated ? "Paper Length" : "Print Width"} 
                  value={canvasWidth} 
                  onChange={(e) => setCanvasSize(Number(e.target.value), canvasHeight)} 
                  disabled={!isRotated}
                />
                <MmScrubberInput 
                  name="height" 
                  label={isRotated ? "Print Width" : "Paper Length"} 
                  value={canvasHeight} 
                  onChange={(e) => setCanvasSize(canvasWidth, Number(e.target.value))} 
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
                  ? `Hardware Defaults: Speed ${selectedPrinterInfo?.default_speed ?? 'Auto'}, ${['niimbot', 'phomemo'].includes(selectedPrinterInfo?.vendor) ? 'Density' : 'Energy'} ${selectedPrinterInfo?.default_energy ?? 'Auto'}`
                  : 'Select a printer to configure device-specific overrides.'}
              </div>

              {selectedPrinterInfo?.media_type === 'continuous' && selectedPrinterInfo?.protocol_family?.includes('p12') && (
                <div className="mb-4 p-3 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded">
                  <label className={labelClass}>Adjust Tape Length</label>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => setCanvasSize(Math.max(getMmToPx(5), canvasWidth - getMmToPx(5)), canvasHeight)}
                      className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded text-lg font-bold dark:text-white"
                    >
                      -
                    </button>
                    <span className="flex-1 text-center text-xs font-bold dark:text-neutral-300">
                      {parseFloat(getPxToMm(canvasWidth)).toFixed(0)} mm
                    </span>
                    <button
                      onClick={() => setCanvasSize(canvasWidth + getMmToPx(5), canvasHeight)}
                      className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded text-lg font-bold dark:text-white"
                    >
                      +
                    </button>
                  </div>
                </div>
              )}

              {['niimbot', 'phomemo'].includes(selectedPrinterInfo?.vendor) ? (
                <div>
                  <label className={labelClass}>Print Density (1 - {maxDensity})</label>
                  <select
                    name="energy"
                    value={printerProfile?.energy || selectedPrinterInfo?.default_energy || 3}
                    onChange={handleProfileChange}
                    disabled={!selectedPrinter}
                    className={inputClass}
                  >
                    {Array.from({ length: maxDensity }, (_, i) => i + 1).map((level) => (
                      <option key={level} value={level}>
                        {level} - {level <= 2 ? 'Light' : level >= (maxDensity - 1) ? 'Dark' : 'Normal'}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <>
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
                      {pInfo.model ? `Hardware Default: ${defaultSpeed}. Max: ${maxSpeed}.` : 'Select a printer to view limits.'}
                    </p>
                  </div>
                  <div>
                    <label className={labelClass}>Energy / Density Override (0 = Auto)</label>
                    <input
                      type="number"
                      name="energy"
                      min={0}
                      max={maxEnergy}
                      step="500"
                      value={printerProfile?.energy || 0}
                      onChange={handleProfileChange}
                      disabled={!selectedPrinter}
                      className={inputClass}
                    />
                    <p className="text-[9px] text-neutral-400 mt-1">
                      {pInfo.model ? `Safe Range: ${minEnergy} - ${maxEnergy}. Default: ${defaultEnergy}.` : 'Select a printer to view limits.'}
                    </p>
                  </div>
                  <div>
                    <label className={labelClass}>Feed Lines (Tear Padding)</label>
                    <input
                      type="number"
                      name="feed_lines"
                      min={0}
                      value={printerProfile?.feed_lines ?? 100}
                      onChange={handleProfileChange}
                      disabled={!selectedPrinter}
                      className={inputClass}
                    />
                  </div>
                </>
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
                <select name="default_font" value={localSettings.default_font || 'RobotoCondensed.ttf'} onChange={(e) => setLocalSettings({ ...localSettings, default_font: e.target.value })} className={inputClass}>
                  <option value="arial.ttf">System Arial</option>
                  {fonts.map(f => (
                    <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                  ))}
                </select>
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
            {designMode === 'html' ? (
              <div className="space-y-4 h-full flex flex-col">
                <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">HTML Editor</h2>
                <p className="text-[10px] text-neutral-500">
                  Wrap text in <code>&lt;div class=&quot;auto-text&quot;&gt;</code> to automatically scale it to fit the container.
                </p>
                <textarea
                  value={htmlContent}
                  onChange={(e) => setHtmlContent(e.target.value)}
                  className="w-full flex-1 bg-neutral-50 dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-3 text-sm font-mono dark:text-white focus:outline-none focus:border-blue-500"
                  placeholder="<div class='auto-text'>Hello World</div>"
                />
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

                  <div className="flex gap-2 mt-2 border border-neutral-200 dark:border-neutral-800 rounded p-1 bg-neutral-50 dark:bg-neutral-900/50">
                    <ToggleBtn icon={Bold} label="Bold" active={selectedItem.weight >= 700} onClick={() => updateItem(selectedId, { weight: selectedItem.weight >= 700 ? 400 : 700 })} />
                    <ToggleBtn icon={Italic} label="Italic" active={selectedItem.italic} onClick={() => updateItem(selectedId, { italic: !selectedItem.italic })} />
                    <ToggleBtn icon={Underline} label="Underline" active={selectedItem.underline} onClick={() => updateItem(selectedId, { underline: !selectedItem.underline })} />
                  </div>

                  <div className="mt-3">
                    <label className={labelClass}>Font Family</label>
                    <select name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                      <option value="arial.ttf">System Arial</option>
                      {fonts.map(f => (
                        <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                      ))}
                    </select>
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

              {selectedItem.type === 'label_template' && (
                <>
                  <div>
                    <label className={labelClass}>Template</label>
                    <select name="template_id" value={selectedItem.template_id || 'default'} onChange={handleChange} className={inputClass}>
                      {labelTemplateOptions.map((template) => (
                        <option key={template.id} value={template.id}>{template.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className={labelClass}>Font Family</label>
                    <select name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                      <option value="arial.ttf">System Arial</option>
                      {fonts.map(f => (
                        <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                      ))}
                    </select>
                  </div>

                  {['title_subtitle', 'price_tag'].includes(selectedItem.template_id) ? (
                    <>
                      <div>
                        <label className={labelClass}>Title</label>
                        <input name="title" value={selectedItem.title || ''} onChange={handleChange} className={inputClass} />
                      </div>
                      <div>
                        <label className={labelClass}>Subtitle</label>
                        <input name="subtitle" value={selectedItem.subtitle || ''} onChange={handleChange} className={inputClass} />
                      </div>
                    </>
                  ) : selectedItem.template_id === 'custom' ? (
                    <div>
                      <label className={labelClass}>Custom HTML</label>
                      <textarea name="custom_html" value={selectedItem.custom_html || ''} onChange={handleChange} className={inputClass} rows={10} />
                    </div>
                  ) : (
                    <div>
                      <label className={labelClass}>{selectedItem.template_id === 'address' ? 'Address Text' : 'Main Text'}</label>
                      <textarea name="text" value={selectedItem.text || ''} onChange={handleChange} className={inputClass} rows={selectedItem.template_id === 'address' ? 6 : 3} />
                    </div>
                  )}
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
                    <select name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                      <option value="arial.ttf">System Arial</option>
                      {fonts.map(f => (
                        <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className={labelClass}>HTML Content</label>
                    <textarea name="html" value={selectedItem.html || ''} onChange={handleChange} className={inputClass} rows={8} />
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Frame Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Frame Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem.type === 'label_template' && (
                <div className="text-[10px] text-neutral-500 leading-relaxed border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/30 p-3">
                  Standard templates stay perfectly consistent. Use the <strong>Custom HTML</strong> option only for one-off styling requests.
                </div>
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

              {selectedItem.type !== 'label_template' && (
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
        {activeTab === 'data' && (
          <div className="space-y-4">
            <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Variable Data</h2>
            <p className="text-[10px] text-neutral-500 mb-2 leading-relaxed">
              Variables replace matching <code>{`{{ variable }}`}</code> tags on the canvas. Each row represents one printed label.
            </p>

            <div className="flex gap-2 mb-4">
              <button
                onClick={() => setDataMode('table')}
                className={`flex-1 py-2 text-[10px] uppercase font-bold tracking-widest transition-colors border ${dataMode === 'table' ? 'bg-blue-50 border-blue-200 text-blue-600 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400' : 'bg-neutral-50 border-transparent text-neutral-500 dark:bg-neutral-900'}`}
              >
                Table
              </button>
              <button
                onClick={() => setDataMode('matrix')}
                className={`flex-1 py-2 text-[10px] uppercase font-bold tracking-widest transition-colors border ${dataMode === 'matrix' ? 'bg-blue-50 border-blue-200 text-blue-600 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400' : 'bg-neutral-50 border-transparent text-neutral-500 dark:bg-neutral-900'}`}
              >
                Permutations
              </button>
              <button
                onClick={() => setDataMode('sequence')}
                className={`flex-1 py-2 text-[10px] uppercase font-bold tracking-widest transition-colors border ${dataMode === 'sequence' ? 'bg-blue-50 border-blue-200 text-blue-600 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400' : 'bg-neutral-50 border-transparent text-neutral-500 dark:bg-neutral-900'}`}
              >
                Sequence
              </button>
            </div>

            <div className="flex gap-2 mb-2">
              <button onClick={() => setShowBatchModal(true)} className="flex-1 flex items-center justify-center gap-2 py-1.5 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-600 dark:text-neutral-300 text-[10px] uppercase font-bold tracking-widest transition-colors">
                <FileSpreadsheet size={14} /> Import CSV
              </button>
              <button onClick={() => setBatchRecords([createEmptyBatchRecord()])} className="px-3 py-1.5 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors" title="Clear All Data">
                <Trash2 size={14} />
              </button>
            </div>

            {allBatchKeys.length === 0 && (
              <div className="text-center p-4 border border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-400 text-xs">
                No variables detected on canvas.<br/><br/> Add a text element containing a tag like <code>{`{{ name }}`}</code> to get started.
              </div>
            )}

            {allBatchKeys.length > 0 && dataMode === 'table' && (
              <div className="w-full overflow-x-auto border border-neutral-200 dark:border-neutral-800">
                <table className="w-full text-left text-xs whitespace-nowrap">
                  <thead className="bg-neutral-100 dark:bg-neutral-900 text-[10px] uppercase tracking-wider text-neutral-500">
                    <tr>
                      <th className="p-2 font-bold w-8 text-center">#</th>
                      {allBatchKeys.map((key) => (
                        <th key={key} className="p-2 font-bold border-l border-neutral-200 dark:border-neutral-800">
                          {key}
                        </th>
                      ))}
                      <th className="p-2 w-8"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800 bg-white dark:bg-neutral-950">
                    {batchRecords.map((record, index) => (
                      <tr key={index} className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50">
                        <td className="p-2 text-center text-neutral-400">{index + 1}</td>
                        {allBatchKeys.map((key) => (
                          <td key={key} className="border-l border-neutral-200 dark:border-neutral-800 p-0">
                            <input
                              type="text"
                              value={record[key] || ''}
                              onChange={(e) => updateBatchRecord(index, { ...record, [key]: e.target.value })}
                              className="w-full h-full p-2 bg-transparent focus:outline-none focus:bg-blue-50 dark:focus:bg-blue-900/20 dark:text-white transition-colors"
                              placeholder="..."
                            />
                          </td>
                        ))}
                        <td className="p-1 border-l border-neutral-200 dark:border-neutral-800">
                          <button onClick={() => removeBatchRecord(index)} className="w-full h-full p-1 text-neutral-400 hover:text-red-500 flex justify-center items-center">
                            <Trash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button onClick={() => addBatchRecord(createEmptyBatchRecord())} className="w-full flex justify-center items-center gap-2 py-2 bg-neutral-50 dark:bg-neutral-900 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors text-[10px] uppercase tracking-widest font-bold">
                  <Plus size={14} /> Add Row
                </button>
              </div>
            )}

            {allBatchKeys.length > 0 && dataMode === 'matrix' && (
              <div className="space-y-3 p-4 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
                <p className="text-[10px] text-neutral-500 mb-2 leading-relaxed">
                  Type comma-separated lists for each variable. We will automatically generate all combinations (Cartesian product).
                </p>
                {allBatchKeys.map((key) => (
                  <div key={key}>
                    <label className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1 block">{key} (comma separated)</label>
                    <input
                      type="text"
                      value={matrixInputs[key] || ''}
                      onChange={(e) => setMatrixInputs((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="w-full bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-2 text-xs focus:outline-none focus:border-blue-500 transition-colors dark:text-white"
                      placeholder="e.g. item 1, item 2, item 3"
                    />
                  </div>
                ))}
                <button
                  onClick={() => {
                    generateBatchMatrix(matrixInputs);
                    setDataMode('table');
                  }}
                  className="w-full mt-2 flex justify-center items-center gap-2 py-2 bg-blue-600 text-white hover:bg-blue-700 transition-colors text-[10px] uppercase tracking-widest font-bold"
                >
                  Generate Combinations
                </button>
              </div>
            )}

            {allBatchKeys.length > 0 && dataMode === 'sequence' && (
              <div className="space-y-3 p-4 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
                <p className="text-[10px] text-neutral-500 mb-2 leading-relaxed">
                  Generate serialized numbers (e.g. Asset Tags, Barcodes).
                </p>
                <div>
                  <label className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1 block">Target Variable</label>
                  <select
                    value={seqInputs.varName}
                    onChange={e => setSeqInputs({ ...seqInputs, varName: e.target.value })}
                    className={inputClass}
                  >
                    <option value="" disabled>Select variable...</option>
                    {allBatchKeys.map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Prefix</label>
                    <input
                      type="text"
                      value={seqInputs.prefix}
                      onChange={e => setSeqInputs({ ...seqInputs, prefix: e.target.value })}
                      className={inputClass}
                      placeholder="BOX-"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Suffix</label>
                    <input
                      type="text"
                      value={seqInputs.suffix}
                      onChange={e => setSeqInputs({ ...seqInputs, suffix: e.target.value })}
                      className={inputClass}
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Start #</label>
                    <input
                      type="number"
                      value={seqInputs.start}
                      onChange={e => setSeqInputs({ ...seqInputs, start: e.target.value })}
                      className={inputClass}
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">End #</label>
                    <input
                      type="number"
                      value={seqInputs.end}
                      onChange={e => setSeqInputs({ ...seqInputs, end: e.target.value })}
                      className={inputClass}
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">0-Pad</label>
                    <input
                      type="number"
                      min="0"
                      max="10"
                      value={seqInputs.padding}
                      onChange={e => setSeqInputs({ ...seqInputs, padding: e.target.value })}
                      className={inputClass}
                    />
                  </div>
                </div>
                <button
                  onClick={() => {
                    generateBatchSequence(seqInputs);
                    setDataMode('table');
                  }}
                  disabled={!seqInputs.varName}
                  className="w-full mt-2 flex justify-center items-center gap-2 py-2 bg-blue-600 text-white hover:bg-blue-700 transition-colors text-[10px] uppercase tracking-widest font-bold disabled:opacity-50"
                >
                  Generate Sequence
                </button>
              </div>
            )}
          </div>
        )}

        {/* === ASSISTANT TAB === */}
        {activeTab === 'assistant' && (
           <AIAssistant />
        )}
      </div>

      {showBatchModal && <BatchPrintModal onClose={() => setShowBatchModal(false)} />}
      {showIconPicker && (
        <IconPicker 
          onClose={() => setShowIconPicker(false)} 
          onSelect={(b64) => {
            updateItem(selectedId, { icon_src: b64 });
            setShowIconPicker(false);
          }} 
        />
      )}
    </div>
  );
}

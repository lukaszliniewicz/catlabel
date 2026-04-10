import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import { AlignCenter, MoveHorizontal, Maximize2 } from 'lucide-react';

const pxToMm = (px) => (px / 8).toFixed(1);
const mmToPx = (mm) => Math.round(mm * 8);

const MmScrubberInput = ({ name, value, onChange, label, disabled }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [startVal, setStartVal] = useState(0);

  const currentMm = value / 8;

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
      // 1 pixel drag = 0.5 mm change
      const newMm = Math.max(0, startVal + dx * 0.5);
      onChange({ target: { name, value: Math.round(newMm * 8), type: 'number' } });
    };
    const handleMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, startX, startVal, onChange, name]);

  const handleChange = (e) => {
    const mm = parseFloat(e.target.value);
    if (!isNaN(mm)) {
      onChange({ target: { name, value: Math.round(mm * 8), type: 'number' } });
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

const ScrubberInput = ({ name, value, onChange, label }) => {
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
      const newVal = Math.max(0, Math.round(startVal + dx * 0.5));
      onChange({ target: { name, value: newVal, type: 'number' } });
    };
    const handleMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, startX, startVal, onChange, name]);

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
        type="number" name={name} value={value} onChange={onChange} 
        className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors" 
      />
    </div>
  );
};

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, canvasBorder, setCanvasBorder, canvasBorderThickness, setCanvasBorderThickness, setCanvasSize, settings, updateSettingsAPI, fonts, isRotated, setIsRotated, splitMode, setSplitMode } = useStore();
  const selectedItem = items.find(i => i.id === selectedId);

  // Tab State
  const [activeTab, setActiveTab] = useState('canvas');
  
  // Automatically switch tabs based on selection
  useEffect(() => {
    if (selectedItem) setActiveTab('element');
  }, [selectedId]);

  // Local settings state for explicit DB saving
  const [localSettings, setLocalSettings] = useState(settings);
  const [isSaving, setIsSaving] = useState(false);

  const [dupCopies, setDupCopies] = useState(1);
  const [dupGap, setDupGap] = useState(10);
  
  // Workspace Multiplier Params
  const [multCopies, setMultCopies] = useState(1);
  const [multGap, setMultGap] = useState(10);
  const [multCutLines, setMultCutLines] = useState(true);

  useEffect(() => {
    setLocalSettings(settings);
  }, [settings]);

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5 truncate";

  // --- Actions ---

  const handleCenterAbsolute = () => {
    if (!selectedItem) return;
    const itemW = selectedItem.width || 0;
    const itemH = selectedItem.height || (selectedItem.type === 'text' ? selectedItem.size : 0);
    updateItem(selectedId, { 
      x: (canvasWidth - itemW) / 2, 
      y: (canvasHeight - itemH) / 2 
    });
  };

  const handleMakeFullWidth = () => {
    if (!selectedItem) return;
    updateItem(selectedId, { x: 0, width: canvasWidth, align: 'center' });
  };

  const handleFitToWidth = () => {
    if (!selectedItem || !selectedItem.width || !selectedItem.text) return;
    
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const fontFamily = selectedItem.font ? selectedItem.font.split('.')[0] : 'Arial';
    const fontWeight = selectedItem.weight || 700;
    
    const pad = (selectedItem.invert || selectedItem.bg_white) ? 4 : 0;
    const targetWidth = canvasWidth - (pad * 2);

    let low = 6;
    let high = 800; 
    let bestSize = selectedItem.size;
    const lines = String(selectedItem.text).split('\n');

    while (low <= high) {
      let mid = Math.floor((low + high) / 2);
      ctx.font = `${fontWeight} ${mid}px "${fontFamily}"`; 
      
      let maxLineWidth = 0;
      for (let l of lines) {
        let w = ctx.measureText(l).width;
        if (w > maxLineWidth) maxLineWidth = w;
      }
      
      if (maxLineWidth <= targetWidth) {
        bestSize = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    
    updateItem(selectedId, { 
      x: 0, 
      width: canvasWidth,
      size: bestSize, 
      no_wrap: true, 
      fit_to_width: true,
      align: 'center'
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

  const handleLocalSettingChange = (e) => {
    setLocalSettings({ ...localSettings, [e.target.name]: Number(e.target.value) });
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    await updateSettingsAPI(localSettings);
    setTimeout(() => setIsSaving(false), 1500);
  };
  
  const handleMultiply = () => {
    useStore.getState().multiplyWorkspace(multCopies, multGap, multCutLines);
    alert('Workspace Expanded Successfully!');
  };

  // Restrict one axis strictly to the hardware print width, letting the feed axis grow infinitely.
  const dotsPerMm = localSettings.default_dpi / 25.4;
  const printPx = Math.round(localSettings.print_width_mm * dotsPerMm);

  useEffect(() => {
    if (splitMode) return; // Do not constrain canvas dimensions if the user is designing an oversized layout

    if (isRotated && canvasHeight !== printPx) {
      setCanvasSize(canvasWidth, printPx);
    } else if (!isRotated && canvasWidth !== printPx) {
      setCanvasSize(printPx, canvasHeight);
    }
  }, [isRotated, printPx, splitMode]);

  return (
    <div className="w-80 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 flex flex-col z-10 overflow-hidden transition-colors duration-300">
      
      {/* TABS */}
      <div className="flex border-b border-neutral-200 dark:border-neutral-800">
        <button 
          onClick={() => setActiveTab('element')}
          disabled={!selectedItem}
          className={`flex-1 py-4 text-xs font-bold uppercase tracking-widest transition-colors
            ${!selectedItem ? 'text-neutral-300 dark:text-neutral-700 cursor-not-allowed' : 
            activeTab === 'element' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          Element
        </button>
        <button 
          onClick={() => setActiveTab('canvas')}
          className={`flex-1 py-4 text-xs font-bold uppercase tracking-widest transition-colors
            ${activeTab === 'canvas' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-neutral-500 hover:bg-neutral-50 dark:hover:bg-neutral-900'}
          `}
        >
          Canvas & Printer
        </button>
      </div>

      <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
        
        {/* === CANVAS & PRINTER TAB === */}
        {activeTab === 'canvas' && (
          <>
            <div className="space-y-4">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Dimensions</h2>
              
              <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-red-600 dark:text-red-400 mt-2 cursor-pointer border px-3 py-2 border-red-200 dark:border-red-900/30 bg-red-50 dark:bg-red-950/20 rounded hover:bg-red-100 dark:hover:bg-red-900/40 w-full transition-colors">
                <input type="checkbox" checked={splitMode || false} onChange={(e) => setSplitMode(e.target.checked)} />
                Oversize / Split Print Mode
              </label>
              
              {splitMode && (
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

            {/* WORKSPACE MULTIPLIER (Repeater logic) */}
            <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Workspace Multiplier</h2>
              <p className="text-[10px] text-neutral-500 mb-2">Easily prepare similar labels by expanding the canvas and cloning all current elements along the feed axis.</p>
              
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-[10px] text-neutral-400 font-bold uppercase mb-1">Copies</label>
                  <input type="number" min="1" value={multCopies} onChange={e => setMultCopies(parseInt(e.target.value)||1)} className={inputClass} />
                </div>
                <div className="flex-1">
                  <label className="block text-[10px] text-neutral-400 font-bold uppercase mb-1">Gap (mm)</label>
                  <input type="number" min="0" value={multGap} onChange={e => setMultGap(parseFloat(e.target.value)||0)} className={inputClass} />
                </div>
              </div>
              <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer mt-2">
                <input type="checkbox" checked={multCutLines} onChange={e => setMultCutLines(e.target.checked)} /> Add Line Separators
              </label>
              <button onClick={handleMultiply} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold mt-2">
                Extend & Multiply Workspace
              </button>
            </div>

            <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Printer Config</h2>
              <div>
                <label className={labelClass}>Speed (0 = Device Profile Auto)</label>
                <input type="number" name="speed" value={localSettings.speed} onChange={handleLocalSettingChange} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>Print Energy / Darkness (0 = Auto)</label>
                <input type="number" name="energy" value={localSettings.energy} onChange={handleLocalSettingChange} step="500" className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>Feed Lines (Tear Padding)</label>
                <input type="number" name="feed_lines" value={localSettings.feed_lines} onChange={handleLocalSettingChange} className={inputClass} />
              </div>
              <div className="pt-2">
                <label className={labelClass}>Global Default Font</label>
                <select name="default_font" value={localSettings.default_font || 'Roboto.ttf'} onChange={(e) => setLocalSettings({ ...localSettings, default_font: e.target.value })} className={inputClass}>
                  <option value="arial.ttf">System Arial</option>
                  {fonts.map(f => (
                    <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                  ))}
                </select>
                <p className="text-[9px] text-neutral-400 mt-1">Applies to all newly created text items.</p>
              </div>
            </div>

            <div className="mt-auto pt-6">
              <button 
                onClick={handleSaveSettings} 
                disabled={isSaving}
                className={`w-full py-3 rounded-none transition-colors text-xs uppercase tracking-widest font-bold border 
                  ${isSaving 
                    ? 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 border-green-200' 
                    : 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 border-transparent hover:bg-neutral-800 dark:hover:bg-neutral-200'}`}
              >
                {isSaving ? 'Settings Saved ✓' : 'Save Printer Settings'}
              </button>
            </div>
          </>
        )}

        {/* === ELEMENT TAB === */}
        {activeTab === 'element' && selectedItem && (
          <>
            <div className="space-y-4">
              <div>
                <div className="flex gap-4">
                  <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                  <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
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
                  <div className="flex gap-4">
                    <ScrubberInput name="size" label="Font Size" value={Math.round(selectedItem.size)} onChange={handleChange} />
                    <ScrubberInput name="weight" label="Weight (100-900)" value={selectedItem.weight || 700} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass}>Font</label>
                      <select name="font" value={selectedItem.font || 'Roboto.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Box Width" value={selectedItem.width || 0} onChange={handleChange} />
                    <div className="flex-1">
                      <label className={labelClass}>Align</label>
                      <select name="align" value={selectedItem.align || 'left'} onChange={handleChange} className={inputClass}>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="no_wrap" checked={selectedItem.no_wrap || false} onChange={handleChange} /> Single Line
                    </label>
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="fit_to_width" checked={selectedItem.fit_to_width || false} onChange={handleChange} /> Auto-Fit
                    </label>
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="invert" checked={selectedItem.invert || false} onChange={handleChange} /> Invert Box
                    </label>
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="bg_white" checked={selectedItem.bg_white || false} onChange={handleChange} /> Solid White BG
                    </label>
                  </div>
                </>
              )}

              {selectedItem.type === 'icon_text' && (
                <>
                  <div className="flex gap-2 mb-2 bg-neutral-50 dark:bg-neutral-900 p-1 border border-neutral-200 dark:border-neutral-800">
                     <button onClick={() => {
                        const newH = Math.max(selectedItem.icon_size, selectedItem.size);
                        updateItem(selectedId, {
                           icon_x: 0, icon_y: (newH - selectedItem.icon_size)/2,
                           text_x: selectedItem.icon_size + 15, text_y: (newH - selectedItem.size)/2,
                           width: selectedItem.icon_size + 15 + (selectedItem.text.length * selectedItem.size * 0.6),
                           height: newH
                        });
                     }} className="flex-1 text-[10px] uppercase font-bold text-neutral-500 py-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">Row</button>
                     <button onClick={() => {
                        const newW = Math.max(selectedItem.icon_size, selectedItem.text.length * selectedItem.size * 0.6);
                        updateItem(selectedId, {
                           icon_x: (newW - selectedItem.icon_size)/2, icon_y: 0,
                           text_x: (newW - (selectedItem.text.length * selectedItem.size * 0.6))/2, text_y: selectedItem.icon_size + 10,
                           width: newW,
                           height: selectedItem.icon_size + 10 + selectedItem.size
                        });
                     }} className="flex-1 text-[10px] uppercase font-bold text-neutral-500 py-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">Col</button>
                     <button onClick={() => {
                        const canvas = document.createElement('canvas');
                        const ctx = canvas.getContext('2d');
                        const fontFamily = selectedItem.font ? selectedItem.font.split('.')[0] : 'Arial';
                        const fontWeight = selectedItem.weight || 700; // ADD WEIGHT
                        
                        let low = 6; let high = 400;
                        let bestScale = 1; let bestTextSize = selectedItem.size;
                        
                        while (low <= high) {
                            let mid = Math.floor((low + high) / 2);
                            ctx.font = `${fontWeight} ${mid}px "${fontFamily}"`; // Apply properly
                            let tWidth = ctx.measureText(selectedItem.text || '').width;
                            let testScale = mid / selectedItem.size;
                            let totalW = (selectedItem.icon_size * testScale) + (15 * testScale) + tWidth;
                            
                            if (totalW <= canvasWidth) {
                                bestTextSize = mid; bestScale = testScale;
                                low = mid + 1;
                            } else {
                                high = mid - 1;
                            }
                        }
                        
                        const newIconSize = selectedItem.icon_size * bestScale;
                        const newH = Math.max(newIconSize, bestTextSize);
                        ctx.font = `${fontWeight} ${bestTextSize}px "${fontFamily}"`; // Apply properly here too
                        const actualTextW = ctx.measureText(selectedItem.text || '').width;
                        const finalW = newIconSize + (15 * bestScale) + actualTextW;
                        
                        updateItem(selectedId, {
                            icon_size: newIconSize, size: bestTextSize,
                            icon_x: 0, icon_y: (newH - newIconSize) / 2,
                            text_x: newIconSize + (15 * bestScale), text_y: (newH - bestTextSize) / 2,
                            width: finalW, height: newH,
                            x: (canvasWidth - finalW) / 2
                        });
                     }} className="flex-1 text-[10px] uppercase font-bold text-blue-600 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors">Fit Width</button>
                  </div>
                  <div>
                    <label className={labelClass}>Group Text</label>
                    <input type="text" name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <ScrubberInput name="size" label="Text Size" value={Math.round(selectedItem.size)} onChange={handleChange} />
                    <ScrubberInput name="weight" label="Weight (100-900)" value={selectedItem.weight || 700} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="icon_size" label="Icon Size" value={Math.round(selectedItem.icon_size)} onChange={handleChange} />
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
                    <label className={labelClass}>HTML Content</label>
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
      </div>
    </div>
  );
}

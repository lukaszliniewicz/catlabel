import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import { AlignCenter, MoveHorizontal, Maximize2 } from 'lucide-react';

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
        className="block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5 cursor-ew-resize hover:text-blue-500 transition-colors" 
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
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, setCanvasSize, settings, updateSettingsAPI, fonts } = useStore();
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

  useEffect(() => {
    setLocalSettings(settings);
  }, [settings]);

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5";

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
    
    let low = 6;
    let high = 800; 
    let bestSize = selectedItem.size;
    const targetWidth = canvasWidth; // Force stretch to full canvas width

    while (low <= high) {
      let mid = Math.floor((low + high) / 2);
      ctx.font = `${mid}px ${fontFamily}`; 
      let textWidth = ctx.measureText(selectedItem.text.split('\n')[0]).width;
      
      if (textWidth <= targetWidth) {
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

  // Warning check for Canvas stretching beyond printer limits
  const dotsPerMm = localSettings.default_dpi / 25.4;
  const printPx = Math.round(localSettings.print_width_mm * dotsPerMm);
  const isCanvasTooWide = canvasWidth > printPx;

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
              <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Canvas Dimensions</h2>
              <div className="flex gap-4">
                <ScrubberInput 
                  name="width" 
                  label="Width (px)" 
                  value={canvasWidth} 
                  onChange={(e) => setCanvasSize(Number(e.target.value), canvasHeight)} 
                />
                <ScrubberInput 
                  name="height" 
                  label="Height (px)" 
                  value={canvasHeight} 
                  onChange={(e) => setCanvasSize(canvasWidth, Number(e.target.value))} 
                />
              </div>
              {isCanvasTooWide && (
                <p className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 p-2 border border-red-200 dark:border-red-800">
                  Warning: Canvas width ({canvasWidth}px) exceeds your printer's max width ({printPx}px). It will be truncated.
                </p>
              )}
            </div>

            <div className="space-y-4 mt-4">
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
                  <ScrubberInput name="x" label="X Pos" value={Math.round(selectedItem.x)} onChange={handleChange} />
                  <ScrubberInput name="y" label="Y Pos" value={Math.round(selectedItem.y)} onChange={handleChange} />
                </div>
                
                {/* Advanced Centering Controls */}
                <div className="flex gap-2 mt-3">
                  <button onClick={handleCenterAbsolute} title="Center Absolutely" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 dark:hover:bg-blue-900/30 dark:hover:text-blue-400 transition-colors border border-transparent hover:border-blue-200 dark:hover:border-blue-800">
                    <AlignCenter size={16} />
                  </button>
                  <button onClick={handleMakeFullWidth} title="Full Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 dark:hover:bg-blue-900/30 dark:hover:text-blue-400 transition-colors border border-transparent hover:border-blue-200 dark:hover:border-blue-800">
                    <MoveHorizontal size={16} />
                  </button>
                  {selectedItem.type === 'text' && (
                    <button onClick={handleFitToWidth} title="Maximize Font to Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 dark:hover:bg-blue-900/30 dark:hover:text-blue-400 transition-colors border border-transparent hover:border-blue-200 dark:hover:border-blue-800">
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
                    <ScrubberInput name="size" label="Size" value={selectedItem.size} onChange={handleChange} />
                    <div className="flex-1">
                      <label className={labelClass}>Font</label>
                      <select name="font" value={selectedItem.font || 'arial.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="flex gap-4">
                    <ScrubberInput name="width" label="Width" value={selectedItem.width || 0} onChange={handleChange} />
                    <div className="flex-1">
                      <label className={labelClass}>Align</label>
                      <select name="align" value={selectedItem.align || 'left'} onChange={handleChange} className={inputClass}>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 mt-2 cursor-pointer">
                    <input type="checkbox" name="no_wrap" checked={selectedItem.no_wrap || false} onChange={handleChange} />
                    Disable Word Wrap (Single Line)
                  </label>
                  <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 mt-1 cursor-pointer">
                    <input type="checkbox" name="fit_to_width" checked={selectedItem.fit_to_width || false} onChange={handleChange} />
                    Auto-fit on print
                  </label>
                </>
              )}

              {selectedItem.type === 'image' && (
                <div className="flex gap-4">
                  <ScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                  <ScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                </div>
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
                    <ScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                    <ScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}
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

import React, { useState, useEffect } from 'react';
import { useStore } from '../store';

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
        className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors" 
      />
    </div>
  );
};

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, setCanvasSize } = useStore();
  const selectedItem = items.find(i => i.id === selectedId);

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5";

  if (!selectedItem) {
    return (
      <div className="w-72 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 p-6 flex flex-col z-10 transition-colors duration-300">
        <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white border-b border-neutral-100 dark:border-neutral-800 pb-2 mb-6">Canvas.</h2>
        <div className="space-y-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <label className={labelClass}>Width (px)</label>
              <input type="number" value={canvasWidth} onChange={(e) => setCanvasSize(Number(e.target.value), canvasHeight)} className={inputClass} />
            </div>
            <div className="flex-1">
              <label className={labelClass}>Height (px)</label>
              <input type="number" value={canvasHeight} onChange={(e) => setCanvasSize(canvasWidth, Number(e.target.value))} className={inputClass} />
            </div>
          </div>
        </div>
        <p className="text-neutral-400 dark:text-neutral-600 text-xs uppercase tracking-widest text-center mt-10">Select an item to edit</p>
      </div>
    );
  }

  const handleCenterH = () => {
    const itemW = selectedItem.width || 0;
    updateItem(selectedId, { x: (canvasWidth - itemW) / 2 });
  };

  const handleCenterV = () => {
    const itemH = selectedItem.height || (selectedItem.type === 'text' ? selectedItem.size : 0);
    updateItem(selectedId, { y: (canvasHeight - itemH) / 2 });
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    let parsedValue = type === 'checkbox' ? checked : (type === 'number' ? Number(value) : value);
    updateItem(selectedId, { [name]: parsedValue });
  };

  return (
    <div className="w-72 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 p-6 flex flex-col gap-6 z-10 overflow-y-auto transition-colors duration-300">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white border-b border-neutral-100 dark:border-neutral-800 pb-2">Properties.</h2>
      
      <div className="space-y-4">
        <div>
          <div className="flex gap-4">
            <ScrubberInput name="x" label="X Pos" value={Math.round(selectedItem.x)} onChange={handleChange} />
            <ScrubberInput name="y" label="Y Pos" value={Math.round(selectedItem.y)} onChange={handleChange} />
          </div>
          <div className="flex gap-2 mt-2">
            <button onClick={handleCenterH} className="flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-1.5 text-[10px] uppercase tracking-widest hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">Center H</button>
            <button onClick={handleCenterV} className="flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-1.5 text-[10px] uppercase tracking-widest hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">Center V</button>
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
                <input type="text" name="font" value={selectedItem.font} onChange={handleChange} className={inputClass} placeholder="arial.ttf" />
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
            <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 mt-2">
              <input type="checkbox" name="fit_to_width" checked={selectedItem.fit_to_width || false} onChange={handleChange} />
              Auto-fit font size to Width
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
    </div>
  );
}

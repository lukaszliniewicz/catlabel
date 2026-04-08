import React from 'react';
import { useStore } from '../store';

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem } = useStore();
  const selectedItem = items.find(i => i.id === selectedId);

  if (!selectedItem) {
    return (
      <div className="w-72 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 p-6 flex flex-col z-10 transition-colors duration-300">
        <p className="text-neutral-400 dark:text-neutral-600 text-xs uppercase tracking-widest text-center mt-10">Select an item to edit</p>
      </div>
    );
  }

  const handleChange = (e) => {
    const { name, value, type } = e.target;
    let parsedValue = value;
    if (type === 'number') parsedValue = Number(value);
    updateItem(selectedId, { [name]: parsedValue });
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-sm text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest mb-1.5";

  return (
    <div className="w-72 bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 p-6 flex flex-col gap-6 z-10 overflow-y-auto transition-colors duration-300">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white border-b border-neutral-100 dark:border-neutral-800 pb-2">Properties.</h2>
      
      <div className="space-y-4">
        <div className="flex gap-4">
          <div className="flex-1">
            <label className={labelClass}>X Pos</label>
            <input type="number" name="x" value={Math.round(selectedItem.x)} onChange={handleChange} className={inputClass} />
          </div>
          <div className="flex-1">
            <label className={labelClass}>Y Pos</label>
            <input type="number" name="y" value={Math.round(selectedItem.y)} onChange={handleChange} className={inputClass} />
          </div>
        </div>

        {selectedItem.type === 'text' && (
          <>
            <div>
              <label className={labelClass}>Text Content</label>
              <textarea name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} rows={3} />
            </div>
            <div className="flex gap-4">
              <div className="flex-1">
                <label className={labelClass}>Size</label>
                <input type="number" name="size" value={selectedItem.size} onChange={handleChange} className={inputClass} />
              </div>
              <div className="flex-1">
                <label className={labelClass}>Font</label>
                <input type="text" name="font" value={selectedItem.font} onChange={handleChange} className={inputClass} placeholder="arial.ttf" />
              </div>
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
              <div className="flex-1">
                <label className={labelClass}>Width</label>
                <input type="number" name="width" value={selectedItem.width} onChange={handleChange} className={inputClass} />
              </div>
              <div className="flex-1">
                <label className={labelClass}>Height</label>
                <input type="number" name="height" value={selectedItem.height} onChange={handleChange} className={inputClass} />
              </div>
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

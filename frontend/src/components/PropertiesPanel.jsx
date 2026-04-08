import React from 'react';
import { useStore } from '../store';

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem } = useStore();
  const selectedItem = items.find(i => i.id === selectedId);

  if (!selectedItem) {
    return (
      <div className="w-64 bg-white border-l border-gray-200 p-4 flex flex-col shadow-sm z-10">
        <p className="text-gray-500 text-sm text-center mt-10">Select an item on the canvas to edit its properties.</p>
      </div>
    );
  }

  const handleChange = (e) => {
    const { name, value, type } = e.target;
    let parsedValue = value;
    if (type === 'number') parsedValue = Number(value);
    updateItem(selectedId, { [name]: parsedValue });
  };

  return (
    <div className="w-64 bg-white border-l border-gray-200 p-4 flex flex-col gap-4 shadow-sm z-10 overflow-y-auto">
      <h2 className="text-lg font-bold text-gray-800 border-b pb-2">Properties</h2>
      
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">X Position</label>
          <input type="number" name="x" value={Math.round(selectedItem.x)} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Y Position</label>
          <input type="number" name="y" value={Math.round(selectedItem.y)} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
        </div>

        {selectedItem.type === 'text' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Text Content</label>
              <textarea name="text" value={selectedItem.text} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" rows={3} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Font Size</label>
              <input type="number" name="size" value={selectedItem.size} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Font</label>
              <input type="text" name="font" value={selectedItem.font} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="arial.ttf" />
            </div>
          </>
        )}

        {selectedItem.type === 'barcode' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Barcode Data</label>
              <input type="text" name="data" value={selectedItem.data} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Barcode Type</label>
              <select name="barcode_type" value={selectedItem.barcode_type} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm">
                <option value="code128">Code 128</option>
                <option value="code39">Code 39</option>
                <option value="ean13">EAN-13</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Width</label>
              <input type="number" name="width" value={selectedItem.width} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Height</label>
              <input type="number" name="height" value={selectedItem.height} onChange={handleChange} className="w-full border border-gray-300 rounded p-1.5 text-sm" />
            </div>
          </>
        )}
      </div>

      <div className="mt-auto pt-4 border-t border-gray-200">
        <button 
          onClick={() => deleteItem(selectedId)} 
          className="w-full bg-red-50 text-red-600 border border-red-200 px-4 py-2 rounded hover:bg-red-100 transition-colors text-sm font-medium"
        >
          Delete Item
        </button>
      </div>
    </div>
  );
}

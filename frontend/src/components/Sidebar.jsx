import React from 'react';
import { useStore } from '../store';

export default function Sidebar() {
  const addItem = useStore((state) => state.addItem);

  const handleAddText = () => {
    addItem({
      id: Date.now().toString(),
      type: 'text',
      text: 'Double click to edit',
      x: 50,
      y: 50,
      size: 24,
      font: 'arial.ttf'
    });
  };

  const handleAddBarcode = () => {
    addItem({
      id: Date.now().toString(),
      type: 'barcode',
      data: '123456789',
      barcode_type: 'code128',
      x: 50,
      y: 100,
      width: 200,
      height: 50
    });
  };

  return (
    <div className="w-64 bg-white border-r border-gray-200 p-4 flex flex-col gap-4 shadow-sm z-10">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Label Studio</h1>
      
      <div className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Tools</h2>
        <button 
          onClick={handleAddText} 
          className="w-full bg-blue-50 text-blue-600 border border-blue-200 px-4 py-2 rounded hover:bg-blue-100 transition-colors text-left font-medium"
        >
          + Add Text
        </button>
        <button 
          onClick={handleAddBarcode} 
          className="w-full bg-green-50 text-green-600 border border-green-200 px-4 py-2 rounded hover:bg-green-100 transition-colors text-left font-medium"
        >
          + Add Barcode
        </button>
      </div>
    </div>
  );
}

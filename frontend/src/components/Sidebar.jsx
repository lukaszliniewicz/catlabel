import React, { useState } from 'react';
import { useStore } from '../store';

export default function Sidebar() {
  const { addItem, items, canvasWidth, canvasHeight, selectedPrinter, setSelectedPrinter } = useStore();
  const [printers, setPrinters] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);

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

  const handleScan = async () => {
    setIsScanning(true);
    try {
      const res = await fetch('http://localhost:8000/api/printers/scan');
      const data = await res.json();
      setPrinters(data.devices || []);
    } catch (e) {
      console.error(e);
      alert("Failed to scan for printers. Is the backend running on port 8000?");
    }
    setIsScanning(false);
  };

  const handlePrint = async () => {
    if (!selectedPrinter) return alert("Please select a printer first!");
    setIsPrinting(true);
    try {
      // 1. Save template temporarily
      const tplRes = await fetch('http://localhost:8000/api/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: 'Quick Print ' + new Date().toISOString(),
          canvas_state: { width: canvasWidth, height: canvasHeight, items }
        })
      });
      const tpl = await tplRes.json();

      // 2. Send print command
      const printRes = await fetch(`http://localhost:8000/api/print/template/${tpl.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mac_address: selectedPrinter, variables: {} })
      });
      
      if (!printRes.ok) throw new Error("Print failed");
      alert("Print job sent successfully!");
    } catch (e) {
      console.error(e);
      alert("Failed to print.");
    }
    setIsPrinting(false);
  };

  return (
    <div className="w-64 bg-white border-r border-gray-200 p-4 flex flex-col gap-4 shadow-sm z-10 overflow-y-auto">
      <h1 className="text-2xl font-bold text-gray-800 mb-2">Label Studio</h1>
      
      <div className="space-y-2 mb-4">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Tools</h2>
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

      <div className="space-y-2 mb-4">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Printers</h2>
        <button 
          onClick={handleScan} 
          disabled={isScanning}
          className="w-full bg-gray-50 text-gray-700 border border-gray-200 px-4 py-2 rounded hover:bg-gray-100 transition-colors text-sm font-medium disabled:opacity-50"
        >
          {isScanning ? 'Scanning...' : 'Scan for Printers'}
        </button>
        
        {printers.length > 0 && (
          <select 
            className="w-full border border-gray-300 rounded p-2 text-sm mt-2"
            value={selectedPrinter || ''}
            onChange={(e) => setSelectedPrinter(e.target.value)}
          >
            <option value="" disabled>Select a printer...</option>
            {printers.map(p => (
              <option key={p.address} value={p.address}>{p.name || p.display_address}</option>
            ))}
          </select>
        )}
      </div>

      <div className="mt-auto pt-4 border-t border-gray-200">
        <button 
          onClick={handlePrint}
          disabled={isPrinting || !selectedPrinter}
          className="w-full bg-indigo-600 text-white px-4 py-3 rounded hover:bg-indigo-700 transition-colors font-bold shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isPrinting ? 'Printing...' : 'Test Print'}
        </button>
      </div>
    </div>
  );
}

import React, { useState } from 'react';
import { X, Upload } from 'lucide-react';
import { useStore } from '../store';

export default function BatchPrintModal({ onClose }) {
  const { canvasWidth, canvasHeight, canvasBorder, items, selectedPrinter, splitMode } = useStore();
  const isRotated = useStore(state => state.isRotated);
  const [tab, setTab] = useState('copies');
  const [copies, setCopies] = useState(1);
  const [csvData, setCsvData] = useState([]);
  const [headers, setHeaders] = useState([]);
  const [isPrinting, setIsPrinting] = useState(false);

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target.result;
      const lines = text.split('\n').filter(l => l.trim() !== '');
      if (lines.length > 0) {
        const head = lines[0].split(',').map(h => h.trim());
        setHeaders(head);
        const data = lines.slice(1).map(line => {
          const vals = line.split(',');
          let obj = {};
          head.forEach((h, i) => { obj[h] = vals[i] ? vals[i].trim() : ''; });
          return obj;
        });
        setCsvData(data);
      }
    };
    reader.readAsText(file);
  };

  const handlePrint = async () => {
    setIsPrinting(true);
    const thickness = useStore.getState().canvasBorderThickness || 2;
    try {
      const res = await fetch('http://localhost:8000/api/print/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: selectedPrinter,
          canvas_state: { width: canvasWidth, height: canvasHeight, isRotated, canvasBorder, canvasBorderThickness: thickness, splitMode, items },
          copies: parseInt(copies, 10) || 1,
          variables_list: tab === 'csv' ? csvData : []
        })
      });
      if (!res.ok) {
         const err = await res.json();
         throw new Error(err.detail || "Batch Print Engine failed");
      }
      alert("Batch Print stream finished continuously!");
      onClose();
    } catch (e) {
      alert("Failed to print: " + e.message);
    }
    setIsPrinting(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-900 w-full max-w-md rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">Print Multiple Copies</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="flex border-b border-neutral-100 dark:border-neutral-800">
          <button onClick={() => setTab('copies')} className={`flex-1 py-3 text-xs font-bold uppercase tracking-widest ${tab==='copies'?'text-blue-600 border-b-2 border-blue-600':'text-neutral-500'}`}>Multiple Copies</button>
          <button onClick={() => setTab('csv')} className={`flex-1 py-3 text-xs font-bold uppercase tracking-widest ${tab==='csv'?'text-blue-600 border-b-2 border-blue-600':'text-neutral-500'}`}>CSV Variables</button>
        </div>

        <div className="p-6 space-y-4">
          {tab === 'copies' ? (
            <div>
              <label className="block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-2">Total Exact Copies</label>
              <input type="number" min="1" value={copies} onChange={e=>setCopies(e.target.value)} className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500" />
            </div>
          ) : (
            <div>
              <label className="flex items-center justify-center w-full bg-neutral-50 dark:bg-neutral-950 border border-dashed border-neutral-300 dark:border-neutral-700 p-6 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-colors">
                <div className="text-center">
                  <Upload className="mx-auto text-neutral-400 mb-2" size={24} />
                  <span className="text-sm dark:text-white">Upload Variable Data (.CSV)</span>
                </div>
                <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
              </label>
              {headers.length > 0 && (
                <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded">
                  <p className="text-xs text-green-600 font-bold mb-1">✓ File Registered ({csvData.length} records)</p>
                  <p className="text-[10px] text-neutral-500">Mappings mapped: {headers.join(', ')}</p>
                </div>
              )}
              <div className="mt-4">
                <label className="block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1">Print Volume Per Record Line</label>
                <input type="number" min="1" value={copies} onChange={e=>setCopies(e.target.value)} className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500" />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800 mt-auto">
          <button 
            onClick={handlePrint}
            disabled={isPrinting || !selectedPrinter || (tab === 'csv' && csvData.length === 0)}
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50"
          >
            {isPrinting ? 'Streaming to Printer...' : 'Fire Batch Queue'}
          </button>
        </div>

      </div>
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import { useStore } from '../store';

export default function Sidebar() {
  const { addItem, items, setItems, setCanvasSize, clearCanvas, canvasWidth, canvasHeight, selectedPrinter, setSelectedPrinter, theme, setTheme } = useStore();
  const [printers, setPrinters] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);
  const [currentTemplateId, setCurrentTemplateId] = useState(null);

  useEffect(() => {
    fetchTemplates();
  }, []);

  const fetchTemplates = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/templates');
      const data = await res.json();
      setTemplates(data);
    } catch (e) {
      console.error("Failed to fetch templates", e);
    }
  };

  const handleAddText = () => {
    addItem({
      id: Date.now().toString(),
      type: 'text',
      text: 'Double click to edit',
      x: 50,
      y: 50,
      size: 24,
      font: 'arial.ttf',
      width: canvasWidth - 100,
      align: 'center'
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

  const handleAddImage = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new window.Image();
      img.src = ev.target.result;
      img.onload = () => {
        // Automatically scale image to fit the 384px print area
        const ratio = img.width / img.height;
        const targetWidth = Math.min(img.width, canvasWidth);
        const targetHeight = targetWidth / ratio;

        addItem({
          id: Date.now().toString(),
          type: 'image',
          src: ev.target.result,
          x: 0,
          y: 0,
          width: targetWidth,
          height: targetHeight
        });
      };
    };
    reader.readAsDataURL(file);
    e.target.value = null; // reset input
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

  const handleSaveTemplate = async () => {
    const name = prompt("Enter a name for this template:");
    if (!name) return;
    
    try {
      await fetch('http://localhost:8000/api/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          canvas_state: { width: canvasWidth, height: canvasHeight, items }
        })
      });
      alert("Template saved!");
      fetchTemplates();
    } catch (e) {
      console.error(e);
      alert("Failed to save template.");
    }
  };

  const handleLoadTemplate = (e) => {
    const tplId = Number(e.target.value);
    if (!tplId) return;
    
    setCurrentTemplateId(tplId);
    const tpl = templates.find(t => t.id === tplId);
    if (tpl) {
      setCanvasSize(tpl.canvas_state.width || 384, tpl.canvas_state.height || 384);
      setItems(tpl.canvas_state.items || []);
    }
    e.target.value = ""; // Reset dropdown
  };

  const handleUpdateTemplate = async () => {
    if (!currentTemplateId) return;
    try {
      await fetch(`http://localhost:8000/api/templates/${currentTemplateId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canvas_state: { width: canvasWidth, height: canvasHeight, items }
        })
      });
      alert("Template updated!");
      fetchTemplates();
    } catch (e) {
      console.error(e);
      alert("Failed to update template.");
    }
  };

  const handlePrint = async () => {
    if (!selectedPrinter) return alert("Please select a printer first!");
    setIsPrinting(true);
    try {
      const printRes = await fetch(`http://localhost:8000/api/print/direct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          mac_address: selectedPrinter, 
          canvas_state: { width: canvasWidth, height: canvasHeight, items },
          variables: {} 
        })
      });
      
      if (!printRes.ok) {
        const err = await printRes.json();
        throw new Error(err.detail || "Print failed");
      }
      alert("Print job sent successfully!");
    } catch (e) {
      console.error(e);
      alert(`Failed to print: ${e.message}`);
    }
    setIsPrinting(false);
  };

  return (
    <div className="w-72 bg-white dark:bg-neutral-950 border-r border-neutral-200 dark:border-neutral-800 p-6 flex flex-col gap-6 z-10 overflow-y-auto transition-colors duration-300">
      <div>
        <h1 className="text-3xl font-serif tracking-tight text-neutral-900 dark:text-white mb-1">Label Studio.</h1>
        <div className="flex gap-3 text-[10px] uppercase tracking-widest text-neutral-400 dark:text-neutral-500">
          <button onClick={() => setTheme('light')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'light' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Light</button>
          <button onClick={() => setTheme('dark')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'dark' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Dark</button>
          <button onClick={() => setTheme('auto')} className={`hover:text-neutral-900 dark:hover:text-white transition-colors ${theme === 'auto' ? 'text-neutral-900 dark:text-white font-bold' : ''}`}>Auto</button>
        </div>
      </div>
      
      <div className="space-y-3">
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Templates</h2>
        <div className="flex gap-2">
          <button 
            onClick={handleSaveTemplate} 
            className="flex-1 bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-2 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-[10px] uppercase tracking-wider font-medium"
          >
            Save As New
          </button>
          {currentTemplateId && (
            <button 
              onClick={handleUpdateTemplate} 
              className="flex-1 bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-2 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-[10px] uppercase tracking-wider font-medium"
            >
              Update Current
            </button>
          )}
        </div>
        
        {templates.length > 0 && (
          <select 
            className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs uppercase tracking-wider text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors"
            onChange={handleLoadTemplate}
            defaultValue=""
          >
            <option value="" disabled>Load a template...</option>
            {templates.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        )}
      </div>

      <div className="space-y-3">
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Tools</h2>
        <button 
          onClick={handleAddText} 
          className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left"
        >
          + Add Text
        </button>
        <button 
          onClick={handleAddBarcode} 
          className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left"
        >
          + Add Barcode
        </button>
        <label className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left cursor-pointer block">
          + Add Image
          <input type="file" accept="image/*" className="hidden" onChange={handleAddImage} />
        </label>
      </div>

      <div className="space-y-3">
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Printers</h2>
        <button 
          onClick={handleScan} 
          disabled={isScanning}
          className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium disabled:opacity-50"
        >
          {isScanning ? 'Scanning...' : 'Scan for Printers'}
        </button>
        
        {printers.length > 0 && (
          <select 
            className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs uppercase tracking-wider text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors"
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

      <div className="mt-auto pt-6">
        <button 
          onClick={handlePrint}
          disabled={isPrinting || !selectedPrinter}
          className="w-full bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 px-4 py-3 rounded-none hover:bg-neutral-800 dark:hover:bg-neutral-200 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isPrinting ? 'Printing...' : 'Test Print'}
        </button>
      </div>
    </div>
  );
}

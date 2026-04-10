import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import IconPicker from './IconPicker';
import HtmlPickerModal from './HtmlPickerModal';
import BatchPrintModal from './BatchPrintModal';
import ShippingLabelModal from './ShippingLabelModal';
import { Trash, ChevronDown, ChevronRight, LayoutTemplate } from 'lucide-react';

export default function Sidebar() {
  const { addItem, items, setItems, setCanvasSize, clearCanvas, canvasWidth, canvasHeight, canvasBorder, setCanvasBorder, selectedPrinter, setSelectedPrinter, theme, setTheme, isRotated, splitMode, applyPreset, projects } = useStore();
  const [presets, setPresets] = useState([]);
  const [printers, setPrinters] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState(null);
  const [showProjects, setShowProjects] = useState(false);
  
  const [showIconPicker, setShowIconPicker] = useState(false);
  const [iconPickerMode, setIconPickerMode] = useState('icon');
  const [showHtmlPicker, setShowHtmlPicker] = useState(false);
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [showShippingModal, setShowShippingModal] = useState(false);

  useEffect(() => {
    useStore.getState().fetchProjects();
    useStore.getState().fetchSettings(); // <-- Load DB settings
    useStore.getState().fetchAddresses();
    
    fetch('/api/presets')
      .then(res => res.json())
      .then(data => setPresets(data))
      .catch(e => console.error(e));
  }, []);

  const handleAddText = () => {
    const defaultFont = useStore.getState().settings.default_font || 'arial.ttf';
    addItem({ id: Date.now().toString(), type: 'text', text: 'Text', x: 0, y: 50, size: 24, font: defaultFont, width: canvasWidth, align: 'center' });
  };

  const handleAddHtml = (htmlContent) => {
    addItem({ id: Date.now().toString(), type: 'html', html: htmlContent, x: 0, y: 0, width: canvasWidth, height: canvasHeight });
    setShowHtmlPicker(false);
  };

  const handleAddIconText = (base64Png) => {
    const defaultFont = useStore.getState().settings.default_font || 'arial.ttf';
    addItem({
      id: Date.now().toString(), type: 'icon_text', x: 10, y: 10,
      icon_src: base64Png, icon_x: 0, icon_y: 0, icon_size: 40,
      text: 'Icon + Text', text_x: 50, text_y: 10, size: 24, font: defaultFont, text_width: 150, align: 'left',
      width: 200, height: 40
    });
    setShowIconPicker(false);
  };

  const handleAddIcon = (base64Png) => {
    if (iconPickerMode === 'icon_text') {
      handleAddIconText(base64Png);
    } else {
      addItem({ id: Date.now().toString(), type: 'image', src: base64Png, x: 0, y: 0, width: 100, height: 100 });
      setShowIconPicker(false);
    }
  };

  const handleAddBarcode = () => {
    addItem({ id: Date.now().toString(), type: 'barcode', data: '123456789', barcode_type: 'code128', x: 50, y: 100, width: 200, height: 50 });
  };

  const handleAddImage = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new window.Image();
      img.src = ev.target.result;
      img.onload = () => {
        const ratio = img.width / img.height;
        const targetWidth = Math.min(img.width, canvasWidth);
        const targetHeight = targetWidth / ratio;
        addItem({ id: Date.now().toString(), type: 'image', src: ev.target.result, x: 0, y: 0, width: targetWidth, height: targetHeight });
      };
    };
    reader.readAsDataURL(file);
    e.target.value = null;
  };

  const handleAddPdf = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
      const res = await fetch('/api/pdf/convert', {
        method: 'POST',
        body: formData
      });
      if (!res.ok) throw new Error("PDF processing failed");
      const data = await res.json();
      
      let currentY = 0;
      for (let i = 0; i < data.images.length; i++) {
        const b64 = data.images[i];
        await new Promise((resolve) => {
          const img = new window.Image();
          img.src = b64;
          img.onload = () => {
            const ratio = img.width / img.height;
            const targetWidth = Math.min(img.width, useStore.getState().canvasWidth);
            const targetHeight = targetWidth / ratio;
            useStore.getState().addItem({
              id: Date.now().toString() + "-" + i, type: 'image', src: b64,
              x: 0, y: currentY, width: targetWidth, height: targetHeight
            });
            currentY += targetHeight + 10;
            resolve();
          };
        });
      }
    } catch (err) {
      console.error(err);
      alert("Failed to process PDF file.");
    }
    e.target.value = null;
  };

  const handleScan = async () => {
    setIsScanning(true);
    try {
      const res = await fetch('/api/printers/scan');
      const data = await res.json();
      setPrinters(data.devices || []);
    } catch (e) {
      console.error(e);
      alert("Failed to scan for printers. Is the backend running on port 8000?");
    }
    setIsScanning(false);
  };

  const handleSaveProject = async () => {
    const name = prompt("Enter a name for this project:");
    if (!name) return;
    const thickness = useStore.getState().canvasBorderThickness || 4;
    
    try {
      await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          canvas_state: { width: canvasWidth, height: canvasHeight, isRotated, canvasBorder, canvasBorderThickness: thickness, splitMode, items }
        })
      });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  };

  const handleLoadProject = (proj) => {
    setCurrentProjectId(proj.id);
    setCanvasSize(proj.canvas_state.width || 384, proj.canvas_state.height || 384);
    setCanvasBorder(proj.canvas_state.canvasBorder || 'none');
    useStore.getState().setSplitMode(proj.canvas_state.splitMode || false);
    useStore.getState().setIsRotated(proj.canvas_state.isRotated || false);
    setItems(proj.canvas_state.items || []);
  };

  const handleUpdateProject = async () => {
    if (!currentProjectId) return;
    const thickness = useStore.getState().canvasBorderThickness || 4;
    try {
      await fetch(`/api/projects/${currentProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canvas_state: { width: canvasWidth, height: canvasHeight, isRotated, canvasBorder, canvasBorderThickness: thickness, splitMode, items }
        })
      });
      useStore.getState().fetchProjects();
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteProject = async (id) => {
    if (!window.confirm("Are you sure you want to delete this project?")) return;
    try {
      await fetch(`/api/projects/${id}`, { method: 'DELETE' });
      useStore.getState().fetchProjects();
      if (currentProjectId === id) setCurrentProjectId(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handlePrint = async () => {
    if (!selectedPrinter) return alert("Please select a printer first!");
    setIsPrinting(true);
    const thickness = useStore.getState().canvasBorderThickness || 4;
    try {
      const printRes = await fetch(`/api/print/direct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          mac_address: selectedPrinter, 
          canvas_state: { width: canvasWidth, height: canvasHeight, isRotated, canvasBorder, canvasBorderThickness: thickness, splitMode, items },
          variables: {} 
        })
      });
      
      if (!printRes.ok) {
        const err = await printRes.json();
        throw new Error(err.detail || "Print failed");
      }
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
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Printers</h2>
        
        {printers.length > 0 && (
          <select 
            className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs uppercase tracking-wider text-neutral-900 dark:text-white focus:outline-none focus:border-neutral-900 dark:focus:border-white transition-colors mb-2"
            value={selectedPrinter || ''}
            onChange={(e) => setSelectedPrinter(e.target.value)}
          >
            <option value="" disabled>Select a printer...</option>
            {printers.map(p => (
              <option key={p.address} value={p.address}>{p.name || p.display_address}</option>
            ))}
          </select>
        )}
        <button 
          onClick={handleScan} 
          disabled={isScanning}
          className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium disabled:opacity-50"
        >
          {isScanning ? 'Scanning...' : 'Scan for Printers'}
        </button>
      </div>

      <div className="space-y-3">
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Canvas Presets</h2>
        <select 
            className="w-full bg-neutral-50 dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 rounded-none p-2 text-xs text-neutral-900 dark:text-white focus:outline-none transition-colors mb-2"
            onChange={(e) => {
              if(e.target.value !== "") {
                const p = presets[e.target.value];
                applyPreset({ w: p.width_mm, h: p.height_mm, rotated: p.is_rotated, splitMode: p.split_mode, border: p.border });
              }
              e.target.value = "";
            }}
            defaultValue=""
          >
            <option value="" disabled>Select physical layout...</option>
            {presets.map((p, idx) => (
              <option key={idx} value={idx}>{p.name} ({p.width_mm}x{p.height_mm}mm)</option>
            ))}
        </select>
      </div>

      <div className="space-y-3">
        <div 
          className="flex items-center justify-between cursor-pointer border-b border-neutral-100 dark:border-neutral-800 pb-2 group"
          onClick={() => setShowProjects(!showProjects)}
        >
          <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest group-hover:text-neutral-900 dark:group-hover:text-white transition-colors">Saved Projects</h2>
          {showProjects ? (
            <ChevronDown size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
          ) : (
            <ChevronRight size={14} className="text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors" />
          )}
        </div>
        
        {showProjects && (
          <div className="flex flex-col gap-2 pt-1">
            <div className="flex gap-2">
              <button 
                onClick={handleSaveProject} 
                className="flex-1 bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-2 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-[10px] uppercase tracking-wider font-medium"
              >
                Save As New
              </button>
              {currentProjectId && (
                <button 
                  onClick={handleUpdateProject} 
                  className="flex-1 bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-2 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-[10px] uppercase tracking-wider font-medium"
                >
                  Update
                </button>
              )}
            </div>
            {projects.length > 0 && (
              <div className="flex flex-col gap-1 max-h-40 overflow-y-auto mt-2">
                {projects.map(p => (
                  <div key={p.id} className={`flex justify-between items-center bg-neutral-50 dark:bg-neutral-900 p-2 border ${currentProjectId === p.id ? 'border-blue-500' : 'border-neutral-200 dark:border-neutral-800'}`}>
                     <span className="text-xs cursor-pointer hover:text-blue-500 dark:text-white truncate flex-1" onClick={() => handleLoadProject(p)}>{p.name}</span>
                     <button onClick={() => handleDeleteProject(p.id)} className="text-red-500 hover:text-red-700 ml-2"><Trash size={14}/></button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="space-y-3">
        <h2 className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest border-b border-neutral-100 dark:border-neutral-800 pb-2">Tools</h2>
        
        <button onClick={() => setShowShippingModal(true)} className="w-full bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 px-4 py-2 rounded-none hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors text-xs uppercase tracking-wider font-bold text-left mb-2">
          + Shipping Label Wizard
        </button>

        <button onClick={handleAddText} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ Text</button>
        <button onClick={() => { setIconPickerMode('icon_text'); setShowIconPicker(true); }} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ Icon + Text</button>
        <button onClick={() => setShowHtmlPicker(true)} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ Custom HTML Element</button>
        <button onClick={() => { setIconPickerMode('icon'); setShowIconPicker(true); }} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ Icon Only</button>
        <button onClick={handleAddBarcode} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ Barcode</button>
        <button onClick={() => addItem({ id: Date.now().toString(), type: 'qrcode', data: 'https://example.com', x: 50, y: 100, width: 120, height: 120 })} className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left">+ QR Code</button>
        <label className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left cursor-pointer block">
          + Image
          <input type="file" accept="image/*" className="hidden" onChange={handleAddImage} />
        </label>
        <label className="w-full bg-transparent text-neutral-900 dark:text-white border border-neutral-300 dark:border-neutral-700 px-4 py-2 rounded-none hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors text-xs uppercase tracking-wider font-medium text-left cursor-pointer block">
          + PDF Document
          <input type="file" accept="application/pdf" className="hidden" onChange={handleAddPdf} />
        </label>
      </div>

      {showIconPicker && <IconPicker onClose={() => setShowIconPicker(false)} onSelect={handleAddIcon} />}
      {showHtmlPicker && <HtmlPickerModal onClose={() => setShowHtmlPicker(false)} onSelect={handleAddHtml} />}

      <div className="mt-auto pt-6 space-y-3">
        <button 
          onClick={handlePrint}
          disabled={isPrinting || !selectedPrinter}
          className="w-full bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 px-4 py-3 rounded-none hover:bg-neutral-800 dark:hover:bg-neutral-200 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isPrinting ? 'Printing...' : 'Print Label'}
        </button>

        <button 
          onClick={() => setShowBatchModal(true)} 
          className="w-full bg-transparent text-blue-600 dark:text-blue-400 border border-blue-600 dark:border-blue-400 px-4 py-3 rounded-none hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors text-xs uppercase tracking-widest font-bold"
        >
          Print Data Stream Batch
        </button>
      </div>

      {showBatchModal && <BatchPrintModal onClose={() => setShowBatchModal(false)} />}
      {showShippingModal && <ShippingLabelModal onClose={() => setShowShippingModal(false)} />}
    </div>
  );
}

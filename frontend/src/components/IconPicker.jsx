import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { icons, X, Search } from 'lucide-react';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

const ICON_NAMES = Object.keys(icons).sort();
const PAGE_SIZE = 80;

export default function IconPicker({ onClose, onSelect }) {
  const dialogRef = useDialogAccessibility(onClose);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedIcon, setSelectedIcon] = useState(null);
  const [page, setPage] = useState(0);
  const svgRef = useRef(null);

  const iconNames = ICON_NAMES.filter(name => name.toLowerCase().includes(searchTerm.toLowerCase()));
  const pageCount = Math.max(1, Math.ceil(iconNames.length / PAGE_SIZE));
  const visibleNames = iconNames.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => {
    if (!selectedIcon) return;
    
    let cancelled = false;
    const frame = requestAnimationFrame(() => {
      const svgElement = svgRef.current?.querySelector('svg');
      if (!svgElement) return;

      if (!svgElement.getAttribute('xmlns')) {
        svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      }

      // Ensure SVG is temporarily visible to calculate BBox
      svgElement.style.display = 'block';
      svgElement.style.position = 'absolute';
      svgElement.style.visibility = 'hidden';
      document.body.appendChild(svgElement);
      
      let bbox;
      try {
        bbox = svgElement.getBBox();
      } catch (_error) {
        bbox = { x: 0, y: 0, width: 24, height: 24 };
      }
      
      // Put it back
      svgRef.current.appendChild(svgElement);
      svgElement.style.display = '';
      svgElement.style.position = '';
      svgElement.style.visibility = '';

      const strokeWidth = 2; // default strokeWidth
      const pad = strokeWidth;
      
      const minX = Math.max(0, bbox.x - pad);
      const minY = Math.max(0, bbox.y - pad);
      const maxX = Math.min(24, bbox.x + bbox.width + pad);
      const maxY = Math.min(24, bbox.y + bbox.height + pad);

      const cropW = maxX - minX;
      const cropH = maxY - minY;

      svgElement.setAttribute('viewBox', `${minX} ${minY} ${cropW} ${cropH}`);
      
      const TARGET_RES = 800;
      const scale = TARGET_RES / Math.max(cropW, cropH);
      const finalW = cropW * scale;
      const finalH = cropH * scale;

      svgElement.setAttribute('width', finalW);
      svgElement.setAttribute('height', finalH);

      const svgData = new XMLSerializer().serializeToString(svgElement);
      
      const img = new Image();
      img.onload = () => {
        if (cancelled) return;
        const finalCanvas = document.createElement("canvas");
        finalCanvas.width = finalW;
        finalCanvas.height = finalH;
        const finalCtx = finalCanvas.getContext("2d");
        
        finalCtx.fillStyle = 'white';
        finalCtx.fillRect(0, 0, finalW, finalH);
        finalCtx.drawImage(img, 0, 0, finalW, finalH);
        
        onSelect(finalCanvas.toDataURL("image/png"));
      };
      img.src = "data:image/svg+xml;base64," + btoa(svgData);
    });

    return () => { cancelled = true; cancelAnimationFrame(frame); };
  }, [selectedIcon, onSelect]);

  return createPortal(
    <div className="fixed inset-0 bg-black/50 z-120 flex items-center justify-center p-4 backdrop-blur-xs">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Select icon" tabIndex={-1} className="bg-white dark:bg-neutral-900 w-full max-w-2xl rounded-xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">Select Icon</h3>
          <button onClick={onClose} aria-label="Close icon picker" className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" size={18} />
            <input 
              type="text" 
              placeholder="Search icons..." 
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
              className="w-full pl-10 pr-4 py-2 bg-neutral-50 dark:bg-neutral-950 border border-neutral-200 dark:border-neutral-800 rounded-lg text-sm focus:outline-hidden focus:border-blue-500 dark:text-white transition-colors"
            />
          </div>
        </div>

        <div className="p-4 overflow-y-auto grid grid-cols-6 sm:grid-cols-8 md:grid-cols-10 gap-4">
          {visibleNames.map((name) => {
            const IconComponent = icons[name];
            return (
              <button
                key={name}
                onClick={() => setSelectedIcon(name)}
                className="flex flex-col items-center gap-2 p-3 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors group"
                title={name}
                aria-label={name}
              >
                <IconComponent className="text-neutral-700 dark:text-neutral-300 group-hover:scale-110 transition-transform" size={24} strokeWidth={2} />
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-between gap-3 p-4 border-t border-neutral-100 dark:border-neutral-800 text-sm">
          <span role="status">{iconNames.length} icons · Page {page + 1} of {pageCount}</span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} className="px-3 py-2 rounded-sm border disabled:opacity-40">Previous</button>
            <button disabled={page + 1 >= pageCount} onClick={() => setPage(page + 1)} className="px-3 py-2 rounded-sm border disabled:opacity-40">Next</button>
          </div>
        </div>

      </div>

      {selectedIcon && (
        <div ref={svgRef} className="hidden">
          {React.createElement(icons[selectedIcon], { size: 24, color: "black", strokeWidth: 2 })}
        </div>
      )}
    </div>,
    document.body
  );
}

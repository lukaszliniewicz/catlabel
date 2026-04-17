import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import * as Icons from 'lucide-react';
import { X, Search } from 'lucide-react';

export default function IconPicker({ onClose, onSelect }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedIcon, setSelectedIcon] = useState(null);
  const svgRef = useRef(null);

  const iconNames = Object.keys(Icons).filter(name => {
    const isPascalCase = /^[A-Z]/.test(name);
    const isNotBase = name !== 'Icon' && name !== 'LucideIcon';
    const matchesSearch = name.toLowerCase().includes(searchTerm.toLowerCase());
    return isPascalCase && isNotBase && matchesSearch;
  });

  useEffect(() => {
    if (!selectedIcon) return;
    
    const timer = setTimeout(() => {
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
      } catch (e) {
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
    }, 50);

    return () => clearTimeout(timer);
  }, [selectedIcon, onSelect]);

  return createPortal(
    <div className="fixed inset-0 bg-black/50 z-[120] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-900 w-full max-w-2xl rounded-xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">Select Icon</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
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
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-neutral-50 dark:bg-neutral-950 border border-neutral-200 dark:border-neutral-800 rounded-lg text-sm focus:outline-none focus:border-blue-500 dark:text-white transition-colors"
            />
          </div>
        </div>

        <div className="p-4 overflow-y-auto grid grid-cols-6 sm:grid-cols-8 md:grid-cols-10 gap-4">
          {iconNames.map((name) => {
            const IconComponent = Icons[name];
            return (
              <button
                key={name}
                onClick={() => setSelectedIcon(name)}
                className="flex flex-col items-center gap-2 p-3 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors group"
                title={name}
              >
                <IconComponent className="text-neutral-700 dark:text-neutral-300 group-hover:scale-110 transition-transform" size={24} strokeWidth={2} />
              </button>
            );
          })}
        </div>

      </div>

      {selectedIcon && (
        <div ref={svgRef} className="hidden">
          {React.createElement(Icons[selectedIcon], { size: 24, color: "black", strokeWidth: 2 })}
        </div>
      )}
    </div>,
    document.body
  );
}

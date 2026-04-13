import React, { useState, useRef, useEffect } from 'react';
import * as Icons from 'lucide-react';
import { X, Search } from 'lucide-react';

export default function IconPicker({ onClose, onSelect }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedIcon, setSelectedIcon] = useState(null);
  const svgRef = useRef(null);

  // Safely filter valid icons: 
  // 1. Must be PascalCase (standard for React components) to filter out 'createLucideIcon'
  // 2. Must exclude the base 'Icon' and 'LucideIcon' classes
  // 3. Must match the search term
  const iconNames = Object.keys(Icons).filter(name => {
    const isPascalCase = /^[A-Z]/.test(name);
    const isNotBase = name !== 'Icon' && name !== 'LucideIcon';
    const matchesSearch = name.toLowerCase().includes(searchTerm.toLowerCase());
    return isPascalCase && isNotBase && matchesSearch;
  });

  // When 'selectedIcon' state changes, React renders the hidden SVG.
  // This effect intercepts it, auto-crops the invisible padding, and generates the Base64 PNG.
  useEffect(() => {
    if (!selectedIcon) return;
    
    const timer = setTimeout(() => {
      const svgElement = svgRef.current?.querySelector('svg');
      if (!svgElement) return;

      if (!svgElement.getAttribute('xmlns')) {
        svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      }

      const svgData = new XMLSerializer().serializeToString(svgElement);
      const CANVAS_SIZE = 800; // Increased resolution for sharp scaling
      const tempCanvas = document.createElement("canvas");
      tempCanvas.width = CANVAS_SIZE;
      tempCanvas.height = CANVAS_SIZE;
      const tempCtx = tempCanvas.getContext("2d");
      if (!tempCtx) return;
      
      const img = new Image();
      img.onload = () => {
        // Draw WITHOUT a background to accurately read the alpha transparency
        tempCtx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
        tempCtx.drawImage(img, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
        const imgData = tempCtx.getImageData(0, 0, CANVAS_SIZE, CANVAS_SIZE);
        const data = imgData.data;
        
        let minX = CANVAS_SIZE, minY = CANVAS_SIZE, maxX = 0, maxY = 0;
        let hasInk = false;

        // Scan pixels to find exact tight icon boundaries
        for (let y = 0; y < CANVAS_SIZE; y++) {
            for (let x = 0; x < CANVAS_SIZE; x++) {
                const alpha = data[(y * CANVAS_SIZE + x) * 4 + 3];
                if (alpha > 5) { // True ink found
                    hasInk = true;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }

        if (hasInk) {
           minX = Math.max(0, minX - 1);
           minY = Math.max(0, minY - 1);
           maxX = Math.min(CANVAS_SIZE, maxX + 1);
           maxY = Math.min(CANVAS_SIZE, maxY + 1);
        } else {
           minX = 0; minY = 0; maxX = CANVAS_SIZE; maxY = CANVAS_SIZE;
        }

        const cropW = maxX - minX;
        const cropH = maxY - minY;

        // Now draw the cropped icon onto a solid white canvas for the printer
        const finalCanvas = document.createElement("canvas");
        finalCanvas.width = cropW;
        finalCanvas.height = cropH;
        const finalCtx = finalCanvas.getContext("2d");
        if (!finalCtx) return;
        
        finalCtx.fillStyle = 'white';
        finalCtx.fillRect(0, 0, cropW, cropH);
        finalCtx.drawImage(tempCanvas, minX, minY, cropW, cropH, 0, 0, cropW, cropH);
        
        onSelect(finalCanvas.toDataURL("image/png"));
      };
      img.src = "data:image/svg+xml;base64," + btoa(svgData);
    }, 50);

    return () => clearTimeout(timer);
  }, [selectedIcon, onSelect]);

  return (
    <div className="fixed inset-0 bg-black/50 z-[110] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-900 w-full max-w-2xl rounded-xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden border border-neutral-200 dark:border-neutral-800">
        
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">Select Icon</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Search */}
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

        {/* Grid */}
        <div className="p-4 overflow-y-auto grid grid-cols-6 sm:grid-cols-8 md:grid-cols-10 gap-4">
          {iconNames.map((name) => {
            const IconComponent = Icons[name];
            return (
              <button
                key={name}
                // Just update state on click. The useEffect handles the conversion logic.
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

      {/* 
        Single, safe hidden render target for serialization.
        Because this is outside the .map() loop, the 'ref' behaves reliably.
      */}
      {selectedIcon && (
        <div ref={svgRef} className="hidden">
          {React.createElement(Icons[selectedIcon], { size: 800, color: "black", strokeWidth: 2 })}
        </div>
      )}
    </div>
  );
}

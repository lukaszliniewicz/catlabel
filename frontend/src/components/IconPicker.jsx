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
  // This effect intercepts it, draws it to an offscreen canvas, and generates the Base64 PNG.
  useEffect(() => {
    if (!selectedIcon) return;
    
    // Wait a brief tick (50ms) to ensure React has flushed the hidden SVG to the DOM
    const timer = setTimeout(() => {
      const svgElement = svgRef.current?.querySelector('svg');
      if (!svgElement) return;

      // Ensure XML namespace exists for canvas serialization
      if (!svgElement.getAttribute('xmlns')) {
        svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      }

      const svgData = new XMLSerializer().serializeToString(svgElement);
      const canvas = document.createElement("canvas");
      
      // Render at a high resolution (200x200) for crisp thermal printing
      canvas.width = 200;
      canvas.height = 200;
      const ctx = canvas.getContext("2d");
      
      const img = new Image();
      img.onload = () => {
        // Fill white background to guarantee cleanly printed boundaries
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, 200, 200);
        
        ctx.drawImage(img, 0, 0, 200, 200);
        const base64Png = canvas.toDataURL("image/png");
        
        onSelect(base64Png);
      };
      img.src = "data:image/svg+xml;base64," + btoa(svgData);
    }, 50);

    return () => clearTimeout(timer);
  }, [selectedIcon, onSelect]);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
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
          {React.createElement(Icons[selectedIcon], { size: 200, color: "black", strokeWidth: 2 })}
        </div>
      )}
    </div>
  );
}

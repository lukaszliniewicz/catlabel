import React, { useState, useRef } from 'react';
import * as Icons from 'lucide-react';
import { X, Search } from 'lucide-react';

export default function IconPicker({ onClose, onSelect }) {
  const [searchTerm, setSearchTerm] = useState('');
  const svgRef = useRef(null);

  // Filter valid icons based on search
  const iconNames = Object.keys(Icons).filter(name => 
    name !== 'createReactComponent' && 
    name !== 'default' &&
    name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleSelectIcon = async (IconComponent) => {
    // Render the component temporarily into our hidden ref
    const svgElement = svgRef.current.querySelector('svg');
    if (!svgElement) return;

    // Ensure XML namespace exists for canvas serialization
    if (!svgElement.getAttribute('xmlns')) {
      svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    }

    const svgData = new XMLSerializer().serializeToString(svgElement);
    const canvas = document.createElement("canvas");
    
    // Render at a high resolution (200x200) for sharp thermal printing
    canvas.width = 200;
    canvas.height = 200;
    const ctx = canvas.getContext("2d");
    
    const img = new Image();
    img.onload = () => {
      // Draw white background (optional, but good for thermal)
      ctx.fillStyle = 'white';
      ctx.fillRect(0, 0, 200, 200);
      
      ctx.drawImage(img, 0, 0, 200, 200);
      const base64Png = canvas.toDataURL("image/png");
      onSelect(base64Png);
    };
    img.src = "data:image/svg+xml;base64," + btoa(svgData);
  };

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
                onClick={() => handleSelectIcon(IconComponent)}
                className="flex flex-col items-center gap-2 p-3 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors group relative"
                title={name}
              >
                {/* Visible UI Icon */}
                <IconComponent className="text-neutral-700 dark:text-neutral-300 group-hover:scale-110 transition-transform" size={24} strokeWidth={2} />
                
                {/* Hidden Render Target for Serialization (Absolute Black for thermal printer) */}
                <div ref={svgRef} className="hidden">
                  <IconComponent size={200} strokeWidth={2} color="black" />
                </div>
              </button>
            );
          })}
        </div>

      </div>
    </div>
  );
}

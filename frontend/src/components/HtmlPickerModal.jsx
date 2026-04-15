import React, { useState } from 'react';
import { X, Code } from 'lucide-react';

export default function HtmlPickerModal({ onClose, onSelect }) {
  const [content, setContent] = useState(
    `<div style="display:flex; flex-direction:column; width:100%; height:100%; text-align:center;">\n  <div style="flex:1; min-width:0; min-height:0; overflow:hidden;">\n    <div class="auto-text">\n      <h1>HELLO WORLD</h1>\n    </div>\n  </div>\n  <div style="flex:1; min-width:0; min-height:0; overflow:hidden;">\n    <div class="auto-text">\n      <p>Custom HTML</p>\n    </div>\n  </div>\n</div>`
  );

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-900 w-full max-w-2xl rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <Code className="text-blue-500" size={20} />
            <h3 className="font-serif text-lg dark:text-white">Create HTML Element</h3>
          </div>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 flex flex-col gap-4">
          <div>
            <label className="block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-2">HTML Content (with inline styles)</label>
            <textarea 
              value={content} 
              onChange={e => setContent(e.target.value)}
              rows={12}
              className="w-full bg-neutral-50 dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-3 text-sm dark:text-white focus:outline-none focus:border-blue-500 font-mono" 
              placeholder="<div>...</div>"
            />
            <p className="text-[10px] text-neutral-500 mt-2">
              Tip: Wrap semantic tags (like h1, p) in an <strong>auto-text</strong> container. Do not set font-sizes! The system will calculate it automatically based on the boundaries of the parent element.
            </p>
          </div>
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800 mt-auto">
          <button 
            onClick={() => onSelect(content)}
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold"
          >
            Add To Canvas
          </button>
        </div>

      </div>
    </div>
  );
}

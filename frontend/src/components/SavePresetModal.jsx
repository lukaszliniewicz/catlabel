import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, LayoutTemplate } from 'lucide-react';
import { useStore } from '../store';

export default function SavePresetModal({ onClose }) {
  const { savePreset, selectedPrinterInfo } = useStore();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  // Auto-fill media type based on the currently selected printer
  const defaultMedia = selectedPrinterInfo?.media_type || 'any';
  const [mediaType, setMediaType] = useState(defaultMedia);

  const handleSave = () => {
    if (!name.trim()) return;
    savePreset({
      name: name.trim(),
      description: description.trim(),
      media_type: mediaType
    });
    onClose();
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors mb-4";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1";

  const modalContent = (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-sm rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">

        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <LayoutTemplate className="text-blue-500" size={20} />
            <h3 className="font-serif text-lg dark:text-white">Save Preset</h3>
          </div>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6">
          <label className={labelClass}>Preset Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. My Custom Spice Jar"
            className={inputClass}
            autoFocus
          />

          <label className={labelClass}>AI Hint / Description (Optional)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Instructs the AI on when to use this preset..."
            className={inputClass}
            rows={3}
          />

          <label className={labelClass}>Media Type (Hardware Intent)</label>
          <select
            value={mediaType}
            onChange={(e) => setMediaType(e.target.value)}
            className={inputClass}
          >
            <option value="continuous">Continuous Roll (Generic Printers)</option>
            <option value="pre-cut">Pre-cut Labels (Niimbot D/B Series)</option>
            <option value="any">Universal / Any</option>
          </select>
          <p className="text-[10px] text-neutral-500 leading-relaxed -mt-2">
            This prevents the AI from attempting to print a pre-cut layout onto a continuous roll sideways.
          </p>
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800">
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold flex justify-center items-center gap-2 disabled:opacity-50"
          >
            <Save size={16} /> Save Canvas Preset
          </button>
        </div>

      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}

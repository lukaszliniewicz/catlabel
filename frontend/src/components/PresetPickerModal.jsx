import React from 'react';
import { createPortal } from 'react-dom';
import { X, LayoutTemplate } from 'lucide-react';
import { useStore } from '../store';

export default function PresetPickerModal({ onClose }) {
  const { labelPresets, applyPreset, selectedPrinterInfo } = useStore();
  const activePreset = useStore((state) => state.getActivePreset());

  const continuousPresets = labelPresets.filter((p) => p.media_type === 'continuous');
  const precutPresets = labelPresets.filter((p) => p.media_type === 'pre-cut');
  const universalPresets = labelPresets.filter((p) => p.media_type !== 'continuous' && p.media_type !== 'pre-cut');

  const isConflict = (mediaType) => {
    if (selectedPrinterInfo?.media_type === 'pre-cut' && mediaType === 'continuous') return true;
    if (selectedPrinterInfo?.media_type === 'continuous' && mediaType === 'pre-cut') return true;
    return false;
  };

  const PresetCard = ({ p }) => {
    const disabled = isConflict(p.media_type);
    const isActive = activePreset?.id === p.id;

    const w = p.is_rotated ? p.height_mm : p.width_mm;
    const h = p.is_rotated ? p.width_mm : p.height_mm;
    const maxDim = Math.max(w, h);
    const scale = 50 / maxDim;
    const displayW = w * scale;
    const displayH = h * scale;

    return (
      <button
        onClick={() => {
          if (!disabled) {
            applyPreset(p);
            onClose();
          }
        }}
        disabled={disabled}
        className={`flex flex-col items-center p-3 rounded-lg border text-left transition-all ${
          isActive
            ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 shadow-sm ring-1 ring-blue-500'
            : disabled
              ? 'opacity-40 cursor-not-allowed border-neutral-200 dark:border-neutral-800'
              : 'border-neutral-200 dark:border-neutral-800 hover:border-blue-300 dark:hover:border-blue-700 hover:bg-neutral-50 dark:hover:bg-neutral-800/50 cursor-pointer'
        }`}
        title={disabled ? 'Incompatible with current printer media type' : p.description || p.name}
      >
        <div className="h-16 w-full flex items-center justify-center mb-3 bg-neutral-100 dark:bg-neutral-900 rounded border border-neutral-200 dark:border-neutral-800 overflow-hidden">
          <div
            style={{ width: displayW, height: displayH }}
            className="bg-white border border-neutral-300 shadow-sm relative flex items-center justify-center overflow-hidden"
          >
            {p.split_mode && (
              <div className="absolute inset-0 flex flex-col justify-evenly">
                <div className="border-b border-red-400 border-dashed w-full h-0"></div>
              </div>
            )}
            {p.border === 'box' && (
              <div className="absolute inset-0 border border-black"></div>
            )}
            {p.border === 'top' && (
              <div className="absolute top-0 left-0 right-0 border-t border-black"></div>
            )}
            {p.border === 'bottom' && (
              <div className="absolute bottom-0 left-0 right-0 border-b border-black"></div>
            )}
            {p.border === 'cut_line' && (
              <div className="absolute bottom-0 left-0 right-0 border-b border-black border-dashed"></div>
            )}
          </div>
        </div>
        <div className="w-full text-center">
          <div className="text-xs font-bold dark:text-white truncate w-full" title={p.name}>{p.name}</div>
          <div className="text-[10px] text-neutral-500 mt-1">{p.width_mm} × {p.height_mm} mm</div>
        </div>
      </button>
    );
  };

  const Section = ({ title, presets }) => {
    if (presets.length === 0) return null;
    return (
      <div className="mb-6">
        <h4 className="text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-3 pb-1 border-b border-neutral-100 dark:border-neutral-800">
          {title}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {presets.map((p) => <PresetCard key={p.id} p={p} />)}
        </div>
      </div>
    );
  };

  return createPortal(
    <div className="fixed inset-0 bg-black/50 z-[105] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-3xl rounded-xl shadow-2xl flex flex-col max-h-[85vh] border border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800 shrink-0">
          <div className="flex items-center gap-2">
            <LayoutTemplate className="text-blue-500" size={20} />
            <h3 className="font-serif text-lg dark:text-white">Canvas Presets</h3>
          </div>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1">
          <Section title="Continuous Roll Labels" presets={continuousPresets} />
          <Section title="Pre-cut Labels (Niimbot)" presets={precutPresets} />
          <Section title="Universal / Other" presets={universalPresets} />
        </div>
      </div>
    </div>,
    document.body
  );
}

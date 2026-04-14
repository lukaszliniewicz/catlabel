import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Wand2, Database, AlertTriangle, LayoutTemplate } from 'lucide-react';
import { useStore } from '../store';
import { calculateAutoFitItem } from '../utils/rendering';
import IconPicker from './IconPicker';

export default function TemplateWizardModal({ template, onClose }) {
  const {
    canvasWidth, canvasHeight, setItems, clearCanvas,
    labelPresets, applyPreset, isRotated, getMmToPx, selectedPrinterInfo
  } = useStore();
  const [formData, setFormData] = useState({});
  const [batchMode, setBatchMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pickerField, setPickerField] = useState(null);

  useEffect(() => {
    const initialData = {};
    (template.fields || []).forEach((field) => {
      let defaultVal = field.default || '';
      if (field.type === 'select' && field.options?.length > 0) {
        defaultVal = field.default || (field.options[0].value || field.options[0]);
      }
      initialData[field.name] = batchMode && field.type === 'text' ? `{{ ${field.name} }}` : defaultVal;
    });
    setFormData(initialData);
  }, [template, batchMode]);

  // Auto-detect the currently active preset to pre-fill the dropdown
  const activePreset = labelPresets.find((p) => {
    const presetWidthPx = getMmToPx(p.width_mm);
    const presetHeightPx = getMmToPx(p.height_mm);
    const directMatch = presetWidthPx === canvasWidth && presetHeightPx === canvasHeight;
    const swappedMatch = presetWidthPx === canvasHeight && presetHeightPx === canvasWidth;

    return p.is_rotated === isRotated && (directMatch || swappedMatch);
  });

  // Intelligent warning if the canvas is too small for data-heavy templates
  const isSmallLabel = canvasWidth < 250 || canvasHeight < 250;
  const needsSpace = ['shipping_address', 'price_tag'].includes(template.id);
  const showSizeWarning = isSmallLabel && needsSpace;

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/templates/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: template.id,
          width: canvasWidth,
          height: canvasHeight,
          params: formData
        })
      });

      if (!res.ok) {
        throw new Error('Failed to generate layout');
      }

      const data = await res.json();
      const optimizedItems = (data.items || []).map((item) =>
        calculateAutoFitItem(item, useStore.getState().batchRecords, canvasWidth, canvasHeight)
      );

      clearCanvas();
      setItems(optimizedItems);
      onClose();
    } catch (err) {
      console.error(err);
      alert('Failed to generate template.');
    } finally {
      setLoading(false);
    }
  };

  const inputClass = 'w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 mb-3 transition-colors';
  const labelClass = 'block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1';

  const modalContent = (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-md rounded-xl shadow-2xl flex flex-col max-h-[90vh] border border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <Wand2 className="text-blue-500" size={20} />
            <h3 className="font-serif text-xl dark:text-white tracking-tight">{template.name}</h3>
          </div>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="bg-neutral-50 dark:bg-neutral-900/50 p-5 border-b border-neutral-100 dark:border-neutral-800">
          <label className="flex items-center gap-2 text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-2">
            <LayoutTemplate size={14} /> Target Label Size
          </label>
          <select
            value={activePreset ? activePreset.id : ''}
            onChange={(e) => {
              if (e.target.value) {
                const preset = labelPresets.find((p) => p.id === parseInt(e.target.value, 10));
                if (preset) applyPreset(preset);
              }
            }}
            className="w-full bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-2.5 text-sm font-medium dark:text-white focus:outline-none focus:border-blue-500 transition-colors"
          >
            <option value="" disabled>Custom Size (Unsaved)</option>
            <optgroup label="Continuous Roll Labels">
              {labelPresets.filter((p) => p.media_type === 'continuous').map((p) => (
                <option key={p.id} value={p.id} disabled={selectedPrinterInfo?.media_type === 'pre-cut'}>
                  {selectedPrinterInfo?.media_type === 'pre-cut' ? '🚫 ' : ''}{p.name} ({p.width_mm}x{p.height_mm}mm)
                </option>
              ))}
            </optgroup>
            <optgroup label="Pre-cut Labels (Niimbot)">
              {labelPresets.filter((p) => p.media_type === 'pre-cut').map((p) => (
                <option key={p.id} value={p.id} disabled={selectedPrinterInfo?.media_type === 'continuous'}>
                  {selectedPrinterInfo?.media_type === 'continuous' ? '🚫 ' : ''}{p.name} ({p.width_mm}x{p.height_mm}mm)
                </option>
              ))}
            </optgroup>
            {labelPresets.filter((p) => p.media_type === 'any').length > 0 && (
              <optgroup label="Universal">
                {labelPresets.filter((p) => p.media_type === 'any').map((p) => (
                  <option key={p.id} value={p.id}>{p.name} ({p.width_mm}x{p.height_mm}mm)</option>
                ))}
              </optgroup>
            )}
          </select>

          {showSizeWarning && (
            <div className="mt-3 flex gap-2 text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 p-3 rounded border border-amber-200 dark:border-amber-900/50 text-xs leading-relaxed">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <p>This template is designed for larger labels. It may look cramped on your currently selected canvas size.</p>
            </div>
          )}
        </div>

        <div className="p-6 overflow-y-auto flex-1 flex flex-col">
          <p className="text-xs text-neutral-500 mb-4">{template.description}</p>

          <div className="flex items-center gap-2 p-3 mb-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded">
            <Database size={16} className="text-blue-500" />
            <label className="flex-1 flex items-center justify-between cursor-pointer text-xs font-bold text-blue-700 dark:text-blue-400 uppercase tracking-widest">
              Setup for Batch Print?
              <input
                type="checkbox"
                checked={batchMode}
                onChange={(e) => setBatchMode(e.target.checked)}
                className="w-4 h-4 accent-blue-600"
              />
            </label>
          </div>

          {(template.fields || []).map((field) => (
            <div key={field.name}>
              <label className={labelClass}>{field.label}</label>
              {field.type === 'textarea' ? (
                <textarea
                  value={formData[field.name] || ''}
                  onChange={(e) => setFormData({ ...formData, [field.name]: e.target.value })}
                  className={inputClass}
                  rows={4}
                />
              ) : field.type === 'select' ? (
                <select
                  value={formData[field.name] || ''}
                  onChange={(e) => setFormData({ ...formData, [field.name]: e.target.value })}
                  className={inputClass}
                >
                  {field.options.map((option) => (
                    <option key={option.value || option} value={option.value || option}>
                      {option.label || option}
                    </option>
                  ))}
                </select>
              ) : field.type === 'icon' ? (
                <div className="flex items-center gap-3 mb-3">
                  {formData[field.name] ? (
                    <img
                      src={formData[field.name]}
                      alt="Icon"
                      className="w-10 h-10 object-contain bg-white border border-neutral-300 dark:border-neutral-700 p-1 rounded"
                    />
                  ) : (
                    <div className="w-10 h-10 bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded flex items-center justify-center text-[10px] text-neutral-400">
                      None
                    </div>
                  )}
                  <button
                    onClick={() => setPickerField(field.name)}
                    className="px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 text-xs font-bold uppercase tracking-wider hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors dark:text-white rounded"
                  >
                    Choose Icon
                  </button>
                </div>
              ) : (
                <input
                  type="text"
                  value={formData[field.name] || ''}
                  onChange={(e) => setFormData({ ...formData, [field.name]: e.target.value })}
                  className={inputClass}
                />
              )}
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800 mt-auto">
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold flex justify-center items-center gap-2 disabled:opacity-50"
          >
            {loading ? 'Generating...' : 'Generate Layout'}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {createPortal(modalContent, document.body)}
      {pickerField && (
        <IconPicker
          onClose={() => setPickerField(null)}
          onSelect={(b64) => {
            setFormData((prev) => ({ ...prev, [pickerField]: b64 }));
            setPickerField(null);
          }}
        />
      )}
    </>
  );
}

import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Wand2, Database, AlertTriangle, LayoutTemplate, ChevronDown } from 'lucide-react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';
import IconPicker from './IconPicker';
import PresetPickerModal from './PresetPickerModal';

function initialTemplateData(template, batchMode) {
  const initialData = {};
  (template.fields || []).forEach((field) => {
    let defaultVal = field.default || '';
    if (field.type === 'select' && field.options?.length > 0) {
      defaultVal = field.default || (field.options[0].value || field.options[0]);
    }
    if (field.type === 'boolean') {
      initialData[field.name] = defaultVal === true || defaultVal === 'true';
    } else {
      initialData[field.name] = batchMode && (field.type === 'text' || field.type === 'textarea')
        ? `{{ ${field.name} }}`
        : defaultVal;
    }
  });
  return initialData;
}

export default function TemplateWizardModal({ template, onClose }) {
  return <TemplateWizard key={template.id} template={template} onClose={onClose} />;
}

function TemplateWizard({ template, onClose }) {
  const dialogRef = useDialogAccessibility(onClose);
  const {
    canvasWidth, canvasHeight, setTemplateConfig, clearCanvas
  } = useStore(useShallow((state) => ({
    canvasWidth: state.canvasWidth, canvasHeight: state.canvasHeight,
    setTemplateConfig: state.setTemplateConfig, clearCanvas: state.clearCanvas
  })));
  const [formData, setFormData] = useState(() => initialTemplateData(template, false));
  const [batchMode, setBatchMode] = useState(false);
  const [pickerField, setPickerField] = useState(null);
  const [showPresetPicker, setShowPresetPicker] = useState(false);
  const activePreset = useStore((state) => state.getActivePreset());



  const isSmallLabel = canvasWidth < 250 || canvasHeight < 250;
  const needsSpace = ['shipping_address', 'price_tag'].includes(template.id);
  const showSizeWarning = isSmallLabel && needsSpace;

  const handleGenerate = () => {
    clearCanvas();
    setTemplateConfig(template.id, formData);
    onClose();
  };

  const inputClass = 'w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-hidden focus:border-blue-500 mb-3 transition-colors';
  const labelClass = 'block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1';

  const modalContent = (
    <div className="fixed inset-0 bg-black/50 z-100 flex items-center justify-center p-4 backdrop-blur-xs">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={`${template.name} template wizard`} tabIndex={-1} className="bg-white dark:bg-neutral-950 w-full max-w-md rounded-xl shadow-2xl flex flex-col max-h-[90vh] border border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <Wand2 className="text-blue-500" size={20} />
            <h3 className="font-serif text-xl dark:text-white tracking-tight">{template.name}</h3>
          </div>
          <button onClick={onClose} aria-label="Close template wizard" className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="bg-neutral-50 dark:bg-neutral-900/50 p-5 border-b border-neutral-100 dark:border-neutral-800">
          <label className="flex items-center gap-2 text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-2">
            <LayoutTemplate size={14} /> Target Label Size
          </label>
          <button
            onClick={() => setShowPresetPicker(true)}
            className="w-full flex items-center justify-between bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-2.5 text-sm font-medium dark:text-white hover:border-blue-500 transition-colors"
          >
            <span className="truncate pr-2">
              {activePreset ? `${activePreset.name} (${activePreset.width_mm}x${activePreset.height_mm}mm)` : 'Custom Size (Unsaved)'}
            </span>
            <ChevronDown size={16} className="text-neutral-500 shrink-0" />
          </button>

          {showSizeWarning && (
            <div className="mt-3 flex gap-2 text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 p-3 rounded-sm border border-amber-200 dark:border-amber-900/50 text-xs leading-relaxed">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <p>This template is designed for larger labels. It may look cramped on your currently selected canvas size.</p>
            </div>
          )}
        </div>

        <div className="p-6 overflow-y-auto flex-1 flex flex-col">
          <p className="text-xs text-neutral-500 mb-4">{template.description}</p>

          <div className="flex items-center gap-2 p-3 mb-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-sm">
            <Database size={16} className="text-blue-500" />
            <label className="flex-1 flex items-center justify-between cursor-pointer text-xs font-bold text-blue-700 dark:text-blue-400 uppercase tracking-widest">
              Setup for Batch Print?
              <input
                type="checkbox"
                checked={batchMode}
                onChange={(e) => {
                  setBatchMode(e.target.checked);
                  setFormData(initialTemplateData(template, e.target.checked));
                }}
                className="w-4 h-4 accent-blue-600"
              />
            </label>
          </div>

          {(template.fields || []).map((field) => (
            <div key={field.name}>
              {field.type !== 'boolean' && <label className={labelClass}>{field.label}</label>}
              
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
                  {field.options?.map((option) => (
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
                      className="w-10 h-10 object-contain bg-white border border-neutral-300 dark:border-neutral-700 p-1 rounded-sm"
                    />
                  ) : (
                    <div className="w-10 h-10 bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded-sm flex items-center justify-center text-[10px] text-neutral-400">
                      None
                    </div>
                  )}
                  <button
                    onClick={() => setPickerField(field.name)}
                    className="px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 text-xs font-bold uppercase tracking-wider hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors dark:text-white rounded-sm"
                  >
                    Choose Icon
                  </button>
                </div>
              ) : field.type === 'boolean' ? (
                <label className="flex items-center gap-2 text-sm dark:text-neutral-200 cursor-pointer mb-3 bg-neutral-50 dark:bg-neutral-900/30 p-2 border border-neutral-200 dark:border-neutral-800 rounded-sm transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-800/50">
                  <input
                    type="checkbox"
                    checked={!!formData[field.name]}
                    onChange={(e) => setFormData({ ...formData, [field.name]: e.target.checked })}
                    className="w-4 h-4 accent-blue-600"
                  />
                  {field.label}
                </label>
              ) : (
                <input
                  type={batchMode && field.type === 'date' ? 'text' : (field.type || 'text')}
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
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold"
          >
            Generate Layout
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
      {showPresetPicker && (
        <PresetPickerModal onClose={() => setShowPresetPicker(false)} />
      )}
    </>
  );
}

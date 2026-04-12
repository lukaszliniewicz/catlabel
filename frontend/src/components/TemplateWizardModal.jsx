import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Wand2, Database } from 'lucide-react';
import { useStore } from '../store';

export default function TemplateWizardModal({ template, onClose }) {
  const { canvasWidth, canvasHeight, setItems, clearCanvas } = useStore();
  const [formData, setFormData] = useState({});
  const [batchMode, setBatchMode] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const initialData = {};
    (template.fields || []).forEach((field) => {
      initialData[field.name] = batchMode ? `{{ ${field.name} }}` : (field.default || '');
    });
    setFormData(initialData);
  }, [template, batchMode]);

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
      clearCanvas();
      setItems(data.items || []);
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

  return createPortal(modalContent, document.body);
}

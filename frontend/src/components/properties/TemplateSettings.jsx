import React, { useId } from 'react';
import { TEMPLATE_METADATA } from '../../domain/templates';
import { inputClass, labelClass } from './styles';

export default function TemplateSettings({ layout, onEject, onChangeParams, onPickIcon, onFormat, onChangeHtml }) {
  const tabId = useId();
  const { activeTemplate, htmlContent } = layout;
  return (
    <div className="space-y-4 h-full flex flex-col">
      {activeTemplate ? (
        <>
          <div className="flex items-center justify-between pb-2 border-b border-neutral-100 dark:border-neutral-800">
            <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white">Template Settings</h2>
            <button onClick={onEject} className="text-[10px] text-amber-600 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400 px-2 py-1 rounded-sm font-bold uppercase hover:bg-amber-100 transition-colors">
              Eject to Custom HTML
            </button>
          </div>

          <div className="space-y-3 overflow-y-auto pr-2 pb-2">
            {(() => {
              const meta = TEMPLATE_METADATA.find((t) => t.id === activeTemplate.id) || TEMPLATE_METADATA[0];
              return meta.fields.map((field) => {
                const value = activeTemplate.params[field.name] ?? field.default ?? '';
                const handleParamChange = (val) => onChangeParams({ [field.name]: val });

                if (field.type === 'icon') {
                  return (
                    <div key={field.name}>
                      <label className={labelClass} htmlFor={`${tabId}-template-${field.name}`}>{field.label}</label>
                      <div className="flex items-center gap-3 mb-3">
                        {value ? (
                          <img
                            src={value}
                            alt={field.label}
                            className="w-10 h-10 object-contain bg-white border border-neutral-300 dark:border-neutral-700 p-1 rounded-sm"
                          />
                        ) : (
                          <div className="w-10 h-10 bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded-sm flex items-center justify-center text-[10px] text-neutral-600 dark:text-neutral-300">
                            None
                          </div>
                        )}
                        <button id={`${tabId}-template-${field.name}`} aria-label={`Choose ${field.label}`}
                          onClick={() => onPickIcon(field.name)}
                          className="px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 text-xs font-bold uppercase tracking-wider hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors dark:text-white rounded-sm"
                        >
                          Choose Icon
                        </button>
                      </div>
                    </div>
                  );
                }

                if (field.type === 'textarea') {
                  return (
                    <div key={field.name}>
                      <label className={labelClass} htmlFor={`${tabId}-template-${field.name}`}>{field.label}</label>
                      <textarea
                        id={`${tabId}-template-${field.name}`} value={value}
                        onChange={(e) => handleParamChange(e.target.value)}
                        className={inputClass}
                        rows={3}
                      />
                    </div>
                  );
                }

                if (field.type === 'select') {
                  return (
                    <div key={field.name}>
                      <label className={labelClass} htmlFor={`${tabId}-template-${field.name}`}>{field.label}</label>
                      <select
                        id={`${tabId}-template-${field.name}`} value={value}
                        onChange={(e) => handleParamChange(e.target.value)}
                        className={inputClass}
                      >
                        {(field.options || []).map((option) => (
                          <option key={option.value || option} value={option.value || option}>
                            {option.label || option}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                }

                return (
                  <div key={field.name}>
                    <label className={labelClass} htmlFor={`${tabId}-template-${field.name}`}>{field.label}</label>
                    <input
                      id={`${tabId}-template-${field.name}`} type="text"
                      value={value}
                      onChange={(e) => handleParamChange(e.target.value)}
                      className={inputClass}
                    />
                  </div>
                );
              });
            })()}
          </div>

          <div className="mt-auto pt-4 border-t border-neutral-100 dark:border-neutral-800">
            <label className={labelClass} htmlFor={`${tabId}-generated-html`}>Generated HTML (Read-Only)</label>
            <textarea id={`${tabId}-generated-html`} value={htmlContent} readOnly className={`${inputClass} opacity-70 bg-neutral-100 dark:bg-neutral-900 cursor-not-allowed`} rows={6} />
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center justify-between pb-2 border-b border-neutral-100 dark:border-neutral-800">
            <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white">Background Layout (HTML)</h2>
            <button onClick={() => onFormat()} className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded-sm font-bold uppercase hover:bg-blue-100 transition-colors">
              Auto-Format
            </button>
          </div>
          <p className="text-[11px] text-neutral-600 dark:text-neutral-300">
            Wrap text in <code>&lt;div class=&quot;auto-text&quot;&gt;</code> to automatically scale it to fit the container.
          </p>
          <textarea aria-label="Background layout HTML"
            value={htmlContent}
            onChange={(e) => onChangeHtml(e.target.value)}
            className="w-full flex-1 bg-neutral-50 dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-3 text-sm font-mono dark:text-white focus:outline-hidden focus:border-blue-500"
            placeholder="<div class='auto-text'>Hello World</div>"
          />
        </>
      )}
    </div>
  );
}

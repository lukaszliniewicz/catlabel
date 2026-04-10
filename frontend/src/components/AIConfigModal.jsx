import React, { useState, useEffect } from 'react';
import { X, Save } from 'lucide-react';

export default function AIConfigModal({ onClose }) {
  const [config, setConfig] = useState({
    provider: 'openai', model_name: 'gpt-4o', api_key: '', base_url: '', use_env: false
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch('/api/ai/config').then(res => res.json()).then(data => setConfig(data));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    await fetch('/api/ai/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    setSaving(false);
    onClose();
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1 mt-3";

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-md rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">AI Assistant Settings</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>
        
        <div className="p-6 overflow-y-auto">
          <label className={labelClass}>Provider</label>
          <select value={config.provider} onChange={e => setConfig({...config, provider: e.target.value})} className={inputClass}>
            <option value="openai">OpenAI</option>
            <option value="gemini">Google Gemini</option>
            <option value="vertex_ai">Google Vertex AI</option>
            <option value="custom">Custom (OpenAI Compatible)</option>
          </select>

          <label className={labelClass}>Model Name</label>
          <input type="text" value={config.model_name} onChange={e => setConfig({...config, model_name: e.target.value})} className={inputClass} placeholder="e.g. gpt-4o, gemini-1.5-pro" />

          <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer mt-4 mb-2">
            <input type="checkbox" checked={config.use_env} onChange={e => setConfig({...config, use_env: e.target.checked})} /> 
            Use Server Environment Variables (Ignore Key below)
          </label>

          {!config.use_env && (
            <>
              <label className={labelClass}>{config.provider === 'vertex_ai' ? 'Service Account JSON' : 'API Key'}</label>
              {config.provider === 'vertex_ai' ? (
                 <textarea value={config.api_key} onChange={e => setConfig({...config, api_key: e.target.value})} className={inputClass} rows={4} placeholder='{"type": "service_account", ...}' />
              ) : (
                 <input type="password" value={config.api_key} onChange={e => setConfig({...config, api_key: e.target.value})} className={inputClass} placeholder="sk-..." />
              )}
            </>
          )}

          {config.provider === 'custom' && (
            <>
              <label className={labelClass}>Custom Base URL</label>
              <input type="text" value={config.base_url} onChange={e => setConfig({...config, base_url: e.target.value})} className={inputClass} placeholder="https://api.your-provider.com/v1" />
            </>
          )}
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800">
          <button onClick={handleSave} disabled={saving} className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold">
            <Save size={16} /> {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}

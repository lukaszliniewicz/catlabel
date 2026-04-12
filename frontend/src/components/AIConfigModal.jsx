import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Plus, Trash, Eye, CheckCircle2, Circle, Settings2 } from 'lucide-react';

export default function AIConfigModal({ onClose }) {
  const [providers, setProviders] = useState([]);
  const [selectedProviderId, setSelectedProviderId] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchProviders();
  }, []);

  const fetchProviders = async () => {
    const res = await fetch('/api/ai/config');
    const data = await res.json();
    setProviders(data);

    if (data.length > 0 && !selectedProviderId) {
      let activeProviderId = data[0].id;
      data.forEach((provider) => {
        if (provider.models.some((model) => model.is_active)) {
          activeProviderId = provider.id;
        }
      });
      setSelectedProviderId(activeProviderId);
    }
  };

  const handleAddProvider = () => {
    const timestamp = Date.now();
    const newProvider = {
      id: `new-prov-${timestamp}`,
      name: 'New Provider',
      provider: 'openai',
      api_key: '',
      base_url: '',
      use_env: false,
      vertex_region: '',
      models: [
        {
          id: `new-mod-${timestamp}`,
          name: 'GPT-4o',
          model_name: 'gpt-4o',
          vision_capable: true,
          reasoning_effort: '',
          is_active: false
        }
      ]
    };
    setProviders([...providers, newProvider]);
    setSelectedProviderId(newProvider.id);
  };

  const handleUpdateProvider = (field, value) => {
    setProviders(providers.map((provider) => (
      provider.id === selectedProviderId ? { ...provider, [field]: value } : provider
    )));
  };

  const handleUpdateModel = (modelId, field, value) => {
    setProviders(providers.map((provider) => {
      if (field === 'is_active' && value === true) {
        return {
          ...provider,
          models: provider.models.map((model) => ({
            ...model,
            is_active: model.id === modelId
          }))
        };
      }

      if (provider.id !== selectedProviderId) {
        return provider;
      }

      return {
        ...provider,
        models: provider.models.map((model) => (
          model.id === modelId ? { ...model, [field]: value } : model
        ))
      };
    }));
  };

  const handleAddModel = () => {
    setProviders(providers.map((provider) => {
      if (provider.id !== selectedProviderId) {
        return provider;
      }

      return {
        ...provider,
        models: [
          ...provider.models,
          {
            id: `new-mod-${Date.now()}`,
            name: 'New Model',
            model_name: '',
            vision_capable: false,
            reasoning_effort: '',
            is_active: false
          }
        ]
      };
    }));
  };

  const handleDeleteModel = (modelId) => {
    setProviders(providers.map((provider) => {
      if (provider.id !== selectedProviderId) {
        return provider;
      }

      return {
        ...provider,
        models: provider.models.filter((model) => model.id !== modelId)
      };
    }));
  };

  const handleDeleteProvider = async (id) => {
    if (String(id).startsWith('new-')) {
      const nextProviders = providers.filter((provider) => provider.id !== id);
      setProviders(nextProviders);
      if (selectedProviderId === id) {
        setSelectedProviderId(nextProviders[0]?.id || null);
      }
      return;
    }

    if (confirm("Delete this provider and all its models?")) {
      await fetch(`/api/ai/config/${id}`, { method: 'DELETE' });
      const nextProviders = providers.filter((provider) => provider.id !== id);
      setProviders(nextProviders);
      if (selectedProviderId === id) {
        setSelectedProviderId(nextProviders[0]?.id || null);
      }
    }
  };

  const handleSave = async () => {
    setSaving(true);

    for (const provider of providers) {
      const payload = { ...provider };
      if (String(provider.id).startsWith('new-')) {
        delete payload.id;
      }

      payload.models = provider.models.map((model) => {
        const modelPayload = { ...model };
        if (String(model.id).startsWith('new-')) {
          delete modelPayload.id;
        }
        return modelPayload;
      });

      try {
        await fetch('/api/ai/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.error("Failed to save provider", provider.name, e);
      }
    }

    setSaving(false);
    onClose();
  };

  const current = providers.find((provider) => provider.id === selectedProviderId);
  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1 mt-3";

  const modalContent = (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-4xl rounded-xl shadow-2xl flex border border-neutral-200 dark:border-neutral-800 h-[700px] overflow-hidden">
        <div className="w-1/3 border-r border-neutral-100 dark:border-neutral-800 flex flex-col bg-neutral-50 dark:bg-neutral-900/50">
          <div className="p-4 border-b border-neutral-100 dark:border-neutral-800 flex items-center justify-between">
            <h3 className="font-serif text-base dark:text-white">AI Providers</h3>
            <button onClick={handleAddProvider} className="text-blue-500 hover:text-blue-600 bg-blue-50 dark:bg-blue-900/20 p-1.5 rounded">
              <Plus size={16} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {providers.map((provider) => (
              <div
                key={provider.id}
                onClick={() => setSelectedProviderId(provider.id)}
                className={`p-3 rounded-lg cursor-pointer flex justify-between items-center transition-colors ${selectedProviderId === provider.id ? 'bg-white dark:bg-neutral-800 shadow border border-neutral-200 dark:border-neutral-700' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 border border-transparent'}`}
              >
                <div>
                  <div className="text-sm font-bold dark:text-white">{provider.name}</div>
                  <div className="text-[10px] text-neutral-500 uppercase mt-1 flex gap-2">
                    <span>{provider.provider}</span>
                    <span className="text-blue-500">{provider.models.length} Models</span>
                  </div>
                </div>
                <button onClick={(e) => { e.stopPropagation(); handleDeleteProvider(provider.id); }} className="text-neutral-400 hover:text-red-500">
                  <Trash size={14} />
                </button>
              </div>
            ))}
            {providers.length === 0 && <div className="text-xs text-neutral-400 text-center mt-4">No providers configured</div>}
          </div>
        </div>

        <div className="w-2/3 flex flex-col bg-white dark:bg-neutral-950 relative">
          <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800 shrink-0">
            <h3 className="font-serif text-lg dark:text-white flex items-center gap-2">
              <Settings2 size={18} className="text-blue-500" />
              Configure Provider
            </h3>
            <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
              <X size={20} />
            </button>
          </div>

          {current ? (
            <div className="p-6 overflow-y-auto flex-1">
              <div className="bg-neutral-50 dark:bg-neutral-900/30 p-4 rounded-lg border border-neutral-200 dark:border-neutral-800 mb-8">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className={labelClass.replace('mt-3', '')}>Provider Alias</label>
                    <input type="text" value={current.name} onChange={(e) => handleUpdateProvider('name', e.target.value)} className={inputClass} placeholder="e.g. OpenAI Corporate" />
                  </div>
                  <div>
                    <label className={labelClass.replace('mt-3', '')}>Provider Type</label>
                    <select value={current.provider} onChange={(e) => handleUpdateProvider('provider', e.target.value)} className={inputClass}>
                      <option value="openai">OpenAI</option>
                      <option value="gemini">Google Gemini</option>
                      <option value="vertex_ai">Google Vertex AI</option>
                      <option value="custom">Custom (OpenAI Compatible)</option>
                    </select>
                  </div>
                </div>

                <div className="mt-4">
                  <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer mb-2">
                    <input type="checkbox" checked={current.use_env} onChange={(e) => handleUpdateProvider('use_env', e.target.checked)} />
                    Use Server Environment Variables (Ignore Key below)
                  </label>

                  {!current.use_env && (
                    <>
                      <label className={labelClass}>{current.provider === 'vertex_ai' ? 'Service Account JSON' : 'API Key'}</label>
                      {current.provider === 'vertex_ai' ? (
                        <textarea value={current.api_key} onChange={(e) => handleUpdateProvider('api_key', e.target.value)} className={inputClass} rows={3} placeholder='{"type": "service_account", ...}' />
                      ) : (
                        <input type="password" value={current.api_key} onChange={(e) => handleUpdateProvider('api_key', e.target.value)} className={inputClass} placeholder="sk-..." />
                      )}
                    </>
                  )}
                </div>

                {current.provider === 'custom' && (
                  <div className="mt-4 p-3 border border-purple-100 dark:border-purple-900/50 bg-purple-50 dark:bg-purple-900/10 rounded">
                    <label className={labelClass.replace('mt-3', '')}>Custom Base URL</label>
                    <input type="text" value={current.base_url} onChange={(e) => handleUpdateProvider('base_url', e.target.value)} className={inputClass} placeholder="http://localhost:1234/v1" />
                  </div>
                )}

                {current.provider === 'vertex_ai' && (
                  <div className="mt-4">
                    <label className={labelClass}>Vertex Region</label>
                    <input type="text" value={current.vertex_region || ''} onChange={(e) => handleUpdateProvider('vertex_region', e.target.value)} className={inputClass} placeholder="e.g. us-central1" />
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between mb-4 border-b border-neutral-200 dark:border-neutral-800 pb-2">
                <h4 className="text-sm font-bold dark:text-white uppercase tracking-widest">Available Models</h4>
                <button onClick={handleAddModel} className="flex items-center gap-1 px-3 py-1.5 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-xs font-bold rounded hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors">
                  <Plus size={14} />
                  Add Model
                </button>
              </div>

              <div className="space-y-4">
                {current.models.map((model) => (
                  <div key={model.id} className={`p-4 border rounded-lg transition-colors ${model.is_active ? 'border-green-500 bg-green-50/50 dark:bg-green-900/10 shadow-sm' : 'border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950'}`}>
                    <div className="flex justify-between items-start mb-4">
                      <button
                        onClick={() => handleUpdateModel(model.id, 'is_active', true)}
                        className={`flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 rounded-full transition-colors ${model.is_active ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400' : 'bg-neutral-100 text-neutral-500 hover:bg-neutral-200 dark:bg-neutral-900 dark:hover:bg-neutral-800 dark:text-neutral-400'}`}
                      >
                        {model.is_active ? <CheckCircle2 size={14} /> : <Circle size={14} />}
                        {model.is_active ? 'Global Active Model' : 'Set As Active'}
                      </button>
                      <button onClick={() => handleDeleteModel(model.id)} className="text-neutral-400 hover:text-red-500 p-1">
                        <Trash size={16} />
                      </button>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className={labelClass.replace('mt-3', '')}>Display Name</label>
                        <input value={model.name} onChange={(e) => handleUpdateModel(model.id, 'name', e.target.value)} className={inputClass} placeholder="e.g. GPT-4o Vision" />
                      </div>
                      <div>
                        <label className={labelClass.replace('mt-3', '')}>Model ID</label>
                        <input value={model.model_name} onChange={(e) => handleUpdateModel(model.id, 'model_name', e.target.value)} className={inputClass} placeholder="e.g. gpt-4o" />
                      </div>
                    </div>

                    <div className="flex items-center justify-between mt-4 bg-neutral-50 dark:bg-neutral-900/30 p-3 rounded">
                      <label className="flex items-center gap-2 text-xs font-bold text-neutral-700 dark:text-neutral-300 cursor-pointer">
                        <input type="checkbox" checked={model.vision_capable} onChange={(e) => handleUpdateModel(model.id, 'vision_capable', e.target.checked)} className="w-4 h-4 accent-blue-600" />
                        <Eye size={16} className={model.vision_capable ? 'text-blue-500' : 'text-neutral-400'} />
                        Vision Capable
                      </label>
                      <div className="flex items-center gap-3">
                        <label className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">Reasoning Level:</label>
                        <select value={model.reasoning_effort || ''} onChange={(e) => handleUpdateModel(model.id, 'reasoning_effort', e.target.value)} className="bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 text-xs px-2 py-1.5 dark:text-white focus:outline-none focus:border-blue-500">
                          <option value="">Default / None</option>
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                    </div>
                  </div>
                ))}
                {current.models.length === 0 && <div className="text-xs text-neutral-400 text-center py-8 bg-neutral-50 dark:bg-neutral-900/20 rounded-lg border border-dashed border-neutral-200 dark:border-neutral-800">No models added to this provider yet.</div>}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-neutral-400 text-sm">
              <Settings2 size={48} className="mb-4 opacity-20" />
              Select or add a provider from the sidebar
            </div>
          )}

          <div className="p-4 border-t border-neutral-100 dark:border-neutral-800 shrink-0">
            <button onClick={handleSave} disabled={saving || !current} className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50">
              <Save size={16} />
              {saving ? 'Saving...' : 'Save All Configuration'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}

import React, { useState, useEffect } from 'react';
import { X, Save, Plus, Trash, Eye } from 'lucide-react';

export default function AIConfigModal({ onClose }) {
  const [profiles, setProfiles] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchProfiles();
  }, []);

  const fetchProfiles = async () => {
    const res = await fetch('/api/ai/config');
    const data = await res.json();
    setProfiles(data);
    if (data.length > 0 && !selectedId) {
      const active = data.find(p => p.is_active) || data[0];
      setSelectedId(active.id);
    }
  };

  const handleAddNew = () => {
    const newProfile = {
      id: `new-${Date.now()}`,
      name: 'New Profile', provider: 'openai', model_name: 'gpt-4o',
      api_key: '', base_url: '', use_env: false, vision_capable: false, is_active: false
    };
    setProfiles([...profiles, newProfile]);
    setSelectedId(newProfile.id);
  };

  const handleUpdateCurrent = (field, value) => {
    setProfiles(profiles.map(p => p.id === selectedId ? { ...p, [field]: value } : p));
  };

  const handleDelete = async (id) => {
    if (String(id).startsWith('new-')) {
      setProfiles(profiles.filter(p => p.id !== id));
      setSelectedId(profiles[0]?.id || null);
      return;
    }
    if (confirm("Delete this profile?")) {
      await fetch(`/api/ai/config/${id}`, { method: 'DELETE' });
      fetchProfiles();
    }
  };

  const handleSave = async () => {
    const activeProfile = profiles.find(p => p.id === selectedId);
    if (!activeProfile) return;
    
    setSaving(true);
    // Mark as the active one in DB
    const payload = { ...activeProfile, is_active: true };
    delete payload.id; // Let backend generate if it's new
    if (!String(selectedId).startsWith('new-')) payload.id = selectedId;

    await fetch('/api/ai/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    setSaving(false);
    onClose();
  };

  const current = profiles.find(p => p.id === selectedId);
  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1 mt-3";

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-3xl rounded-xl shadow-2xl flex border border-neutral-200 dark:border-neutral-800 h-[600px] overflow-hidden">
        
        {/* Sidebar: Profile List */}
        <div className="w-1/3 border-r border-neutral-100 dark:border-neutral-800 flex flex-col bg-neutral-50 dark:bg-neutral-900/50">
          <div className="p-4 border-b border-neutral-100 dark:border-neutral-800 flex items-center justify-between">
            <h3 className="font-serif text-base dark:text-white">AI Profiles</h3>
            <button onClick={handleAddNew} className="text-blue-500 hover:text-blue-600"><Plus size={18} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {profiles.map(p => (
              <div 
                key={p.id} 
                onClick={() => setSelectedId(p.id)}
                className={`p-3 rounded cursor-pointer flex justify-between items-center transition-colors ${selectedId === p.id ? 'bg-blue-100 dark:bg-blue-900/40 border border-blue-200 dark:border-blue-800' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 border border-transparent'}`}
              >
                <div>
                  <div className="text-sm font-bold dark:text-white flex items-center gap-2">
                    {p.name} {p.is_active && <span className="w-2 h-2 rounded-full bg-green-500" title="Active"></span>}
                  </div>
                  <div className="text-[10px] text-neutral-500 uppercase">{p.provider} • {p.model_name}</div>
                </div>
                <button onClick={(e) => { e.stopPropagation(); handleDelete(p.id); }} className="text-neutral-400 hover:text-red-500"><Trash size={14}/></button>
              </div>
            ))}
          </div>
        </div>

        {/* Main: Edit Profile */}
        <div className="w-2/3 flex flex-col">
          <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
            <h3 className="font-serif text-lg dark:text-white">Configure Profile</h3>
            <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
              <X size={20} />
            </button>
          </div>
          
          {current ? (
            <div className="p-6 overflow-y-auto flex-1">
              <label className={labelClass}>Profile Name</label>
              <input type="text" value={current.name} onChange={e => handleUpdateCurrent('name', e.target.value)} className={inputClass} placeholder="e.g. GPT-4 Vision Main" />

              <label className={labelClass}>Provider</label>
              <select value={current.provider} onChange={e => handleUpdateCurrent('provider', e.target.value)} className={inputClass}>
                <option value="openai">OpenAI</option>
                <option value="gemini">Google Gemini</option>
                <option value="vertex_ai">Google Vertex AI</option>
                <option value="custom">Custom (OpenAI Compatible)</option>
              </select>

              <label className={labelClass}>Model Name</label>
              <input type="text" value={current.model_name} onChange={e => handleUpdateCurrent('model_name', e.target.value)} className={inputClass} placeholder="e.g. gpt-4o, gemini-1.5-pro" />

              <div className="mt-4 p-4 border border-blue-100 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-900/10 rounded">
                <label className="flex items-center gap-2 text-sm font-bold text-neutral-800 dark:text-neutral-200 cursor-pointer">
                  <input type="checkbox" checked={current.vision_capable} onChange={e => handleUpdateCurrent('vision_capable', e.target.checked)} className="w-4 h-4" /> 
                  <Eye size={16} className="text-blue-500" />
                  Model is Vision-Capable
                </label>
                <p className="text-[10px] text-neutral-500 mt-1 ml-6">
                  If enabled, the assistant will automatically "see" a picture of the canvas as it edits, letting it perfectly align HTML and text.
                </p>
              </div>

              <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer mt-4 mb-2">
                <input type="checkbox" checked={current.use_env} onChange={e => handleUpdateCurrent('use_env', e.target.checked)} /> 
                Use Server Environment Variables (Ignore Key below)
              </label>

              {!current.use_env && (
                <>
                  <label className={labelClass}>{current.provider === 'vertex_ai' ? 'Service Account JSON' : 'API Key'}</label>
                  {current.provider === 'vertex_ai' ? (
                    <textarea value={current.api_key} onChange={e => handleUpdateCurrent('api_key', e.target.value)} className={inputClass} rows={4} placeholder='{"type": "service_account", ...}' />
                  ) : (
                    <input type="password" value={current.api_key} onChange={e => handleUpdateCurrent('api_key', e.target.value)} className={inputClass} placeholder="sk-..." />
                  )}
                </>
              )}

              {current.provider === 'custom' && (
                <>
                  <label className={labelClass}>Custom Base URL</label>
                  <input type="text" value={current.base_url} onChange={e => handleUpdateCurrent('base_url', e.target.value)} className={inputClass} placeholder="https://api.your-provider.com/v1" />
                </>
              )}
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-neutral-400 text-sm">Select or create a profile</div>
          )}

          <div className="p-4 border-t border-neutral-100 dark:border-neutral-800">
            <button onClick={handleSave} disabled={saving || !current} className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50">
              <Save size={16} /> {saving ? 'Saving...' : 'Set Active & Save'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

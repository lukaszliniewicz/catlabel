import React, { useId } from 'react';
import { useStore } from '../../store';
import { useShallow } from 'zustand/react/shallow';
import { inputClass, labelClass } from './styles';
import { Plus } from 'lucide-react';
import FileUploadButton from '../FileUploadButton';

export default function GlobalDefaults({ localSettings, setLocalSettings }) {
  const { settings, fonts, uploadFont, updateSettingsAPI } = useStore(useShallow(state => ({
    settings: state.settings,
    fonts: state.fonts,
    uploadFont: state.uploadFont,
    updateSettingsAPI: state.updateSettingsAPI,
  })));
  const saveStatus = useStore(state => state.settingsSaveStatus);
  const saveError = useStore(state => state.settingsSaveError);
  const draftChanged = localSettings.default_font !== settings.default_font || localSettings.intended_media_type !== settings.intended_media_type;
  const tabId = useId();
  return <>
    <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Global Defaults</h2>
      <div className="pt-2">
        <label className={labelClass} htmlFor={`${tabId}-media`}>AI Media Assumption</label>
        <select id={`${tabId}-media`} name="intended_media_type" value={localSettings.intended_media_type || 'unknown'} onChange={(e) => setLocalSettings({ ...localSettings, intended_media_type: e.target.value })} className={inputClass}>
          <option value="unknown">Not Set (AI will ask)</option>
          <option value="continuous">Continuous Roll (Generic)</option>
          <option value="pre-cut">Pre-cut Labels (Niimbot)</option>
          <option value="both">Both / Mixed</option>
        </select>
        <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1 mb-2">Guides the AI Assistant if no printer is connected.</p>
      </div>
      <div className="pt-2">
        <label className={labelClass} htmlFor={`${tabId}-default-font`}>Global Default Font</label>
        <div className="flex gap-2">
          <select id={`${tabId}-default-font`} name="default_font" value={localSettings.default_font || 'RobotoCondensed.ttf'} onChange={(e) => setLocalSettings({ ...localSettings, default_font: e.target.value })} className={inputClass}>
            <option value="arial.ttf">System Arial</option>
            {fonts.map(f => (
              <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
            ))}
          </select>
          <FileUploadButton label="Upload custom font" accept=".ttf,.otf" className="min-h-11 min-w-11 flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 hover:bg-neutral-200 dark:hover:bg-neutral-700" onChange={event => { if (event.target.files[0]) uploadFont(event.target.files[0]); }}><Plus size={16} /></FileUploadButton>
        </div>
        <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1">Applies to all newly created text items.</p>
      </div>
      {saveStatus === 'failed' && <p role="alert" className="text-sm text-red-800 dark:text-red-300">{saveError}</p>}
      <p role="status" aria-live="polite">{saveStatus === 'saved' && !draftChanged ? 'Global defaults saved.' : draftChanged ? 'Unsaved default changes' : ''}</p>
      <button
        onClick={() => updateSettingsAPI(localSettings)}
        disabled={saveStatus === 'saving'}
        className="w-full py-3 rounded-none transition-colors text-xs uppercase tracking-widest font-bold border bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white border-neutral-200 dark:border-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-800"
      >
        {saveStatus === 'saving' ? 'Saving global defaults…' : 'Save Global Defaults'}
      </button>
    </div>
  </>;
}

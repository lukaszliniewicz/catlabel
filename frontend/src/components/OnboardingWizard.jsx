import React from 'react';
import { useStore } from '../store';
import { Printer, Tag } from 'lucide-react';

export default function OnboardingWizard() {
  const updateSettingsAPI = useStore((state) => state.updateSettingsAPI);
  const settings = useStore((state) => state.settings);

  const handleSelect = (type) => {
    updateSettingsAPI({ ...settings, intended_media_type: type });
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-lg rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800 p-8 text-center relative">
        <h2 className="text-2xl font-serif tracking-tight dark:text-white mb-2">Welcome to CatLabel Studio</h2>
        <p className="text-sm text-neutral-500 mb-8">To help the AI Assistant design perfectly sized layouts, what kind of printer do you primarily use?</p>

        <div className="grid grid-cols-2 gap-4 mb-6">
          <button onClick={() => handleSelect('continuous')} className="flex flex-col items-center justify-center gap-4 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all group">
            <Printer size={48} className="text-neutral-400 group-hover:text-blue-500" />
            <div>
              <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Continuous Roll</h3>
              <p className="text-xs text-neutral-500 mt-2">Generic Chinese, Phomemo, etc. (Tape feeds infinitely)</p>
            </div>
          </button>

          <button onClick={() => handleSelect('pre-cut')} className="flex flex-col items-center justify-center gap-4 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all group">
            <Tag size={48} className="text-neutral-400 group-hover:text-emerald-500" />
            <div>
              <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Pre-cut Labels</h3>
              <p className="text-xs text-neutral-500 mt-2">Niimbot D11, B21, etc. (Fixed individual stickers)</p>
            </div>
          </button>
        </div>

        <button onClick={() => handleSelect('both')} className="text-xs font-bold uppercase tracking-widest text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors">
          I use both / Skip for now
        </button>
      </div>
    </div>
  );
}

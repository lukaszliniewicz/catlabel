import React, { useEffect, useState } from 'react';
import { useStore } from '../store';
import { Printer, Sparkles, Search, ChevronRight, Loader2, Bot } from 'lucide-react';

export default function OnboardingWizard() {
  const {
    updateSettingsAPI,
    settings,
    selectedPrinterInfo,
    setSelectedPrinter,
    addManualPrinter,
    setShowAiConfig
  } = useStore();

  const [step, setStep] = useState(1);
  const [isScanning, setIsScanning] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);
  const [scannedPrinters, setScannedPrinters] = useState([]);
  const [manualMode, setManualMode] = useState(false);
  const [selectedManualModel, setSelectedManualModel] = useState('');
  const [supportedModels, setSupportedModels] = useState([]);

  useEffect(() => {
    fetch('/api/printers/supported_models')
      .then((res) => res.json())
      .then((data) => setSupportedModels(data.models || []))
      .catch((error) => {
        console.error('Failed to fetch supported printer models', error);
      });
  }, []);

  const finishOnboarding = (mediaTypeAssumption) => {
    updateSettingsAPI({ ...settings, intended_media_type: mediaTypeAssumption });
  };

  const handleScan = async () => {
    setIsScanning(true);
    setHasScanned(true);
    setManualMode(false);

    try {
      const res = await fetch('/api/printers/scan');
      const data = await res.json();
      setScannedPrinters(data.devices || []);
    } catch (e) {
      console.error(e);
      setManualMode(true);
    } finally {
      setIsScanning(false);
    }
  };

  const selectPrinter = async (printerObj) => {
    await setSelectedPrinter(printerObj.address, printerObj);
    setStep(2);
  };

  const selectManualPrinter = async () => {
    if (!selectedManualModel) return;

    setIsScanning(true);
    try {
      const res = await fetch(`/api/printers/model/${encodeURIComponent(selectedManualModel)}`);
      const info = await res.json();

      const manualPrinter = {
        ...info,
        name: `Manual Profile (${selectedManualModel})`,
        address: `manual-${selectedManualModel}`,
        transport: 'offline',
        model_id: info.model_id || info.model,
      };

      addManualPrinter(manualPrinter);
      await setSelectedPrinter(manualPrinter.address, manualPrinter);
      setStep(2);
    } catch (e) {
      console.error(e);
      alert('Failed to load printer profile. Please check backend connection.');
    } finally {
      setIsScanning(false);
    }
  };

  const selectedMediaType = selectedPrinterInfo?.media_type || 'continuous';

  return (
    <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-2xl rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800 overflow-hidden min-h-[450px]">

        <div className="bg-neutral-50 dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 p-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-serif tracking-tight dark:text-white">Welcome to CatLabel Studio</h2>
            <p className="text-sm text-neutral-500 mt-1">Let's configure your workspace.</p>
          </div>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest">
            <span className={step >= 1 ? 'text-blue-600 dark:text-blue-400' : 'text-neutral-400'}>1. Printer</span>
            <ChevronRight size={14} className="text-neutral-300 dark:text-neutral-700" />
            <span className={step >= 2 ? 'text-blue-600 dark:text-blue-400' : 'text-neutral-400'}>2. AI Assistant</span>
          </div>
        </div>

        {step === 1 && (
          <div className="p-8 flex-1 flex flex-col gap-6">
            <div className="flex gap-4">
              <button
                onClick={handleScan}
                className="flex-1 flex flex-col items-center justify-center gap-3 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all group"
              >
                <Search size={32} className="text-blue-500" />
                <div className="text-center">
                  <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Scan Bluetooth</h3>
                  <p className="text-[10px] text-neutral-500 mt-1">Ensure printer is turned on</p>
                </div>
              </button>

              <button
                onClick={() => setManualMode(true)}
                className="flex-1 flex flex-col items-center justify-center gap-3 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all group"
              >
                <Printer size={32} className="text-emerald-500" />
                <div className="text-center">
                  <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Manual Setup</h3>
                  <p className="text-[10px] text-neutral-500 mt-1">Select from offline profiles</p>
                </div>
              </button>
            </div>

            {isScanning && !manualMode && (
              <div className="flex justify-center items-center py-8 text-neutral-500 gap-2 text-sm">
                <Loader2 className="animate-spin text-blue-500" size={20} /> Searching for printers...
              </div>
            )}

            {!isScanning && !manualMode && scannedPrinters.length > 0 && (
              <div className="mt-4 border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden">
                <div className="bg-neutral-100 dark:bg-neutral-900 px-4 py-2 text-[10px] uppercase font-bold text-neutral-500">Found Printers</div>
                {scannedPrinters.map((p) => (
                  <div key={p.address} onClick={() => selectPrinter(p)} className="px-4 py-3 flex justify-between items-center cursor-pointer hover:bg-blue-50 dark:hover:bg-blue-900/20 border-t border-neutral-100 dark:border-neutral-800 transition-colors">
                    <div>
                      <div className="font-bold dark:text-white text-sm">{p.name || p.display_address}</div>
                      <div className="text-xs text-neutral-500">{p.width_mm}mm • {p.media_type}</div>
                    </div>
                    <ChevronRight className="text-blue-500" size={16} />
                  </div>
                ))}
              </div>
            )}

            {!isScanning && !manualMode && hasScanned && scannedPrinters.length === 0 && (
              <div className="mt-4 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6 text-center text-sm text-neutral-500">
                No Bluetooth printers were found. You can try scanning again or use Manual Setup.
              </div>
            )}

            {manualMode && (
              <div className="mt-2 bg-neutral-50 dark:bg-neutral-900/50 p-6 rounded-lg border border-neutral-200 dark:border-neutral-800">
                <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-2">Select Printer Profile</label>
                <select
                  value={selectedManualModel}
                  onChange={(e) => setSelectedManualModel(e.target.value)}
                  className="w-full bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-3 text-sm dark:text-white focus:outline-none focus:border-emerald-500 transition-colors mb-2"
                >
                  <option value="" disabled>Choose a printer family...</option>

                  <optgroup label="Generic Printers (Continuous Roll / A4 / A5)">
                    {supportedModels.filter((model) => model.vendor !== 'niimbot').map((model) => (
                      <option key={model.model_no} value={model.model_no}>
                        {model.name} - {model.width_mm}mm ({model.dpi} DPI)
                      </option>
                    ))}
                  </optgroup>

                  <optgroup label="Niimbot Printers (Pre-cut Labels)">
                    {supportedModels.filter((model) => model.vendor === 'niimbot').map((model) => (
                      <option key={model.model_no} value={model.model_no}>
                        {model.name} - {model.width_mm}mm ({model.dpi} DPI)
                      </option>
                    ))}
                  </optgroup>
                </select>
                <p className="text-[10px] text-neutral-500 leading-relaxed mb-4">
                  <strong>Hint:</strong> If you bought a generic "Mini Printer" from AliExpress that looks like a cat, it almost always maps to the <strong>GT01</strong> profile.
                </p>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setManualMode(false)} className="px-4 py-2 text-xs uppercase font-bold text-neutral-500 hover:text-neutral-800 dark:hover:text-white transition-colors">Cancel</button>
                  <button onClick={selectManualPrinter} disabled={!selectedManualModel || isScanning} className="px-6 py-2 bg-emerald-600 text-white text-xs uppercase font-bold hover:bg-emerald-700 transition-colors disabled:opacity-50">
                    Apply Profile
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="p-8 flex-1 flex flex-col items-center justify-center text-center gap-6">
            <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-full flex items-center justify-center">
              <Bot size={32} />
            </div>
            <div>
              <h3 className="text-xl font-serif dark:text-white mb-2">Configure Your AI Layout Assistant</h3>
              <p className="text-sm text-neutral-500 max-w-md mx-auto leading-relaxed mb-4">
                CatLabel includes an advanced AI Agent that can instantly design labels, configure permutations, and inject variables based on plain English requests.
              </p>
              <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-900 p-4 rounded text-left text-xs text-neutral-600 dark:text-neutral-400">
                <p className="mb-2"><strong>Cloud APIs:</strong> Connect OpenAI, Gemini, or Vertex AI instantly.</p>
                <p><strong>Local Inference (Free):</strong> You can use apps like <em>LM Studio</em> by selecting the "Custom" provider in the settings and pointing it to <code>http://localhost:1234/v1</code>.</p>
              </div>
            </div>

            <div className="flex w-full gap-4 mt-4">
              <button
                onClick={() => finishOnboarding(selectedMediaType)}
                className="flex-1 py-3 text-xs uppercase font-bold tracking-widest border border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
              >
                Skip For Now
              </button>
              <button
                onClick={() => {
                  finishOnboarding(selectedMediaType);
                  setShowAiConfig(true);
                }}
                className="flex-[2] py-3 bg-blue-600 text-white text-xs uppercase font-bold tracking-widest hover:bg-blue-700 flex justify-center items-center gap-2 transition-colors"
              >
                <Sparkles size={16} /> Configure AI Keys
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

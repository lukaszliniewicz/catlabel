import React, { useEffect, useState } from 'react';
import { useStore } from '../store';
import { Printer, Sparkles, Search, ChevronRight, Loader2, Bot, ArrowLeft, CheckCircle, Globe, Tag } from 'lucide-react';

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
  
  // Navigation states for manual setup flow
  const [manualStep, setManualStep] = useState('off'); // 'off', 'vendor', 'model', 'added'
  const [selectedVendor, setSelectedVendor] = useState(null);
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
    setManualStep('off');

    try {
      const res = await fetch('/api/printers/scan');
      const data = await res.json();
      setScannedPrinters(data.devices || []);
    } catch (e) {
      console.error(e);
      // If scan crashes, gently encourage manual mode
      setManualStep('vendor');
    } finally {
      setIsScanning(false);
    }
  };

  const selectPrinter = async (printerObj) => {
    await setSelectedPrinter(printerObj.address, printerObj);
    setStep(2);
  };

  const handleAddManual = async (info) => {
    const address = `manual-${info.model_id || info.model}`;
    const { manualPrinters } = useStore.getState();
    const exists = manualPrinters.some(p => p.address === address);

    if (exists) {
      // Don't duplicate, but still select it and move to success screen
      await setSelectedPrinter(address, manualPrinters.find(p => p.address === address));
      setManualStep('added');
      return;
    }

    const manualPrinter = {
      ...info,
      name: `Offline: ${info.name}`,
      address: address,
      transport: 'offline',
      model_id: info.model_id || info.model,
    };

    addManualPrinter(manualPrinter);
    await setSelectedPrinter(manualPrinter.address, manualPrinter);
    setManualStep('added');
  };

  const getGroupedModels = () => {
    if (!selectedVendor) return {};
    const vendorModels = supportedModels.filter(m => m.vendor === selectedVendor);
    
    const groups = {
      'Small Labels (12-15mm)': [],
      'Medium Labels (25-30mm)': [],
      'Standard / 2-inch (48-58mm)': [],
      'Large / 3-inch (72-80mm)': [],
      'Extra Large / 4-inch (100mm+)': []
    };

    vendorModels.forEach(m => {
      const w = m.width_mm || 48;
      if (w <= 15) groups['Small Labels (12-15mm)'].push(m);
      else if (w <= 30) groups['Medium Labels (25-30mm)'].push(m);
      else if (w <= 58) groups['Standard / 2-inch (48-58mm)'].push(m);
      else if (w <= 80) groups['Large / 3-inch (72-80mm)'].push(m);
      else groups['Extra Large / 4-inch (100mm+)'].push(m);
    });

    // Strip out empty size groups
    Object.keys(groups).forEach(k => {
      if (groups[k].length === 0) delete groups[k];
    });

    return groups;
  };

  const selectedMediaType = selectedPrinterInfo?.media_type || 'continuous';

  return (
    <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-3xl rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800 overflow-hidden min-h-[480px]">

        <div className="bg-neutral-50 dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 p-6 flex items-center justify-between shrink-0">
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
          <div className="p-8 flex-1 flex flex-col gap-6 relative overflow-hidden">
            
            {/* --- MAIN MENU --- */}
            {!isScanning && manualStep === 'off' && (
              <div className="flex-1 flex flex-col animate-in fade-in duration-300">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  
                  {/* Logo Card */}
                  <div className="flex flex-col items-center justify-center gap-3 p-6 border-2 border-neutral-100 dark:border-neutral-800 rounded-xl bg-neutral-50 dark:bg-neutral-900/50">
                    <img src="/logo.webp" alt="CatLabel" className="w-16 h-16 drop-shadow-md" draggable={false} />
                    <div className="text-center">
                      <h3 className="font-serif font-bold text-sm dark:text-white tracking-tight">CatLabel Studio</h3>
                      <p className="text-[10px] text-neutral-500 mt-1 uppercase tracking-widest">Setup Wizard</p>
                    </div>
                  </div>

                  {/* Scan Card */}
                  <button
                    onClick={handleScan}
                    className="flex flex-col items-center justify-center gap-3 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all group"
                  >
                    <Search size={32} className="text-blue-500 group-hover:scale-110 transition-transform" />
                    <div className="text-center">
                      <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Scan Bluetooth</h3>
                      <p className="text-[10px] text-neutral-500 mt-1">Ensure printer is turned on</p>
                    </div>
                  </button>

                  {/* Manual Card */}
                  <button
                    onClick={() => setManualStep('vendor')}
                    className="flex flex-col items-center justify-center gap-3 p-6 border-2 border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all group"
                  >
                    <Printer size={32} className="text-emerald-500 group-hover:scale-110 transition-transform" />
                    <div className="text-center">
                      <h3 className="font-bold text-sm dark:text-white uppercase tracking-widest">Manual Setup</h3>
                      <p className="text-[10px] text-neutral-500 mt-1">Select offline profiles</p>
                    </div>
                  </button>

                </div>

                {hasScanned && scannedPrinters.length > 0 && (
                  <div className="mt-6 border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden flex-1 flex flex-col">
                    <div className="bg-neutral-100 dark:bg-neutral-900 px-4 py-2 text-[10px] uppercase font-bold text-neutral-500 shrink-0">Found Printers</div>
                    <div className="overflow-y-auto max-h-48">
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
                  </div>
                )}

                {hasScanned && scannedPrinters.length === 0 && (
                  <div className="mt-6 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6 text-center text-sm text-neutral-500">
                    No Bluetooth printers were found. You can try scanning again or use Manual Setup.
                  </div>
                )}
              </div>
            )}

            {/* --- SCANNING LOADING VIEW --- */}
            {isScanning && (
              <div className="flex flex-col justify-center items-center py-12 text-neutral-500 gap-4 flex-1">
                <Loader2 className="animate-spin text-blue-500" size={32} /> 
                <span className="text-sm font-medium">Searching for Bluetooth printers...</span>
              </div>
            )}

            {/* --- MANUAL SETUP: VENDOR SELECTION --- */}
            {!isScanning && manualStep === 'vendor' && (
              <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-4 duration-300">
                 <button onClick={() => setManualStep('off')} className="flex items-center gap-1 text-xs uppercase font-bold tracking-widest text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors mb-6 self-start">
                   <ArrowLeft size={14} /> Back
                 </button>
                 <h3 className="text-sm font-bold uppercase tracking-widest text-neutral-400 dark:text-neutral-500 mb-4">Select Printer Brand</h3>
                 <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    
                    <button onClick={() => { setSelectedVendor('generic'); setManualStep('model'); }} className="flex flex-col items-center text-center gap-3 p-5 border border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all">
                      <Globe size={28} className="text-blue-500" />
                      <div>
                        <div className="font-bold text-sm dark:text-white">Generic Chinese</div>
                        <div className="text-[10px] text-neutral-500 mt-1">"Cat Printers", Mini Printers</div>
                      </div>
                    </button>

                    <button onClick={() => { setSelectedVendor('niimbot'); setManualStep('model'); }} className="flex flex-col items-center text-center gap-3 p-5 border border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all">
                      <Tag size={28} className="text-emerald-500" />
                      <div>
                        <div className="font-bold text-sm dark:text-white">Niimbot</div>
                        <div className="text-[10px] text-neutral-500 mt-1">D11, B21, B3S, B18</div>
                      </div>
                    </button>

                    <button onClick={() => { setSelectedVendor('phomemo'); setManualStep('model'); }} className="flex flex-col items-center text-center gap-3 p-5 border border-neutral-200 dark:border-neutral-800 rounded-xl hover:border-purple-500 hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-all">
                      <Printer size={28} className="text-purple-500" />
                      <div>
                        <div className="font-bold text-sm dark:text-white">Phomemo</div>
                        <div className="text-[10px] text-neutral-500 mt-1">M02, M110, D30, T02</div>
                      </div>
                    </button>

                 </div>
                 
                 <div className="mt-6 text-[10px] text-neutral-500 leading-relaxed bg-neutral-50 dark:bg-neutral-900/50 p-3 rounded border border-neutral-100 dark:border-neutral-800">
                    <strong>Hint:</strong> If you bought a generic "Mini Printer" from AliExpress that looks like a cat, it almost always uses the <strong>Generic Chinese</strong> profile (Model: GT01).
                 </div>
              </div>
            )}

            {/* --- MANUAL SETUP: MODEL SELECTION --- */}
            {!isScanning && manualStep === 'model' && (
              <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-4 duration-300">
                 <button onClick={() => setManualStep('vendor')} className="flex items-center gap-1 text-xs uppercase font-bold tracking-widest text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors mb-6 self-start">
                   <ArrowLeft size={14} /> Back to Brands
                 </button>
                 
                 <div className="border border-neutral-200 dark:border-neutral-800 rounded-xl overflow-hidden flex flex-col flex-1 max-h-[50vh]">
                   <div className="bg-neutral-50 dark:bg-neutral-900 px-4 py-3 border-b border-neutral-200 dark:border-neutral-800 text-xs font-bold uppercase tracking-widest text-neutral-500 shrink-0">
                     Select Specific Model
                   </div>
                   <div className="overflow-y-auto flex-1 bg-white dark:bg-neutral-950">
                     {Object.entries(getGroupedModels()).map(([groupName, models]) => (
                       <div key={groupName}>
                         <div className="px-4 py-1.5 bg-neutral-100 dark:bg-neutral-900/50 text-[10px] font-bold uppercase tracking-widest text-neutral-400 border-y border-neutral-100 dark:border-neutral-800/50 sticky top-0 backdrop-blur-md">
                           {groupName}
                         </div>
                         <div className="divide-y divide-neutral-100 dark:divide-neutral-800/50">
                           {models.map(m => (
                             <button 
                               key={m.model_no || m.model_id} 
                               onClick={() => handleAddManual(m)}
                               className="w-full text-left px-4 py-3 flex items-center justify-between hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors group"
                             >
                               <div>
                                 <div className="text-sm font-bold dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">{m.name}</div>
                                 <div className="text-[10px] text-neutral-500 mt-0.5">{m.media_type === 'continuous' ? 'Continuous Roll' : 'Pre-cut Labels'}</div>
                               </div>
                               <div className="text-[10px] font-bold tracking-widest uppercase text-neutral-400 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 px-2 py-1 rounded">
                                 {m.dpi} DPI
                               </div>
                             </button>
                           ))}
                         </div>
                       </div>
                     ))}
                   </div>
                 </div>
              </div>
            )}

            {/* --- MANUAL SETUP: ADDED SUCCESS --- */}
            {!isScanning && manualStep === 'added' && (
              <div className="flex flex-col items-center justify-center py-6 gap-6 text-center animate-in zoom-in-95 duration-300 flex-1">
                 <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 text-green-500 rounded-full flex items-center justify-center">
                   <CheckCircle size={32} />
                 </div>
                 <div>
                   <h3 className="text-xl font-serif dark:text-white mb-2">Profile Added</h3>
                   <p className="text-sm text-neutral-500">The offline printer profile has been successfully added to your workspace.</p>
                 </div>
                 <div className="flex w-full gap-4 mt-2 max-w-sm">
                   <button onClick={() => setManualStep('vendor')} className="flex-1 py-3 text-xs uppercase font-bold tracking-widest border border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors">
                     Add Another
                   </button>
                   <button onClick={() => setStep(2)} className="flex-1 py-3 bg-blue-600 text-white text-xs uppercase font-bold tracking-widest hover:bg-blue-700 flex justify-center items-center gap-2 transition-colors">
                     Continue <ChevronRight size={16} />
                   </button>
                 </div>
              </div>
            )}

          </div>
        )}

        {/* --- STEP 2: AI CONFIG --- */}
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

            <div className="flex w-full gap-4 mt-4 max-w-md">
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
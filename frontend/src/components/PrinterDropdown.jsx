import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Trash2, Printer as PrinterIcon } from 'lucide-react';
import { useStore } from '../store';

export default function PrinterDropdown({ printers, manualPrinters, selectedPrinter, onSelect }) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);
  const { removeManualPrinter } = useStore();

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const allPrinters = [...printers, ...manualPrinters];
  const selectedData = allPrinters.find((p) => p.address === selectedPrinter);

  return (
    <div className="relative w-full" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-2.5 text-xs text-neutral-900 dark:text-white transition-colors hover:border-blue-500"
      >
        <div className="flex items-center gap-2 truncate">
          {selectedData ? (
            <>
              <div className={`w-2 h-2 rounded-full shrink-0 ${selectedData.transport === 'offline' ? 'bg-neutral-300 dark:bg-neutral-600' : 'bg-green-500'}`} />
              <span className="truncate font-bold uppercase tracking-wider">
                {selectedData.name || selectedData.display_address} ({selectedData.width_mm}mm)
              </span>
            </>
          ) : (
            <span className="text-neutral-500 uppercase tracking-wider font-bold">Select a printer...</span>
          )}
        </div>
        <ChevronDown size={14} className={`text-neutral-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl rounded-md z-50 overflow-hidden max-h-64 flex flex-col">
          <div className="overflow-y-auto flex-1">

            {printers.length > 0 && (
              <div className="py-1">
                <div className="px-3 py-1.5 text-[10px] uppercase font-bold tracking-widest text-neutral-400 dark:text-neutral-500 bg-neutral-50 dark:bg-neutral-950/50">
                  Bluetooth Printers
                </div>
                {printers.map((p) => (
                  <button
                    key={p.address}
                    onClick={() => { onSelect(p.address, p); setIsOpen(false); }}
                    className={`w-full flex items-center justify-between px-3 py-2.5 text-xs text-left transition-colors ${selectedPrinter === p.address ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-700 dark:text-neutral-200'}`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <div className="w-2 h-2 rounded-full shrink-0 bg-green-500" />
                      <span className="truncate font-bold uppercase tracking-wider">{p.name || p.display_address} ({p.width_mm}mm)</span>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {manualPrinters.length > 0 && (
              <div className={`py-1 ${printers.length > 0 ? 'border-t border-neutral-100 dark:border-neutral-800' : ''}`}>
                <div className="px-3 py-1.5 text-[10px] uppercase font-bold tracking-widest text-neutral-400 dark:text-neutral-500 bg-neutral-50 dark:bg-neutral-950/50">
                  Offline Profiles
                </div>
                {manualPrinters.map((p, index) => (
                  <div
                    key={`${p.address}-${index}`}
                    className={`w-full flex items-center justify-between px-3 py-1.5 text-xs text-left transition-colors ${selectedPrinter === p.address ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-700 dark:text-neutral-200'}`}
                  >
                    <button
                      onClick={() => { onSelect(p.address, p); setIsOpen(false); }}
                      className="flex-1 flex items-center gap-2 truncate py-1"
                    >
                      <div className="w-2 h-2 rounded-full shrink-0 bg-neutral-300 dark:bg-neutral-600" />
                      <span className="truncate font-bold uppercase tracking-wider">{p.name} ({p.width_mm}mm)</span>
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        removeManualPrinter(p.address);
                        if (selectedPrinter === p.address) onSelect('', null);
                      }}
                      className="p-1.5 text-neutral-400 hover:text-red-500 transition-colors rounded shrink-0 ml-2"
                      title="Delete Profile"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {printers.length === 0 && manualPrinters.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-neutral-500 flex flex-col items-center gap-2">
                <PrinterIcon size={20} className="text-neutral-400 opacity-50" />
                <span>No printers found.<br />Scan or add a manual profile.</span>
              </div>
            )}

          </div>
        </div>
      )}
    </div>
  );
}

import React, { useState } from 'react';
import { X, Upload, ArrowRight } from 'lucide-react';
import { useStore } from '../store';
import { extractTemplateVariables, parseCsvRecords } from '../utils/batchData';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

export default function BatchPrintModal({ onClose }) {
  const dialogRef = useDialogAccessibility(onClose);
  const batchRecords = useStore(state => state.batchRecords);
  const items = useStore(state => state.items);
  const pageLayouts = useStore(state => state.pageLayouts);
  
  // Extract variables from the current canvas
  const canvasVariables = React.useMemo(() => {
    return extractTemplateVariables({ items, pageLayouts: pageLayouts || [] });
  }, [items, pageLayouts]);

  const hasExistingBatchRecords = Array.isArray(batchRecords) && (
    batchRecords.length > 1 ||
    (batchRecords.length === 1 && Object.keys(batchRecords[0] || {}).length > 0)
  );

  const [csvData, setCsvData] = useState([]);
  const [headers, setHeaders] = useState([]);
  const [mappingOverrides, setMappingOverrides] = useState({});
  const [fileError, setFileError] = useState('');

  const mapping = Object.fromEntries(canvasVariables.map((variable) => {
    const selected = mappingOverrides[variable] ?? (headers.includes(variable) ? variable : '');
    return [variable, headers.includes(selected) ? selected : ''];
  }));

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const parsed = parseCsvRecords(ev.target.result);
        setMappingOverrides({});
        setHeaders(parsed.headers);
        setCsvData(parsed.records);
        setFileError('');
      } catch (error) {
        setMappingOverrides({});
        setHeaders([]);
        setCsvData([]);
        setFileError(error.message);
      }
    };
    reader.onerror = () => setFileError('The CSV file could not be read.');
    reader.readAsText(file);
  };

  const handleApply = () => {
    if (csvData.length > 0) {
      // Map the data
      const mappedData = csvData.map(row => {
        const mappedRow = {};
        canvasVariables.forEach(v => {
          if (mapping[v]) {
            mappedRow[v] = row[mapping[v]] || '';
          }
        });
        return mappedRow;
      });
      useStore.getState().setBatchRecords(mappedData);
    } else if (!hasExistingBatchRecords) {
      useStore.getState().setBatchRecords([{}]);
    }
    onClose();
  };

  const handleClear = () => {
    useStore.getState().setBatchRecords([{}]);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Import batch data" tabIndex={-1} className="bg-white dark:bg-neutral-900 w-full max-w-md rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-lg dark:text-white">Import CSV Batch Data</h3>
          <button onClick={onClose} aria-label="Close batch import" className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>


        <div className="p-6 space-y-4 max-h-[60vh] overflow-y-auto">
          <label className="flex items-center justify-center w-full bg-neutral-50 dark:bg-neutral-950 border border-dashed border-neutral-300 dark:border-neutral-700 p-6 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-colors">
            <div className="text-center">
              <Upload className="mx-auto text-neutral-400 mb-2" size={24} />
              <span className="text-sm dark:text-white">Upload Variable Data (.CSV)</span>
            </div>
            <input type="file" accept=".csv" className="hidden" onClick={(e) => e.target.value = null} onChange={handleFileUpload} />
          </label>
          
          {headers.length > 0 && (
            <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded">
              <p className="text-xs text-green-600 font-bold mb-1">✓ File Registered ({csvData.length} records)</p>
            </div>
          )}

          {fileError && (
            <div role="alert" className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
              <p className="text-xs text-red-700 dark:text-red-400 font-bold">{fileError}</p>
            </div>
          )}

          {headers.length > 0 && canvasVariables.length > 0 && (
            <div className="mt-4 border border-neutral-200 dark:border-neutral-700 rounded overflow-hidden">
              <div className="bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-xs font-bold dark:text-neutral-300">
                Map CSV Columns to Canvas Variables
              </div>
              <div className="p-3 space-y-3 bg-neutral-50 dark:bg-neutral-900/50">
                {canvasVariables.map(v => (
                  <div key={v} className="flex items-center gap-2">
                    <div className="flex-1 text-xs font-bold text-neutral-700 dark:text-neutral-300 truncate" title={`{{ ${v} }}`}>
                      {`{{ ${v} }}`}
                    </div>
                    <ArrowRight size={14} className="text-neutral-400" />
                    <select
                      className="flex-1 bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-1.5 text-xs focus:outline-none focus:border-blue-500 dark:text-white"
                      value={mapping[v] || ''}
                      onChange={(e) => setMappingOverrides({ ...mappingOverrides, [v]: e.target.value })}
                    >
                      <option value="">-- Skip / Empty --</option>
                      {headers.map(h => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </div>
          )}

          {hasExistingBatchRecords && csvData.length === 0 && (
            <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded">
              <p className="text-xs text-blue-600 font-bold mb-1">ℹ Active Batch Data Detected</p>
              <p className="text-[10px] text-neutral-500">You currently have {batchRecords.length} records loaded.</p>
            </div>
          )}
        </div>

        <div className="flex gap-2 p-4 border-t border-neutral-100 dark:border-neutral-800 mt-auto shrink-0">
          {hasExistingBatchRecords && (
            <button 
              onClick={handleClear}
              className="w-1/3 bg-transparent border border-red-200 dark:border-red-900/50 text-red-600 px-4 py-3 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-xs uppercase tracking-widest font-bold"
            >
              Clear
            </button>
          )}
          <button 
            onClick={handleApply}
            disabled={csvData.length === 0}
            className="flex-1 bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold disabled:opacity-50"
          >
            Apply To Workspace
          </button>
        </div>

      </div>
    </div>
  );
}

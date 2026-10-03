import React, { lazy, Suspense, useMemo, useState } from 'react';
import { FileSpreadsheet, Plus, Trash2 } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../store';
import { extractTemplateVariables } from '../utils/batchData';

const BatchPrintModal = lazy(() => import('./BatchPrintModal'));

const inputClass = 'w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm text-neutral-900 dark:text-white focus:outline-hidden focus:border-blue-500 transition-colors';

export default function BatchDataPanel() {
  const {
    items, pageLayouts, batchRecords, setBatchRecords, updateBatchRecord,
    addBatchRecord, removeBatchRecord, generateBatchMatrix, generateBatchSequence,
    batchGenerationError, clearBatchGenerationError
  } = useStore(useShallow((state) => ({
    items: state.items,
    pageLayouts: state.pageLayouts,
    batchRecords: state.batchRecords,
    setBatchRecords: state.setBatchRecords,
    updateBatchRecord: state.updateBatchRecord,
    addBatchRecord: state.addBatchRecord,
    removeBatchRecord: state.removeBatchRecord,
    generateBatchMatrix: state.generateBatchMatrix,
    generateBatchSequence: state.generateBatchSequence,
    batchGenerationError: state.batchGenerationError,
    clearBatchGenerationError: state.clearBatchGenerationError
  })));
  const [showImport, setShowImport] = useState(false);
  const [mode, setMode] = useState('table');
  const [matrixInputs, setMatrixInputs] = useState({});
  const [sequence, setSequence] = useState({
    varName: '', start: 1, end: 10, prefix: '', suffix: '', padding: 3
  });

  const keys = useMemo(() => {
    const templateKeys = extractTemplateVariables({ items, pageLayouts });
    const recordKeys = batchRecords.flatMap((record) => Object.keys(record || {}));
    return Array.from(new Set([...templateKeys, ...recordKeys]));
  }, [batchRecords, items, pageLayouts]);

  const [previousKeys, setPreviousKeys] = useState(keys);
  if (previousKeys !== keys) {
    setPreviousKeys(keys);
    setMatrixInputs((previous) => Object.fromEntries(
      keys.map((key) => [key, previous[key] ?? ''])
    ));
  }

  const emptyRecord = () => Object.fromEntries(keys.map((key) => [key, '']));
  const modeButton = (buttonMode) => (
    `flex-1 py-2 text-[10px] uppercase font-bold tracking-widest transition-colors border ${
      mode === buttonMode
        ? 'bg-blue-50 border-blue-200 text-blue-600 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400'
        : 'bg-neutral-50 border-transparent text-neutral-500 dark:bg-neutral-900'
    }`
  );

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Variable Data</h2>
      <p className="text-[10px] text-neutral-500 mb-2 leading-relaxed">
        Variables replace matching <code>{'{{ variable }}'}</code> tags on the canvas. Each row represents one printed label.
      </p>

      <div className="flex gap-2 mb-4" role="tablist" aria-label="Batch data editor mode">
        <button type="button" role="tab" aria-selected={mode === 'table'} onClick={() => setMode('table')} className={modeButton('table')}>Table</button>
        <button type="button" role="tab" aria-selected={mode === 'matrix'} onClick={() => setMode('matrix')} className={modeButton('matrix')}>Permutations</button>
        <button type="button" role="tab" aria-selected={mode === 'sequence'} onClick={() => setMode('sequence')} className={modeButton('sequence')}>Sequence</button>
      </div>

      {batchGenerationError && (
        <div role="alert" className="flex items-start justify-between gap-3 border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          <span>{batchGenerationError}</span>
          <button type="button" onClick={clearBatchGenerationError} className="font-bold" aria-label="Dismiss batch error">×</button>
        </div>
      )}

      <div className="flex gap-2 mb-2">
        <button type="button" onClick={() => setShowImport(true)} className="flex-1 flex items-center justify-center gap-2 py-1.5 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-600 dark:text-neutral-300 text-[10px] uppercase font-bold tracking-widest transition-colors">
          <FileSpreadsheet size={14} /> Import CSV
        </button>
        <button type="button" onClick={() => setBatchRecords([emptyRecord()])} aria-label="Clear all batch data" className="px-3 py-1.5 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors">
          <Trash2 size={14} />
        </button>
      </div>

      {keys.length === 0 && (
        <div className="text-center p-4 border border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-400 text-xs">
          No variables detected on canvas.<br /><br />Add a text element containing a tag like <code>{'{{ name }}'}</code> to get started.
        </div>
      )}

      {keys.length > 0 && mode === 'table' && (
        <div className="w-full overflow-x-auto border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-left text-xs whitespace-nowrap">
            <thead className="bg-neutral-100 dark:bg-neutral-900 text-[10px] uppercase tracking-wider text-neutral-500">
              <tr>
                <th className="p-2 font-bold w-8 text-center">#</th>
                {keys.map((key) => <th key={key} className="p-2 font-bold border-l border-neutral-200 dark:border-neutral-800">{key}</th>)}
                <th className="p-2 w-8"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800 bg-white dark:bg-neutral-950">
              {batchRecords.map((record, index) => (
                <tr key={index} className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50">
                  <td className="p-2 text-center text-neutral-400">{index + 1}</td>
                  {keys.map((key) => (
                    <td key={key} className="border-l border-neutral-200 dark:border-neutral-800 p-0">
                      <input
                        type="text"
                        aria-label={`Row ${index + 1}, ${key}`}
                        value={record[key] || ''}
                        onChange={(event) => updateBatchRecord(index, { ...record, [key]: event.target.value })}
                        className="w-full h-full p-2 bg-transparent focus:outline-hidden focus:bg-blue-50 dark:focus:bg-blue-900/20 dark:text-white transition-colors"
                      />
                    </td>
                  ))}
                  <td className="p-1 border-l border-neutral-200 dark:border-neutral-800">
                    <button type="button" aria-label={`Remove row ${index + 1}`} onClick={() => removeBatchRecord(index)} className="w-full h-full p-1 text-neutral-400 hover:text-red-500 flex justify-center items-center">
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" onClick={() => addBatchRecord(emptyRecord())} className="w-full flex justify-center items-center gap-2 py-2 bg-neutral-50 dark:bg-neutral-900 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors text-[10px] uppercase tracking-widest font-bold">
            <Plus size={14} /> Add Row
          </button>
        </div>
      )}

      {keys.length > 0 && mode === 'matrix' && (
        <div className="space-y-3 p-4 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
          <p className="text-[10px] text-neutral-500 mb-2 leading-relaxed">Enter comma-separated values for each variable to generate their Cartesian product.</p>
          {keys.map((key) => (
            <div key={key}>
              <label className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1 block" htmlFor={`matrix-${key}`}>{key} (comma separated)</label>
              <input id={`matrix-${key}`} type="text" value={matrixInputs[key] || ''} onChange={(event) => setMatrixInputs((previous) => ({ ...previous, [key]: event.target.value }))} className={inputClass} placeholder="e.g. item 1, item 2" />
            </div>
          ))}
          <button type="button" onClick={() => { if (generateBatchMatrix(matrixInputs)) setMode('table'); }} className="w-full mt-2 py-2 bg-blue-600 text-white hover:bg-blue-700 text-[10px] uppercase tracking-widest font-bold">Generate Combinations</button>
        </div>
      )}

      {keys.length > 0 && mode === 'sequence' && (
        <div className="space-y-3 p-4 border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
          <p className="text-[10px] text-neutral-500">Generate serialized values such as asset tags and barcodes.</p>
          <label className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider block" htmlFor="sequence-variable">Target Variable</label>
          <select id="sequence-variable" value={sequence.varName} onChange={(event) => setSequence({ ...sequence, varName: event.target.value })} className={inputClass}>
            <option value="" disabled>Select variable…</option>
            {keys.map((key) => <option key={key} value={key}>{key}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-2">
            {['prefix', 'suffix', 'start', 'end', 'padding'].map((field) => (
              <label key={field} className="text-[10px] font-bold text-neutral-500 uppercase">
                {field === 'padding' ? '0-Pad' : field}
                <input
                  type={['start', 'end', 'padding'].includes(field) ? 'number' : 'text'}
                  min={field === 'padding' ? 0 : undefined}
                  max={field === 'padding' ? 10 : undefined}
                  value={sequence[field]}
                  onChange={(event) => setSequence({ ...sequence, [field]: event.target.value })}
                  className={`${inputClass} mt-1 normal-case`}
                />
              </label>
            ))}
          </div>
          <button type="button" disabled={!sequence.varName} onClick={() => { if (generateBatchSequence(sequence)) setMode('table'); }} className="w-full mt-2 py-2 bg-blue-600 text-white hover:bg-blue-700 text-[10px] uppercase tracking-widest font-bold disabled:opacity-50">Generate Sequence</button>
        </div>
      )}

      <Suspense fallback={null}>
        {showImport && <BatchPrintModal onClose={() => setShowImport(false)} />}
      </Suspense>
    </div>
  );
}

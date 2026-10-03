import React, { useId } from 'react';
import { useStore } from '../../store';
import { useShallow } from 'zustand/react/shallow';
import { inputClass, labelClass } from './styles';
import { MmScrubberInput, ScrubberInput } from '../NumericInput';

export default function CanvasSettings({ multCopies, setMultCopies }) {
  const { canvasWidth, canvasHeight, canvasBorder, setCanvasBorder, canvasBorderThickness, setCanvasBorderThickness, setCanvasGeometry, getMmToPx, isRotated, setIsRotated, splitMode, setSplitMode, selectedPrinterInfo } = useStore(useShallow(state => ({
    canvasWidth: state.canvasWidth,
    canvasHeight: state.canvasHeight,
    canvasBorder: state.canvasBorder,
    setCanvasBorder: state.setCanvasBorder,
    canvasBorderThickness: state.canvasBorderThickness,
    setCanvasBorderThickness: state.setCanvasBorderThickness,
    setCanvasGeometry: state.setCanvasGeometry,
    getMmToPx: state.getMmToPx,
    isRotated: state.isRotated,
    setIsRotated: state.setIsRotated,
    splitMode: state.splitMode,
    setSplitMode: state.setSplitMode,
    selectedPrinterInfo: state.selectedPrinterInfo,
  })));
  const tabId = useId();
  const isPreCut = selectedPrinterInfo?.media_type === 'pre-cut';
  return <>
    <div className="space-y-4">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Dimensions</h2>

      <label className={`flex items-center gap-2 text-[10px] uppercase font-bold mt-2 cursor-pointer border px-3 py-2 rounded w-full transition-colors ${
        isPreCut
          ? 'text-neutral-400 border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 opacity-60 cursor-not-allowed'
          : 'text-red-600 dark:text-red-400 border-red-200 dark:border-red-900/30 bg-red-50 dark:bg-red-950/20 hover:bg-red-100 dark:hover:bg-red-900/40'
      }`}>
        <input
          type="checkbox"
          checked={splitMode || false}
          onChange={(e) => !isPreCut && setSplitMode(e.target.checked)}
          disabled={isPreCut}
        />
        Oversize / Split Print Mode {isPreCut && '(Disabled for Pre-cut Media)'}
      </label>

      {splitMode && !isPreCut && (
        <div className="flex gap-2 mt-2">
          <button onClick={() => setCanvasGeometry(getMmToPx(105), getMmToPx(148), false)} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A6</button>
          <button onClick={() => setCanvasGeometry(getMmToPx(148), getMmToPx(210), false)} className="flex-1 py-2 bg-neutral-100 dark:bg-neutral-900 text-[10px] font-bold uppercase hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">A5</button>
        </div>
      )}

      <div className="flex gap-4 items-center">
        <label className="flex items-center gap-2 text-xs font-bold text-neutral-600 dark:text-neutral-400 mt-2 cursor-pointer border px-3 py-2 border-neutral-200 dark:border-neutral-800 rounded-sm hover:bg-neutral-50 dark:hover:bg-neutral-900 w-full">
          <input type="checkbox" checked={isRotated} onChange={(e) => setIsRotated(e.target.checked)} />
          Rotate Feed (Landscape View)
        </label>
      </div>
      <div className="flex gap-4">
        <MmScrubberInput
          name="width"
          label={isRotated ? "Paper Length" : "Print Width"}
          value={canvasWidth}
          onChange={(e) => setCanvasGeometry(Number(e.target.value), canvasHeight, isRotated)}
          disabled={!isRotated}
        />
        <MmScrubberInput
          name="height"
          label={isRotated ? "Print Width" : "Paper Length"}
          value={canvasHeight}
          onChange={(e) => setCanvasGeometry(canvasWidth, Number(e.target.value), isRotated)}
          disabled={isRotated}
        />
      </div>
    </div>

    <div className="space-y-4 mt-4">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Canvas Styling</h2>
      <div className="flex gap-4">
        <div className="flex flex-col justify-end flex-1">
          <label className={labelClass} title="Canvas Border / Cut line" htmlFor={`${tabId}-canvas-border`}>Canvas Border</label>
          <select id={`${tabId}-canvas-border`} value={canvasBorder} onChange={(e) => setCanvasBorder(e.target.value)} className={inputClass}>
            <option value="none">None</option>
            <option value="box">Full Box</option>
            <option value="top">Top Border</option>
            <option value="bottom">Bottom Border</option>
            <option value="cut_line">Cut Line (Dashed Bottom)</option>
          </select>
        </div>
        <ScrubberInput
          name="canvasBorderThickness"
          label="Thickness"
          value={canvasBorderThickness || 4}
          onChange={(e) => setCanvasBorderThickness(Number(e.target.value))}
        />
      </div>
    </div>


    <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Duplicate Label</h2>
      <p className="text-[11px] text-neutral-600 dark:text-neutral-300">Easily create identical copies of this label as new pages.</p>
      <div className="flex gap-4">
        <div className="flex-1">
          <label className="block text-[10px] text-neutral-600 dark:text-neutral-300 font-bold uppercase mb-1" htmlFor={`${tabId}-page-copies`}>Copies to Add</label>
          <input id={`${tabId}-page-copies`} type="number" min="1" value={multCopies} onChange={e => setMultCopies(parseInt(e.target.value) || 1)} className={inputClass} />
        </div>
      </div>
      <button onClick={() => useStore.getState().multiplyWorkspace(multCopies)} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
        Duplicate Page
      </button>
    </div>

  </>;
}

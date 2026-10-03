import React, { useId, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useShallow } from 'zustand/react/shallow';
import { inputClass, labelClass } from './styles';
import { apiJson } from '../../utils/apiClient';
import { isPrinterProfile } from '../../domain/printer';

const profileSnapshot = profile => JSON.stringify([profile?.speed, profile?.energy, profile?.feed_lines, profile?.paper_mode || null]);

export default function PrinterSettings() {
  const { selectedPrinter, selectedPrinterInfo, printerProfile, dither, setDither, canvasWidth, canvasHeight, setCanvasGeometry, getMmToPx, getPxToMm, isRotated } = useStore(useShallow(state => ({
    selectedPrinter: state.selectedPrinter,
    selectedPrinterInfo: state.selectedPrinterInfo,
    printerProfile: state.printerProfile,
    dither: state.dither,
    setDither: state.setDither,
    canvasWidth: state.canvasWidth,
    canvasHeight: state.canvasHeight,
    setCanvasGeometry: state.setCanvasGeometry,
    getMmToPx: state.getMmToPx,
    getPxToMm: state.getPxToMm,
    isRotated: state.isRotated,
  })));
  const tabId = useId();
  const pInfo = selectedPrinterInfo || {};
  const caps = pInfo.capabilities || {};
  const supportedPaperModes = Array.isArray(pInfo.supported_paper_modes) ? pInfo.supported_paper_modes : [];
  const maxSpeed = caps.speed?.max || 100;
  const minEnergy = caps.energy?.min || 1000;
  const maxEnergy = caps.energy?.max || 65535;
  const minDensity = caps.density?.min ?? 1;
  const maxDensity = caps.density?.max ?? 5;
  const allowsAutomaticDensity = Boolean(caps.density?.allow_auto);
  const usesRawDensity = caps.density?.scale === 'raw';
  const recommendedMinDensity = caps.density?.recommended_min;
  const recommendedMaxDensity = caps.density?.recommended_max;

  const request = useRef(0);
  const [save, setSave] = useState({ status: 'idle' });
  const samePrinter = save.printer === selectedPrinter;
  const isSaving = samePrinter && save.status === 'saving';
  const snapshot = profileSnapshot(printerProfile);
  const handleProfileChange = (e) => {
    const { name, value } = e.target;
    if (name === 'paper_mode') {
      useStore.setState((state) => ({
        printerProfile: {
          ...state.printerProfile,
          paper_mode: value || null
        }
      }));
      return;
    }

    const rawValue = Number(value);

    let nextValue = Number.isFinite(rawValue) ? rawValue : 0;

    if (name === 'speed') {
      nextValue = Math.max(0, Math.min(nextValue, maxSpeed));
    } else if (name === 'energy') {
      nextValue = caps.density?.available
        ? Math.max(allowsAutomaticDensity ? 0 : minDensity, Math.min(nextValue, maxDensity))
        : Math.max(0, Math.min(nextValue, maxEnergy));
    } else if (name === 'feed_lines') {
      nextValue = Math.max(0, nextValue);
    }

    useStore.setState((state) => ({
      printerProfile: {
        ...state.printerProfile,
        [name]: nextValue
      }
    }));
  };

  const handleSaveProfile = async () => {
    if (!selectedPrinter || isSaving) return;
    const id = ++request.current;
    const printer = selectedPrinter;
    const profile = { ...useStore.getState().printerProfile };
    setSave({ status: 'saving', printer });
    try {
      const result = await apiJson(`/api/printers/${printer}/profile`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...profile, paper_mode: profile.paper_mode || '' })
      }, { validate: isPrinterProfile });
      if (request.current === id) setSave({ status: 'saved', printer, snapshot: profileSnapshot(result) });
    } catch (error) {
      if (request.current === id) setSave({ status: 'failed', printer, error: error.message || 'Failed to save the printer profile.' });
    }
  };
  return <>
    <div className="space-y-4 mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
      <h2 className="text-lg font-serif tracking-tight text-neutral-900 dark:text-white pb-2 border-b border-neutral-100 dark:border-neutral-800">Printer Config</h2>

      <div className="text-xs text-blue-600 dark:text-blue-400 mb-2">
        {selectedPrinter
          ? `Hardware Defaults: Speed ${caps.speed?.default ?? 'Auto'}, ${caps.density?.available ? 'Density' : 'Energy'} ${caps.density?.available ? (caps.density.default || 'Auto') : (caps.energy?.default || 'Auto')}`
          : 'Select a printer to configure device-specific overrides.'}
      </div>

      <div>
        <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 dark:text-neutral-400 cursor-pointer border px-3 py-2 border-neutral-200 dark:border-neutral-800 rounded-sm hover:bg-neutral-50 dark:hover:bg-neutral-900 w-full mb-4">
          <input type="checkbox" checked={dither} onChange={(e) => setDither(e.target.checked)} />
          Enable Dithering (Best for Photos)
        </label>
      </div>

      {pInfo.media_type === 'continuous' && pInfo.protocol_family?.includes('p12') && (
        <div className="mb-4 p-3 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-sm">
          <label className={labelClass}>Adjust Tape Length</label>
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={() => setCanvasGeometry(Math.max(getMmToPx(5), canvasWidth - getMmToPx(5)), canvasHeight, isRotated)}
              className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded-sm text-lg font-bold dark:text-white"
            >
              -
            </button>
            <span className="flex-1 text-center text-xs font-bold dark:text-neutral-300">
              {parseFloat(getPxToMm(canvasWidth)).toFixed(0)} mm
            </span>
            <button
              onClick={() => setCanvasGeometry(canvasWidth + getMmToPx(5), canvasHeight, isRotated)}
              className="w-8 h-8 flex items-center justify-center bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors rounded-sm text-lg font-bold dark:text-white"
            >
              +
            </button>
          </div>
        </div>
      )}

      {caps.density?.available && (
        <div>
          <label className={labelClass} htmlFor={`${tabId}-density`}>
            {usesRawDensity ? 'Print Density Override' : 'Print Darkness'} ({minDensity} - {maxDensity})
          </label>
          {usesRawDensity ? (
            <input id={`${tabId}-density`}
              type="number"
              name="energy"
              min={allowsAutomaticDensity ? 0 : minDensity}
              max={maxDensity}
              step={1}
              value={printerProfile?.energy ?? (allowsAutomaticDensity ? 0 : caps.density.default ?? minDensity)}
              onChange={handleProfileChange}
              disabled={!selectedPrinter}
              className={inputClass}
            />
          ) : (
            <select id={`${tabId}-density`}
              name="energy"
              value={printerProfile?.energy ?? caps.density.default ?? 3}
              onChange={handleProfileChange}
              disabled={!selectedPrinter}
              className={inputClass}
            >
              {Array.from({ length: Math.max(0, maxDensity - minDensity + 1) }, (_, i) => minDensity + i).map((level) => (
                <option key={level} value={level}>
                  {level} - {level <= 2 ? 'Light' : level >= (maxDensity - 1) ? 'Dark' : 'Normal'}
                </option>
              ))}
            </select>
          )}
          {usesRawDensity && (
            <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1">
              {allowsAutomaticDensity ? `0 = Auto${caps.density.default != null ? ` (${caps.density.default})` : ''}. ` : ''}
              Protocol range: {minDensity} - {maxDensity}.
              {recommendedMinDensity != null && recommendedMaxDensity != null
                ? ` Model-tuned range: ${recommendedMinDensity} - ${recommendedMaxDensity}.`
                : ' This model has no published tuned range.'}
              {' '}Thermal protection may reduce the effective density while the print head is hot.
            </p>
          )}
        </div>
      )}

      {caps.speed?.available && (
        <div>
          <label className={labelClass} htmlFor={`${tabId}-speed`}>Speed Override (0 = Auto)</label>
          <input id={`${tabId}-speed`}
            type="number"
            name="speed"
            min={0}
            max={maxSpeed}
            value={printerProfile?.speed || 0}
            onChange={handleProfileChange}
            disabled={!selectedPrinter}
            className={inputClass}
          />
          <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1">
            {pInfo.model ? `Hardware Default: ${caps.speed.default || 0}. Max: ${maxSpeed}.` : 'Select a printer to view limits.'}
          </p>
        </div>
      )}

      {caps.energy?.available && (
        <div>
          <label className={labelClass} htmlFor={`${tabId}-energy`}>Energy Override (0 = Auto)</label>
          <input id={`${tabId}-energy`}
            type="number"
            name="energy"
            min={0}
            max={maxEnergy}
            step={caps.energy.step || 500}
            value={printerProfile?.energy || 0}
            onChange={handleProfileChange}
            disabled={!selectedPrinter}
            className={inputClass}
          />
          <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1">
            {pInfo.model ? `Safe Range: ${minEnergy} - ${maxEnergy}. Default: ${caps.energy.default || 5000}.` : 'Select a printer to view limits.'}
          </p>
        </div>
      )}

      {caps.feed?.available && (
        <div>
          <label className={labelClass} htmlFor={`${tabId}-feed`}>Feed Lines (Tear Padding)</label>
          <input id={`${tabId}-feed`}
            type="number"
            name="feed_lines"
            min={0}
            value={printerProfile?.feed_lines ?? (caps.feed.default || 50)}
            onChange={handleProfileChange}
            disabled={!selectedPrinter}
            className={inputClass}
          />
        </div>
      )}

      {supportedPaperModes.length > 0 && (
        <div>
          <label className={labelClass} htmlFor={`${tabId}-paper-mode`}>Paper Mode</label>
          <select id={`${tabId}-paper-mode`}
            name="paper_mode"
            value={printerProfile?.paper_mode || supportedPaperModes[0]?.value || ''}
            onChange={handleProfileChange}
            disabled={!selectedPrinter}
            className={inputClass}
          >
            {supportedPaperModes.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label || mode.value}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-neutral-600 dark:text-neutral-300 mt-1">
            Controls media alignment for printers whose firmware supports labels, marks, folders, or tattoo paper.
          </p>
        </div>
      )}

      <p role="status" aria-live="polite">{samePrinter && save.status === 'saved' && snapshot === save.snapshot ? 'Printer settings saved.' : samePrinter && save.status === 'saved' ? 'Printer settings changed since the last save.' : ''}</p>
      {samePrinter && save.status === 'failed' && <p role="alert" className="text-sm text-red-800 dark:text-red-300">{save.error}</p>}
      <button
        onClick={handleSaveProfile}
        disabled={isSaving || !selectedPrinter}
        className={`w-full mt-4 py-3 rounded-none transition-colors text-xs uppercase tracking-widest font-bold border
          ${isSaving
            ? 'bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-300 border-neutral-300 dark:border-neutral-700'
            : 'bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 border-transparent hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed'}`}
      >
        {isSaving ? 'Saving printer settings…' : 'Save Printer Settings'}
      </button>
    </div>

  </>;
}

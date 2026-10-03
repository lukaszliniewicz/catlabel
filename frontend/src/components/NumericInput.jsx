import React, { useId, useRef } from 'react';
import { useStore } from '../store';

function NumericInput({ name, value, onChange, label, disabled = false, step = 0.5, dragMultiplier = 0.5, toModel = value => value, displayValue = value }) {
  const id = useId();
  const drag = useRef(null);
  const numericValue = Number(displayValue);
  const emit = next => onChange({ target: { name, value: toModel(next), type: 'number' } });
  const endDrag = event => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <div className="min-w-0 flex-1">
    <label htmlFor={id} className={`mb-1.5 flex min-h-6 items-center text-[10px] font-bold uppercase tracking-widest ${disabled ? 'text-neutral-500' : 'cursor-ew-resize text-neutral-600 dark:text-neutral-300 hover:text-blue-600'}`}
      style={{ touchAction: disabled ? 'auto' : 'none' }} title={disabled ? 'Locked' : 'Drag left/right to adjust; type or use arrow keys in the field'}
      onPointerDown={event => {
        if (disabled || (event.pointerType === 'mouse' && event.button !== 0)) return;
        drag.current = { pointerId: event.pointerId, x: event.clientX, value: Number.isFinite(numericValue) ? numericValue : 0 };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }}
      onPointerMove={event => {
        const start = drag.current;
        if (!start || start.pointerId !== event.pointerId) return;
        const factor = 1 / step;
        const next = Math.max(0, Math.round((start.value + (event.clientX - start.x) * dragMultiplier) * factor) / factor);
        emit(next);
      }} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={() => { drag.current = null; }}>
      {label}<span aria-hidden="true" className="ml-1">{disabled ? '🔒' : '⇹'}</span>
    </label>
    <input id={id} type="number" step={step} name={name} disabled={disabled}
      value={Number.isFinite(numericValue) ? numericValue : ''}
      onChange={event => { const next = Number.parseFloat(event.target.value); if (Number.isFinite(next)) emit(next); }}
      className="min-h-11 w-full border border-neutral-400 bg-transparent p-2 text-sm text-neutral-900 focus:border-blue-600 focus:outline-2 focus:outline-blue-600 disabled:opacity-60 dark:border-neutral-600 dark:text-white" />
  </div>;
}

export function MmScrubberInput(props) {
  const getPxToMm = useStore(state => state.getPxToMm);
  const getMmToPx = useStore(state => state.getMmToPx);
  return <NumericInput {...props} label={`${props.label} (mm)`} step={0.1} displayValue={Number(getPxToMm(props.value))} toModel={getMmToPx} />;
}

export function ScrubberInput(props) { return <NumericInput {...props} />; }

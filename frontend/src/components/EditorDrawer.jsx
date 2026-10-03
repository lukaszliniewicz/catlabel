import React from 'react';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

export default function EditorDrawer({ label, side = 'right', width = 360, onClose, children }) {
  const ref = useDialogAccessibility(onClose);
  return <div className="fixed inset-0 z-40 bg-black/50" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={ref} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}
      className={`absolute inset-y-0 flex flex-col bg-white shadow-2xl dark:bg-neutral-950 ${side === 'left' ? 'left-0' : 'right-0'}`}
      style={{ width, maxWidth: 'calc(100vw - 32px)' }}>
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-neutral-300 px-4 py-2 dark:border-neutral-700">
        <h2 className="text-sm font-semibold">{label}</h2>
        <button type="button" data-dialog-initial-focus onClick={onClose} aria-label={`Close ${label.toLowerCase()}`} className="min-h-10 min-w-10 rounded-sm border border-neutral-400 px-3">×</button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </section>
  </div>;
}

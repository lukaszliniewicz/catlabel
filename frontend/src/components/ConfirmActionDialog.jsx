import React, { useId } from 'react';
import { createPortal } from 'react-dom';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

export default function ConfirmActionDialog({ title, message, actionLabel, cancelLabel = 'Cancel', busy = false, error = '', onClose, onConfirm, returnFocusRef }) {
  const id = useId();
  const ref = useDialogAccessibility(busy ? null : onClose, { returnFocusRef });
  return createPortal(<div className="fixed inset-0 z-10000 flex items-center justify-center bg-black/60 p-4">
    <section ref={ref} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} tabIndex={-1}
      className="w-full max-w-md rounded-lg border border-neutral-300 bg-white p-6 text-neutral-900 shadow-xl dark:border-neutral-700 dark:bg-neutral-950 dark:text-white">
      <h2 id={`${id}-title`} className="text-xl font-semibold">{title}</h2>
      <p id={`${id}-description`} className="mt-3 text-sm">{message}</p>
      {error && <p role="alert" className="mt-3 text-sm text-red-800 dark:text-red-300">{error}</p>}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <button type="button" data-dialog-initial-focus disabled={busy} onClick={onClose} className="min-h-11 border border-neutral-500 px-4 py-2 text-sm disabled:opacity-50">{cancelLabel}</button>
        <button type="button" disabled={busy} onClick={onConfirm} className="min-h-11 bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? 'Working…' : actionLabel}</button>
      </div>
    </section>
  </div>, document.body);
}

import React from 'react';
import { createPortal } from 'react-dom';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

export default function ProjectActionsDialog({ name, coordinates, onClose, returnFocusRef, children }) {
  const ref = useDialogAccessibility(onClose, { returnFocusRef });
  return createPortal(<div className="fixed inset-0 z-9998" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={ref} role="dialog" aria-modal="true" aria-label={`Actions for ${name}`} tabIndex={-1}
      className="fixed flex w-48 flex-col overflow-y-auto rounded-md border border-neutral-300 bg-white py-1 text-neutral-900 shadow-xl dark:border-neutral-700 dark:bg-neutral-900 dark:text-white"
      style={{ top: coordinates.top ?? undefined, bottom: coordinates.bottom ?? undefined, left: coordinates.left, maxHeight: coordinates.maxHeight }}>
      <button type="button" data-dialog-initial-focus onClick={onClose} className="min-h-11 border-b border-neutral-200 px-3 py-2 text-left text-xs dark:border-neutral-700">Close actions</button>
      {children}
    </section>
  </div>, document.body);
}

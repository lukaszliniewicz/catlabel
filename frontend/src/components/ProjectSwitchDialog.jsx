import React from 'react';
import { useStore } from '../store';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';

export default function ProjectSwitchDialog() {
  const pending = useStore(state => state.pendingProjectLoad);
  const cancel = useStore(state => state.cancelProjectLoad);
  const confirm = useStore(state => state.confirmProjectLoad);
  const dialogRef = useDialogAccessibility(cancel);
  return (
    <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/60 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="project-switch-title"
        aria-describedby="project-switch-description" tabIndex={-1}
        className="w-full max-w-md rounded-lg border border-neutral-300 bg-white p-6 shadow-xl dark:border-neutral-700 dark:bg-neutral-950">
        <h2 id="project-switch-title" className="text-xl font-semibold">Open another project?</h2>
        <p id="project-switch-description" className="mt-3 text-sm">Opening {pending?.summary.name || 'this project'} will replace your unsaved edits. Keep editing and save first if you want to retain them.</p>
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button type="button" data-dialog-initial-focus onClick={cancel} className="border border-neutral-500 px-4 py-3 text-sm">Keep editing</button>
          <button type="button" onClick={confirm} className="bg-blue-700 px-4 py-3 text-sm font-semibold text-white">Discard edits and open</button>
        </div>
      </div>
    </div>
  );
}

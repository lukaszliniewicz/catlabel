import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../store';
import HeadlessPage from './HeadlessPage';
import { useDialogAccessibility } from '../utils/useDialogAccessibility';
import { usePreparedPrintSession } from '../rendering/usePreparedPrintSession';

export default function LocalBatchRenderer({ onComplete }) {
  const pendingPrintJob = useStore((state) => state.pendingPrintJob);
  return pendingPrintJob
    ? <LocalBatchJob key={pendingPrintJob.id} pendingPrintJob={pendingPrintJob} onComplete={onComplete} />
    : null;
}

function LocalBatchJob({ pendingPrintJob, onComplete }) {
  const [completedCount, setCompletedCount] = useState(0);
  const [currentIndex, setCurrentIndex] = useState(0);
  const uploadTaskRef = useRef(null);
  const queuedIndexRef = useRef(-1);
  const completedRef = useRef(false);
  useEffect(() => {
    completedRef.current = false;
    return () => {
      completedRef.current = true;
    };
  }, []);

  const jobs = useMemo(() => {
    if (!pendingPrintJob) return [];

    const variablesCollection = pendingPrintJob.batchRecords?.length
      ? pendingPrintJob.batchRecords
      : [{}];
    const copies = Math.max(1, Number(pendingPrintJob.copies) || 1);
    const pageIndices = (pendingPrintJob.pageIndices?.length
      ? pendingPrintJob.pageIndices
      : [0]).map((pageIndex) => Math.max(0, Number(pageIndex) || 0));

    const nextJobs = [];
    variablesCollection.forEach((record, recordIndex) => {
      for (let copyIndex = 0; copyIndex < copies; copyIndex += 1) {
        pageIndices.forEach((pageIndex) => {
          nextJobs.push({
            id: `local-${recordIndex}-${copyIndex}-${pageIndex}`,
            record,
            pageIndex
          });
        });
      }
    });

    return nextJobs;
  }, [pendingPrintJob]);



  useEffect(() => {
    if (pendingPrintJob && jobs.length === 0) {
      onComplete([], null, pendingPrintJob.id);
    }
  }, [jobs.length, onComplete, pendingPrintJob]);

  const preparation = usePreparedPrintSession(jobs.length);
  const { ready, error: preparationError, upload, handOff, cancel, rejectHandOff } = preparation;

  const handlePageError = useCallback((error) => {
    if (completedRef.current) return;
    completedRef.current = true;
    cancel();
    onComplete([], error, pendingPrintJob.id);
  }, [cancel, onComplete, pendingPrintJob.id]);

  useEffect(() => { if (preparationError) handlePageError(preparationError); }, [handlePageError, preparationError]);

  const handlePageReady = useCallback((b64) => {
    if (completedRef.current || currentIndex <= queuedIndexRef.current) return undefined;
    const index = currentIndex;
    queuedIndexRef.current = index;
    const previous = uploadTaskRef.current;
    // One upload and one rendered successor may coexist; uploads remain ordered.
    const sendPage = async () => {
      if (completedRef.current) return;
      const sending = upload(b64, index);
      if (index + 1 < jobs.length) setCurrentIndex(index + 1);
      await sending;
      if (completedRef.current) return;
      const nextCount = index + 1;
      setCompletedCount(nextCount);
      if (nextCount === jobs.length) {
        const receipt = handOff();
        completedRef.current = true;
        const accepted = await onComplete(receipt, null, pendingPrintJob.id);
        if (accepted === false) rejectHandOff();
      }
    };
    const task = (previous ? previous.then(sendPage) : sendPage()).catch(error => {
      if (completedRef.current) rejectHandOff();
      else handlePageError(error);
    }).finally(() => {
      if (uploadTaskRef.current === task) uploadTaskRef.current = null;
    });
    uploadTaskRef.current = task;
    return task;
  }, [currentIndex, handlePageError, handOff, jobs.length, onComplete, pendingPrintJob.id, rejectHandOff, upload]);

  const cancelPreparation = useCallback(() => {
    handlePageError(new Error('Print preparation cancelled before submission.'));
  }, [handlePageError]);
  const dialogRef = useDialogAccessibility(cancelPreparation);

  if (!pendingPrintJob || jobs.length === 0) {
    return null;
  }

  const progressPercent = jobs.length
    ? Math.round((completedCount / jobs.length) * 100)
    : 0;
  const activeJob = jobs[currentIndex];

  return (
    <div className="fixed inset-0 bg-black/80 z-200 flex flex-col items-center justify-center backdrop-blur-md">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Preparing labels" tabIndex={-1} className="bg-white dark:bg-neutral-900 p-6 sm:p-8 rounded-xl shadow-2xl text-center border border-neutral-200 dark:border-neutral-800 w-full max-w-sm">
        <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <h3 className="text-lg font-serif dark:text-white">Preparing Labels</h3>
        <p role="status" aria-live="polite" aria-busy="true" className="text-sm text-neutral-500 mt-2">
          Preparing {completedCount} of {jobs.length}...
        </p>
        <div role="progressbar" aria-label="Label rendering progress" aria-valuemin={0} aria-valuemax={jobs.length} aria-valuenow={completedCount} className="mt-4 h-2 w-full bg-neutral-200 dark:bg-neutral-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-200"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <button type="button" data-dialog-initial-focus onClick={cancelPreparation} className="mt-6 border border-neutral-500 px-4 py-3 text-sm">Cancel preparation</button>
        <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">No labels have been submitted while this preparation screen is open.</p>
      </div>

      <div style={{ position: 'absolute', top: '-9999px', left: '-9999px', pointerEvents: 'none' }}>
        {activeJob && ready && (
          <HeadlessPage
            key={activeJob.id}
            state={pendingPrintJob.canvasState}
            record={activeJob.record}
            pageIndex={activeJob.pageIndex}
            onReady={handlePageReady}
            onError={handlePageError}
          />
        )}
      </div>
    </div>
  );
}

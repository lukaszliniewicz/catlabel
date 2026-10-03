import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../store';
import HeadlessPage from './HeadlessPage';
import { usePreparedPrintSession } from '../rendering/usePreparedPrintSession';

export default function LocalBatchRenderer({ onComplete }) {
  const pendingPrintJob = useStore((state) => state.pendingPrintJob);
  return pendingPrintJob
    ? <LocalBatchJob key={pendingPrintJob.id} pendingPrintJob={pendingPrintJob} onComplete={onComplete} />
    : null;
}

function LocalBatchJob({ pendingPrintJob, onComplete }) {
  const reportProgress = useStore(state => state.reportPrintPreparation);
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
      reportProgress(pendingPrintJob.id, nextCount);
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
  }, [currentIndex, handlePageError, handOff, jobs.length, onComplete, pendingPrintJob.id, rejectHandOff, reportProgress, upload]);

  if (!pendingPrintJob || jobs.length === 0) {
    return null;
  }

  const activeJob = jobs[currentIndex];

  return (
      <div aria-hidden="true" style={{ position: 'absolute', top: '-9999px', left: '-9999px', pointerEvents: 'none' }}>
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
  );
}

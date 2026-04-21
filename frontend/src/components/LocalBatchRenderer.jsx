import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useStore } from '../store';
import HeadlessPage from './HeadlessPage';

export default function LocalBatchRenderer({ onComplete }) {
  const pendingPrintJob = useStore((state) => state.pendingPrintJob);
  const [results, setResults] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);

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
    setResults([]);
    setCurrentIndex(0);
  }, [jobs, pendingPrintJob]);

  useEffect(() => {
    if (pendingPrintJob && jobs.length === 0) {
      onComplete([]);
    }
  }, [jobs.length, onComplete, pendingPrintJob]);

  const handlePageReady = useCallback((b64) => {
    setResults((prev) => {
      const next = [...prev, b64];

      if (next.length === jobs.length) {
        onComplete(next);
      } else {
        window.setTimeout(() => {
          setCurrentIndex((idx) => idx + 1);
        }, 50);
      }

      return next;
    });
  }, [jobs.length, onComplete]);

  if (!pendingPrintJob || jobs.length === 0) {
    return null;
  }

  const completedCount = results.length;
  const progressPercent = jobs.length
    ? Math.round((completedCount / jobs.length) * 100)
    : 0;
  const activeJob = jobs[currentIndex];

  return (
    <div className="fixed inset-0 bg-black/80 z-[200] flex flex-col items-center justify-center backdrop-blur-md">
      <div className="bg-white dark:bg-neutral-900 p-8 rounded-xl shadow-2xl text-center border border-neutral-200 dark:border-neutral-800 min-w-[320px]">
        <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <h3 className="text-lg font-serif dark:text-white">Preparing Labels</h3>
        <p className="text-sm text-neutral-500 mt-2">
          Rendering {completedCount} of {jobs.length}...
        </p>
        <div className="mt-4 h-2 w-full bg-neutral-200 dark:bg-neutral-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-200"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      <div style={{ position: 'absolute', top: '-9999px', left: '-9999px', pointerEvents: 'none' }}>
        {activeJob && (
          <HeadlessPage
            key={activeJob.id}
            state={pendingPrintJob.canvasState}
            record={activeJob.record}
            pageIndex={activeJob.pageIndex}
            onReady={handlePageReady}
          />
        )}
      </div>
    </div>
  );
}

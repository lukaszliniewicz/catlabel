import React, { useCallback, useEffect, useMemo, useState } from 'react';
import HeadlessPage from './components/HeadlessPage';


export default function HeadlessRenderer() {
  const [payload, setPayload] = useState(() => window.__INJECTED_PAYLOAD__ || null);
  const [results, setResults] = useState([]);

  useEffect(() => {
    if (payload) return undefined;

    const intervalId = window.setInterval(() => {
      if (window.__INJECTED_PAYLOAD__) {
        window.clearInterval(intervalId);
        setPayload(window.__INJECTED_PAYLOAD__);
      }
    }, 100);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [payload]);

  const renderJobs = useMemo(() => {
    if (!payload) return [];

    const canvasState = payload.canvas_state || {};
    const items = canvasState.items || [];
    const maxPage = items.reduce((max, item) => Math.max(max, Number(item.pageIndex ?? 0)), 0);
    const pages = Array.from({ length: maxPage + 1 }, (_, index) => index);
    const variablesCollection = payload.variables_collection?.length ? payload.variables_collection : [{}];
    const copies = Math.max(1, Number(payload.copies) || 1);

    const jobs = [];
    variablesCollection.forEach((record, recordIndex) => {
      for (let copyIndex = 0; copyIndex < copies; copyIndex += 1) {
        pages.forEach((pageIndex) => {
          jobs.push({
            id: `job-${recordIndex}-${copyIndex}-${pageIndex}`,
            pageIndex,
            record
          });
        });
      }
    });

    return jobs;
  }, [payload]);

  useEffect(() => {
    setResults(Array(renderJobs.length).fill(null));
    window.__RENDERED_IMAGES__ = [];

    const doneMarker = document.getElementById('render-done');
    if (doneMarker) {
      doneMarker.remove();
    }
  }, [renderJobs.length]);

  const handlePageReady = useCallback((captureIndex, b64) => {
    setResults((prev) => {
      const next = prev.length === renderJobs.length
        ? [...prev]
        : Array(renderJobs.length).fill(null);

      next[captureIndex] = b64;

      if (renderJobs.length > 0 && next.every(Boolean)) {
        window.__RENDERED_IMAGES__ = next;

        if (!document.getElementById('render-done')) {
          const doneMarker = document.createElement('div');
          doneMarker.id = 'render-done';
          doneMarker.style.opacity = '0';
          document.body.appendChild(doneMarker);
        }
      }

      return next;
    });
  }, [renderJobs.length]);

  if (!payload) {
    return null;
  }

  const canvasState = payload.canvas_state || {};

  return (
    <div style={{ position: 'absolute', top: '-9999px', left: '-9999px', opacity: 0, pointerEvents: 'none' }}>
      {renderJobs.map((job, index) => (
        <HeadlessPage
          key={job.id}
          state={canvasState}
          record={job.record}
          pageIndex={job.pageIndex}
          onReady={(b64) => handlePageReady(index, b64)}
        />
      ))}
    </div>
  );
}

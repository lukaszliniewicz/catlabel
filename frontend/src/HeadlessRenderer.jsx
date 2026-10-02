import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HeadlessPage from './components/HeadlessPage';
import { getPageIndices } from './utils/canvasPages';
import { getPrintJobCount, getRenderPixelCount, MAX_PRINT_JOBS, MAX_RENDER_PIXELS } from './utils/batchData';


export default function HeadlessRenderer() {
  const [payload, setPayload] = useState(() => window.__INJECTED_PAYLOAD__ || null);
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

  return payload ? <HeadlessJob payload={payload} /> : null;
}

function HeadlessJob({ payload }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const resultsRef = useRef([]);
  const completedRef = useRef(false);
  const advanceTimer = useRef(null);
  useEffect(() => {
    completedRef.current = false;
    return () => {
      completedRef.current = true;
      window.clearTimeout(advanceTimer.current);
    };
  }, []);

  const markDone = useCallback((images, error = null) => {
    window.__RENDERED_IMAGES__ = images;
    window.__RENDER_ERROR__ = error ? String(error.message || error) : null;
    if (!document.getElementById('render-done')) {
      const doneMarker = document.createElement('div');
      doneMarker.id = 'render-done';
      doneMarker.style.opacity = '0';
      document.body.appendChild(doneMarker);
    }
  }, []);



  const renderPlan = useMemo(() => {
    if (!payload) return { jobs: [], error: null };

    const canvasState = payload.canvas_state || {};
    const pages = getPageIndices(canvasState, { includeCurrent: false });
    const variablesCollection = payload.variables_collection?.length ? payload.variables_collection : [{}];
    const copies = Math.max(1, Number(payload.copies) || 1);
    const jobCount = getPrintJobCount({
      records: variablesCollection.length,
      copies,
      pages: pages.length
    });

    if (jobCount > MAX_PRINT_JOBS) {
      return {
        jobs: [],
        error: new Error(
          `The render request contains ${jobCount.toLocaleString()} jobs; the limit is ${MAX_PRINT_JOBS.toLocaleString()}.`
        )
      };
    }
    const renderPixels = getRenderPixelCount({
      width: canvasState.width,
      height: canvasState.height,
      jobs: jobCount
    });
    if (renderPixels > MAX_RENDER_PIXELS) {
      return {
        jobs: [],
        error: new Error('The render request exceeds the safe in-memory pixel limit.')
      };
    }

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

    return { jobs, error: null };
  }, [payload]);
  const renderJobs = renderPlan.jobs;

  useEffect(() => {
    window.__RENDERED_IMAGES__ = [];
    window.__RENDER_ERROR__ = null;

    const doneMarker = document.getElementById('render-done');
    if (doneMarker) {
      doneMarker.remove();
    }
  }, []);

  useEffect(() => {
    if (payload && renderJobs.length === 0) {
      markDone([], renderPlan.error);
    }
  }, [markDone, renderJobs.length, renderPlan.error, payload]);

  const handlePageReady = useCallback((b64) => {
    if (completedRef.current) return;
    const next = [...resultsRef.current, b64];
    resultsRef.current = next;

    if (next.length === renderJobs.length) {
      completedRef.current = true;
      markDone(next);
      return;
    }

    advanceTimer.current = window.setTimeout(() => {
      setCurrentIndex((idx) => idx + 1);
    }, 50);
  }, [markDone, renderJobs.length]);

  const handlePageError = useCallback((error) => {
    if (completedRef.current) return;
    completedRef.current = true;
    markDone([], error);
  }, [markDone]);

  if (!payload || renderJobs.length === 0) {
    return null;
  }

  const canvasState = payload.canvas_state || {};
  const activeJob = renderJobs[currentIndex];

  return (
    <div style={{ position: 'absolute', top: '-9999px', left: '-9999px', pointerEvents: 'none' }}>
      {activeJob && (
        <HeadlessPage
          key={activeJob.id}
          state={canvasState}
          record={activeJob.record}
          pageIndex={activeJob.pageIndex}
          onReady={handlePageReady}
          onError={handlePageError}
        />
      )}
    </div>
  );
}

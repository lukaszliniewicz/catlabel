import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HeadlessPage from './components/HeadlessPage';
import { useStore } from './store';
import { getPageIndices } from './utils/canvasPages';
import { getPrintJobCount, getRenderPixelCount, MAX_PRINT_JOBS, MAX_RENDER_PIXELS } from './utils/batchData';


export default function HeadlessRenderer() {
  const [fontsReady, setFontsReady] = useState(false);
  const [fontError, setFontError] = useState(null);
  useEffect(() => {
    window.__CATLABEL_HEADLESS_VERSION__ = 1;
    let active = true;
    useStore.getState().fetchFonts().then((loaded) => {
      if (!active) return;
      if (loaded === false) setFontError(new Error('Label fonts could not be loaded.'));
      setFontsReady(true);
    });
    return () => { active = false; };
  }, []);
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

  return payload && fontsReady ? <HeadlessJob payload={payload} initialError={fontError} /> : null;
}

function HeadlessJob({ payload, initialError }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const resultsRef = useRef([]);
  const completedRef = useRef(false);
  useEffect(() => {
    completedRef.current = false;
    return () => {
      completedRef.current = true;
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
    if (initialError) return { jobs: [], error: initialError };
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
  }, [payload, initialError]);
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

    setCurrentIndex((idx) => idx + 1);
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

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Layer, Line, Rect, Stage } from 'react-konva';
import CanvasItemNode from './components/CanvasItemNode';

const waitForPaint = () => new Promise((resolve) => {
  requestAnimationFrame(() => requestAnimationFrame(resolve));
});

const renderCanvasBorder = (canvasState) => {
  const width = Math.max(1, Number(canvasState.width) || 384);
  const height = Math.max(1, Number(canvasState.height) || 384);
  const thickness = canvasState.canvasBorderThickness || 4;

  if (canvasState.canvasBorder === 'box') {
    return <Rect width={width} height={height} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState.canvasBorder === 'top') {
    return <Line points={[0, 0, width, 0]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState.canvasBorder === 'bottom') {
    return <Line points={[0, height, width, height]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState.canvasBorder === 'cut_line') {
    return <Line points={[0, height, width, height]} stroke="black" strokeWidth={thickness} dash={[10, 10]} listening={false} />;
  }

  return null;
};

const HeadlessCaptureStage = ({ canvasState, record, pageIndex, captureIndex, onReady }) => {
  const stageRef = useRef(null);
  const items = canvasState.items || [];
  const width = Math.max(1, Number(canvasState.width) || 384);
  const height = Math.max(1, Number(canvasState.height) || 384);

  const pageItems = useMemo(
    () => items.filter((item) => Number(item.pageIndex ?? 0) === pageIndex),
    [items, pageIndex]
  );

  useEffect(() => {
    let cancelled = false;
    let timeoutId = null;

    const capture = async () => {
      try {
        if (document.fonts?.ready) {
          await document.fonts.ready;
        }
      } catch (error) {
        console.warn('Font readiness check failed', error);
      }

      await waitForPaint();

      timeoutId = window.setTimeout(() => {
        if (!cancelled && stageRef.current) {
          onReady(captureIndex, stageRef.current.toDataURL({ pixelRatio: 1 }));
        }
      }, 500);
    };

    capture();

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [captureIndex, onReady, pageItems, record]);

  return (
    <Stage ref={stageRef} width={width} height={height}>
      <Layer>
        <Rect x={0} y={0} width={width} height={height} fill="white" listening={false} />
        {renderCanvasBorder(canvasState)}
        {pageItems.map((item) => (
          <CanvasItemNode
            key={item.id}
            item={item}
            record={record}
            canvasWidth={width}
            canvasHeight={height}
          />
        ))}
      </Layer>
    </Stage>
  );
};

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
        <HeadlessCaptureStage
          key={job.id}
          canvasState={canvasState}
          record={job.record}
          pageIndex={job.pageIndex}
          captureIndex={index}
          onReady={handlePageReady}
        />
      ))}
    </div>
  );
}

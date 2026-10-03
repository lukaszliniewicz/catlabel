import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Layer, Line, Rect, Stage } from 'react-konva';
import { toPng } from 'html-to-image';
import CanvasItemNode from './CanvasItemNode';
import HtmlLabel from './HtmlLabel';
import { buildLabelTemplateMarkup } from '../domain/templates';
import { getPageItems, getPageLayout } from '../utils/canvasPages';

const renderCanvasBorder = (canvasState) => {
  const width = Math.max(1, Number(canvasState?.width) || 384);
  const height = Math.max(1, Number(canvasState?.height) || 384);
  const thickness = canvasState?.canvasBorderThickness || 4;

  if (canvasState?.canvasBorder === 'box') {
    return <Rect width={width} height={height} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState?.canvasBorder === 'top') {
    return <Line points={[0, 0, width, 0]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState?.canvasBorder === 'bottom') {
    return <Line points={[0, height, width, height]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (canvasState?.canvasBorder === 'cut_line') {
    return <Line points={[0, height, width, height]} stroke="black" strokeWidth={thickness} dash={[10, 10]} listening={false} />;
  }

  return null;
};

const RENDER_TIMEOUT_MS = 20_000;

export default function HeadlessPage({ state, record, pageIndex, onReady, onError }) {
  const stageRef = useRef(null);
  const containerRef = useRef(null);
  const completedRef = useRef(false);
  const width = Math.max(1, Number(state?.width) || 384);
  const height = Math.max(1, Number(state?.height) || 384);
  const activeLayout = getPageLayout(state, pageIndex);
  const layoutHtml = activeLayout.htmlContent || (
    activeLayout.activeTemplate?.id
      ? buildLabelTemplateMarkup({
          template_id: activeLayout.activeTemplate.id,
          params: activeLayout.activeTemplate.params || {},
          width,
          height
        })
      : ''
  );
  const pageItems = useMemo(() => getPageItems(state?.items || [], pageIndex), [state?.items, pageIndex]);

  const [htmlReady, setHtmlReady] = useState(false);

  const reportError = useCallback((error) => {
    if (completedRef.current) return;
    completedRef.current = true;
    const normalizedError = error instanceof Error ? error : new Error(String(error));
    console.error('Headless render failed', normalizedError);
    onError?.(normalizedError);
  }, [onError]);

  const handleHtmlReady = useCallback(() => {
    setHtmlReady(true);
  }, []);

  const captureBoth = useCallback(async () => {
    if (!containerRef.current || completedRef.current) return;
    try {
      if (document.fonts?.ready) await document.fonts.ready;
      await new Promise(r => setTimeout(r, 100));
      const dataUrl = await toPng(containerRef.current, {
        pixelRatio: 1,
        backgroundColor: 'white',
        useCORS: true,
        cacheBust: true
      });
      if (completedRef.current) return;
      completedRef.current = true;
      onReady(dataUrl);
    } catch (error) {
      reportError(error);
    }
  }, [onReady, reportError]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      reportError(new Error(`Label rendering timed out after ${RENDER_TIMEOUT_MS / 1000} seconds.`));
    }, RENDER_TIMEOUT_MS);

    return () => window.clearTimeout(timeoutId);
  }, [reportError]);

  useEffect(() => {
    if (htmlReady) {
      captureBoth();
    }
  }, [htmlReady, captureBoth]);

  return (
    <div ref={containerRef} style={{ width, height, position: 'absolute', backgroundColor: 'white' }}>
      <div style={{ position: 'absolute', inset: 0, zIndex: 1 }}>
        <HtmlLabel
          html={layoutHtml}
          record={record}
          width={width}
          height={height}
          canvasBorder={state?.canvasBorder}
          canvasBorderThickness={state?.canvasBorderThickness}
          onRenderComplete={handleHtmlReady}
          onRenderError={reportError}
        />
      </div>
      <div style={{ position: 'absolute', inset: 0, zIndex: 2 }}>
        <Stage ref={stageRef} width={width} height={height}>
          <Layer>
            <Rect x={0} y={0} width={width} height={height} fill="transparent" listening={false} />
            {renderCanvasBorder(state)}
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
      </div>
    </div>
  );
}

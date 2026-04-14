import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Layer, Line, Rect, Stage } from 'react-konva';
import { toPng } from 'html-to-image';
import CanvasItemNode from './CanvasItemNode';
import HtmlLabel from './HtmlLabel';

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

export default function HeadlessPage({ state, record, pageIndex, onReady }) {
  const stageRef = useRef(null);
  const htmlRef = useRef(null);
  const items = state?.items || [];
  const width = Math.max(1, Number(state?.width) || 384);
  const height = Math.max(1, Number(state?.height) || 384);
  const isHtmlMode = state?.designMode === 'html';

  const pageItems = useMemo(
    () => items.filter((item) => Number(item.pageIndex ?? 0) === pageIndex),
    [items, pageIndex]
  );

  const captureHtml = useCallback(async () => {
    if (!htmlRef.current) return;

    try {
      if (document.fonts?.ready) {
        await document.fonts.ready;
      }
    } catch (error) {
      console.warn('Font readiness check failed', error);
    }

    try {
      const dataUrl = await toPng(htmlRef.current, {
        pixelRatio: 1,
        backgroundColor: 'white',
        useCORS: true
      });
      onReady(dataUrl);
    } catch (error) {
      console.error('html-to-image failed', error);
    }
  }, [onReady]);

  useEffect(() => {
    if (isHtmlMode) return undefined;

    let cancelled = false;
    const capture = async () => {
      try {
        if (document.fonts?.ready) {
          await document.fonts.ready;
        }
      } catch (error) {
        console.warn('Font readiness check failed', error);
      }

      requestAnimationFrame(() => {
        window.setTimeout(() => {
          if (cancelled || !stageRef.current) {
            return;
          }

          onReady(stageRef.current.toDataURL({ pixelRatio: 1 }));
        }, 300);
      });
    };

    capture();

    return () => {
      cancelled = true;
    };
  }, [isHtmlMode, onReady, pageItems, record, state, width, height]);

  if (isHtmlMode) {
    return (
      <div ref={htmlRef} style={{ width, height, position: 'absolute', backgroundColor: 'white' }}>
        <HtmlLabel
          html={state?.htmlContent || ''}
          record={record}
          width={width}
          height={height}
          canvasBorder={state?.canvasBorder}
          canvasBorderThickness={state?.canvasBorderThickness}
          onRenderComplete={captureHtml}
        />
      </div>
    );
  }

  return (
    <Stage ref={stageRef} width={width} height={height}>
      <Layer>
        <Rect x={0} y={0} width={width} height={height} fill="white" listening={false} />
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
  );
}

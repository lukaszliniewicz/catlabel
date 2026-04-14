import React, { useEffect, useMemo, useRef } from 'react';
import { Layer, Line, Rect, Stage } from 'react-konva';
import { toPng } from 'html-to-image';
import CanvasItemNode from './CanvasItemNode';
import HtmlLabel from './HtmlLabel';

const waitForPaint = () => new Promise((resolve) => {
  requestAnimationFrame(() => requestAnimationFrame(resolve));
});

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

export default function HeadlessPage({ state, record, pageIndex, onReady, readyDelayMs = 500 }) {
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

      timeoutId = window.setTimeout(async () => {
        if (cancelled) {
          return;
        }

        if (isHtmlMode && htmlRef.current) {
          try {
            const dataUrl = await toPng(htmlRef.current, {
              pixelRatio: 1,
              backgroundColor: 'white'
            });
            onReady(dataUrl);
          } catch (error) {
            console.error('html-to-image failed', error);
          }
          return;
        }

        if (stageRef.current) {
          onReady(stageRef.current.toDataURL({ pixelRatio: 1 }));
        }
      }, readyDelayMs);
    };

    capture();

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [isHtmlMode, onReady, pageItems, record, readyDelayMs, state, width, height]);

  if (isHtmlMode) {
    return (
      <div ref={htmlRef} style={{ width, height, position: 'relative', backgroundColor: 'white' }}>
        <HtmlLabel
          html={state?.htmlContent || ''}
          record={record}
          width={width}
          height={height}
          canvasBorder={state?.canvasBorder}
          canvasBorderThickness={state?.canvasBorderThickness}
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

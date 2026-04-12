import React, { useEffect, useMemo, useRef } from 'react';
import { Layer, Line, Rect, Stage } from 'react-konva';
import CanvasItemNode from './CanvasItemNode';

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
  const items = state?.items || [];
  const width = Math.max(1, Number(state?.width) || 384);
  const height = Math.max(1, Number(state?.height) || 384);

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
  }, [onReady, pageItems, record, readyDelayMs, width, height, state?.canvasBorder, state?.canvasBorderThickness]);

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

import React, { useEffect, useMemo, useRef } from 'react';
import { autoTextSize } from 'auto-text-size';
import { applyVars } from '../utils/rendering';

const overlayBaseStyle = {
  position: 'absolute',
  pointerEvents: 'none',
  boxSizing: 'border-box'
};

export default function HtmlLabel({
  html,
  record,
  width,
  height,
  canvasBorder = 'none',
  canvasBorderThickness = 4
}) {
  const containerRef = useRef(null);
  const processedHtml = useMemo(() => applyVars(html || '', record), [html, record]);
  const borderThickness = Math.max(1, Number(canvasBorderThickness) || 4);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const elements = containerRef.current.querySelectorAll('.auto-text');
    const cleanups = Array.from(elements).map((element) => {
      try {
        return autoTextSize({ containerEl: element });
      } catch (error) {
        console.error('auto-text-size failed', error);
        return null;
      }
    });

    return () => {
      cleanups.forEach((cleanup) => {
        if (typeof cleanup === 'function') {
          cleanup();
        } else if (cleanup && typeof cleanup.disconnect === 'function') {
          cleanup.disconnect();
        } else if (cleanup && typeof cleanup.destroy === 'function') {
          cleanup.destroy();
        }
      });
    };
  }, [processedHtml, width, height]);

  return (
    <div
      ref={containerRef}
      style={{
        width,
        height,
        overflow: 'hidden',
        position: 'relative',
        backgroundColor: 'white'
      }}
    >
      <div
        style={{ width: '100%', height: '100%' }}
        dangerouslySetInnerHTML={{ __html: processedHtml }}
      />
      {canvasBorder === 'box' && (
        <div
          style={{
            ...overlayBaseStyle,
            inset: 0,
            border: `${borderThickness}px solid black`
          }}
        />
      )}
      {canvasBorder === 'top' && (
        <div
          style={{
            ...overlayBaseStyle,
            top: 0,
            left: 0,
            right: 0,
            height: borderThickness,
            backgroundColor: 'black'
          }}
        />
      )}
      {canvasBorder === 'bottom' && (
        <div
          style={{
            ...overlayBaseStyle,
            bottom: 0,
            left: 0,
            right: 0,
            height: borderThickness,
            backgroundColor: 'black'
          }}
        />
      )}
      {canvasBorder === 'cut_line' && (
        <div
          style={{
            ...overlayBaseStyle,
            bottom: 0,
            left: 0,
            right: 0,
            borderBottom: `${borderThickness}px dashed black`
          }}
        />
      )}
    </div>
  );
}

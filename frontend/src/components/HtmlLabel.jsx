import React, { useEffect, useRef, useState } from 'react';
import { applyVars, processHtmlDynamicElements } from '../utils/rendering';
import { sanitizeLabelHtml } from '../utils/htmlSecurity';
import { useStore } from '../store';

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
  canvasBorderThickness = 4,
  onRenderComplete,
  onRenderError
}) {
  const containerRef = useRef(null);
  const defaultFont = useStore((state) => state.settings?.default_font) || 'Arial';
  const fontFamily = defaultFont.split('.')[0];
  const processedHtml = sanitizeLabelHtml(applyVars(html || '', record));
  const borderThickness = Math.max(1, Number(canvasBorderThickness) || 4);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let cancelled = false;
    setIsReady(false);
    container.innerHTML = processedHtml;

    const process = async () => {
      try {
        if (document.fonts?.ready) {
          await document.fonts.ready;
        }
      } catch (error) {
        if (!cancelled) onRenderError?.(error);
        return;
      }

      if (cancelled) return;

      try {
        await processHtmlDynamicElements(container, width, height, () => cancelled);
      } catch (error) {
        if (!cancelled) onRenderError?.(error);
        return;
      }

      if (cancelled) return;

      setIsReady(true);

      if (onRenderComplete) {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (!cancelled) {
              onRenderComplete();
            }
          });
        });
      }
    };

    process();

    return () => {
      cancelled = true;
    };
  }, [processedHtml, width, height, fontFamily, onRenderComplete, onRenderError]);

  return (
    <div
      style={{
        width,
        height,
        overflow: 'hidden',
        position: 'relative',
        backgroundColor: 'white',
        color: 'black',
        fontFamily: `'${fontFamily}', sans-serif`,
        opacity: isReady ? 1 : 0
      }}
    >
      <div
        ref={containerRef}
        style={{ width: '100%', height: '100%' }}
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

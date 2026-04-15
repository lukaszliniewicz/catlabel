import React, { useEffect, useRef } from 'react';
import { applyVars } from '../utils/rendering';
import { useStore } from '../store';

const overlayBaseStyle = {
  position: 'absolute',
  pointerEvents: 'none',
  boxSizing: 'border-box'
};

const AUTO_TEXT_HTML_STYLES = `
/* Hardened container */
.auto-text {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  overflow: hidden;
}

/* CRITICAL RESET: Strip LLM formatting from children so scrollHeight doesn't blow up */
.auto-text * {
  margin: 0 !important;
  padding: 0 !important;
  line-height: 1.1 !important;
}
`;

export default function HtmlLabel({
  html,
  record,
  width,
  height,
  canvasBorder = 'none',
  canvasBorderThickness = 4,
  onRenderComplete
}) {
  const containerRef = useRef(null);
  const defaultFont = useStore((state) => state.settings?.default_font) || 'Arial';
  const fontFamily = defaultFont.split('.')[0];
  const processedHtml = applyVars(html || '', record);
  const borderThickness = Math.max(1, Number(canvasBorderThickness) || 4);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let cancelled = false;
    const elements = container.querySelectorAll('.auto-text');

    elements.forEach((el) => {
      let low = 4;
      let high = 500;
      let best = 4;

      const targetW = el.clientWidth || el.parentElement?.clientWidth || width;
      const targetH = el.clientHeight || el.parentElement?.clientHeight || height;

      while (high - low >= 0.5) {
        const mid = (low + high) / 2;
        el.style.fontSize = `${mid}px`;

        if (el.scrollWidth <= targetW && el.scrollHeight <= targetH) {
          best = mid;
          low = mid + 0.5;
        } else {
          high = mid - 0.5;
        }
      }

      el.style.fontSize = `${Math.floor(best)}px`;
    });

    requestAnimationFrame(() => {
      if (cancelled) return;
      requestAnimationFrame(() => {
        if (!cancelled && onRenderComplete) {
          onRenderComplete();
        }
      });
    });

    return () => {
      cancelled = true;
    };
  }, [processedHtml, width, height, onRenderComplete]);

  return (
    <div
      style={{
        width,
        height,
        overflow: 'hidden',
        position: 'relative',
        backgroundColor: 'white',
        color: 'black',
        fontFamily: `'${fontFamily}', sans-serif`
      }}
    >
      <style>{AUTO_TEXT_HTML_STYLES}</style>
      <div
        ref={containerRef}
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

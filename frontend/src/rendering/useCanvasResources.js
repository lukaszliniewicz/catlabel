import { useEffect, useRef, useState } from 'react';
import { toPng } from 'html-to-image';
import { processHtmlDynamicElements } from '../utils/rendering';
import { sanitizeLabelHtml } from '../utils/htmlSecurity';
import { loadRenderImage, nextPaint } from './readiness';
import { useResourceReady } from './useResourceReady';

export function useCanvasImage(url) {
  const [loaded, setLoaded] = useState(null);
  const current = loaded?.url === url ? loaded : null;
  useResourceReady(!url || Boolean(current), current?.error);
  useEffect(() => {
    if (!url) return undefined;
    const controller = new AbortController();
    loadRenderImage(url, controller.signal).then(
      (image) => { if (!controller.signal.aborted) setLoaded({ url, image }); },
      (error) => { if (!controller.signal.aborted) setLoaded({ url, image: null, error }); }
    );
    return () => controller.abort();
  }, [url]);
  return current?.image || null;
}

export function useHtmlRasterizer(html, width, height, font = 'Arial') {
  const [result, setResult] = useState(null);
  const generationRef = useRef(null);
  const matches = result?.html === html && result?.width === width && result?.height === height && result?.font === font;
  useResourceReady(!html || Boolean(matches), matches ? result?.error : null);
  useEffect(() => {
    if (!html || width <= 0 || height <= 0) return undefined;
    const controller = new AbortController();
    const generation = {};
    generationRef.current = generation;
    const container = document.createElement('div');
    Object.assign(container.style, {
      position: 'fixed', left: '-9999px', top: '0', overflow: 'hidden',
      boxSizing: 'border-box', pointerEvents: 'none', backgroundColor: 'transparent',
      color: 'black', width: `${width}px`, height: `${height}px`,
      fontFamily: `'${font.split('.')[0]}', sans-serif`
    });
    container.innerHTML = sanitizeLabelHtml(html);
    document.body.appendChild(container);
    const active = () => !controller.signal.aborted && generationRef.current === generation;
    const rasterize = async () => {
      try {
        if (document.fonts?.ready) await document.fonts.ready;
        if (!active()) return;
        await processHtmlDynamicElements(container, width, height, () => !active());
        await nextPaint();
        if (!active()) return;
        const url = await toPng(container, {
          pixelRatio: 1, useCORS: true,
          style: { position: 'static' }
        });
        const image = await loadRenderImage(url, controller.signal);
        if (active()) setResult({ html, width, height, font, image });
      } catch (error) {
        if (active()) setResult({ html, width, height, font, image: null, error });
      } finally {
        container.remove();
      }
    };
    void rasterize();
    return () => { controller.abort(); container.remove(); };
  }, [html, width, height, font]);
  return matches ? result.image : null;
}

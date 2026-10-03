import { useEffect, useState } from 'react';
import Konva from 'konva';
import { applyVars } from '../domain/variables';
import { useResourceReady } from '../rendering/useResourceReady';
import { CodeRenderCache } from './codeCache';

let barcodeModulePromise;
let qrCodeModulePromise;
const getBarcodeModule = () => {
  barcodeModulePromise ||= import('bwip-js').then((module) => module.default || module).catch(error => { barcodeModulePromise = null; throw error; });
  return barcodeModulePromise;
};
const getQrCodeModule = () => {
  qrCodeModulePromise ||= import('qrcode').then((module) => module.default || module).catch(error => { qrCodeModulePromise = null; throw error; });
  return qrCodeModulePromise;
};

const codeCache = new CodeRenderCache();
const renderCode = (type, value, format, scale) => codeCache.getOrCreate(JSON.stringify([type, value, format, scale]), async () => {
  if (type === 'barcode') {
    const bwipjs = await getBarcodeModule();
    const canvas = document.createElement('canvas');
    bwipjs.toCanvas(canvas, { bcid: format, text: value, scale, includetext: false, backgroundcolor: 'FFFFFF' });
    return canvas.toDataURL('image/png');
  }
  const QRCode = await getQrCodeModule();
  return QRCode.toDataURL(value, { margin: 1, scale, color: { dark: '#000000', light: '#FFFFFF' } });
});

const IMAGE_LOAD_TIMEOUT_MS = 8_000;

const loadInjectedImage = (src) => new Promise((resolve) => {
  const image = document.createElement('img');
  let settled = false;
  const finish = (value) => {
    if (settled) return;
    settled = true;
    window.clearTimeout(timeoutId);
    resolve(value);
  };
  const timeoutId = window.setTimeout(() => finish(null), IMAGE_LOAD_TIMEOUT_MS);
  image.onload = () => finish(image);
  image.onerror = () => finish(null);
  image.src = src;
});

export const processHtmlDynamicElements = async (container, width, height, isCancelled) => {
  // 1. Process codes (QR/Barcode)
  const codeEls = Array.from(container.querySelectorAll('.catlabel-code'));

  for (const el of codeEls) {
    if (isCancelled && isCancelled()) return;

    const type = el.getAttribute('data-type');
    const format = el.getAttribute('data-format') || 'code128';
    const value = el.getAttribute('data-value') || '';

    if (!value) {
      el.innerHTML = '';
      continue;
    }

    try {
      let dataUrl = null;

      if (type === 'barcode') {
        dataUrl = await renderCode(type, value, format, 8);
      } else if (type === 'qrcode') {
        dataUrl = await renderCode(type, value, '', 16);
      }

      if (dataUrl) {
        const image = await loadInjectedImage(dataUrl);
        if (isCancelled && isCancelled()) return;

        if (!image) throw new Error('A generated label code could not be loaded.');
        if (image) {
          image.style.maxWidth = '100%';
          image.style.maxHeight = '100%';
          image.style.width = '100%';
          image.style.height = '100%';
          image.style.objectFit = 'contain';
          el.replaceChildren(image);
        }
      }
    } catch (error) {
      throw new Error(`A label code could not be generated: ${error.message || error}`, { cause: error });
    }
  }

  if (isCancelled && isCancelled()) return;

  // 2. Wait for all injected images to load
  const imgEls = Array.from(container.querySelectorAll('img'));
  await Promise.all(imgEls.map((img) => {
    if (img.complete) {
      if (!img.naturalWidth) return Promise.reject(new Error('An HTML label image could not be loaded.'));
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const finish = (error) => {
        window.clearTimeout(timeoutId);
        img.removeEventListener('load', onLoad);
        img.removeEventListener('error', onError);
        if (error) reject(error); else resolve();
      };
      const onLoad = () => finish(null);
      const onError = () => finish(new Error('An HTML label image could not be loaded.'));
      const timeoutId = window.setTimeout(() => finish(new Error('An HTML label image timed out.')), IMAGE_LOAD_TIMEOUT_MS);
      img.addEventListener('load', onLoad, { once: true });
      img.addEventListener('error', onError, { once: true });
    });
  }));

  if (isCancelled && isCancelled()) return;

  // =========================================================================
  // THREE-PASS AUTO-SCALING PIPELINE
  // =========================================================================

  // Force a DOM reflow to ensure all flex layouts and images are settled
  container.offsetHeight;

  const boxes = Array.from(container.querySelectorAll('.bound-box'));

  // PASS 1: READ
  // We use offsetWidth/clientWidth because they ignore CSS transform scales.
  const boxMetrics = boxes.map((box) => {
    const style = window.getComputedStyle(box);
    const px = (val) => parseFloat(val) || 0;

    return {
      outerW: Math.max(1, box.offsetWidth),
      outerH: Math.max(1, box.offsetHeight),
      innerW: Math.max(1, box.clientWidth - px(style.paddingLeft) - px(style.paddingRight)),
      innerH: Math.max(1, box.clientHeight - px(style.paddingTop) - px(style.paddingBottom))
    };
  });

  // PASS 2: LOCK (WRITE)
  // Force absolute pixel values so the layout never shifts when text grows.
  boxes.forEach((box, i) => {
    box.style.width = `${boxMetrics[i].outerW}px`;
    box.style.height = `${boxMetrics[i].outerH}px`;
    box.style.flex = 'none';
    box.style.minWidth = 'unset';
    box.style.minHeight = 'unset';
    box.style.maxWidth = 'unset';
    box.style.maxHeight = 'unset';
  });

  if (isCancelled && isCancelled()) return;

  // PASS 3: BINARY SCALE
  const autoTexts = Array.from(container.querySelectorAll('.auto-text'));

  autoTexts.forEach((el) => {
    const parentBox = el.closest('.bound-box');
    if (!parentBox) return;

    const pIndex = boxes.indexOf(parentBox);
    const targetW = boxMetrics[pIndex].innerW;
    const targetH = boxMetrics[pIndex].innerH;

    // Reset styles to shrink-wrap the text exactly
    el.style.width = '100%';
    el.style.height = 'auto';

    let low = 1;
    let high = 500;
    let best = 1;

    while (high - low > 0.5) {
      const mid = (low + high) / 2;
      el.style.fontSize = `${mid}px`;

      // Check text footprint vs target inner boundaries (allow 1px buffer)
      const overflowsH = el.scrollWidth > targetW + 1;
      const overflowsV = el.scrollHeight > targetH + 1;

      if (overflowsH || overflowsV) {
        high = mid;
      } else {
        best = mid;
        low = mid;
      }
    }

    el.style.fontSize = `${Math.floor(best * 10) / 10}px`;
  });
};

export { applyVars };

export const useCodeGenerator = (type, data, barcodeType) => {
  const [result, setResult] = useState(null);
  const hasData = data != null && String(data).length > 0;
  const [emptyError] = useState(() => new Error('A label code has no value.'));
  const key = JSON.stringify([type, data, barcodeType]);
  const current = result?.key === key ? result : null;
  useResourceReady(hasData && Boolean(current), hasData ? current?.error : emptyError);

  useEffect(() => {
    const setSrc = (src, error = null) => setResult({ key, src, error });
    let cancelled = false;

    const generate = async () => {
      if (!hasData || (type !== 'barcode' && type !== 'qrcode')) {
        if (!cancelled) setSrc(null);
        return;
      }

      if (type === 'barcode') {
        try {
          let bcid = 'code128';
          if (barcodeType === 'code39') bcid = 'code39';
          if (barcodeType === 'ean13') bcid = 'ean13';

          const dataUrl = await renderCode(type, String(data), bcid, 12);
          if (!cancelled) {
            setSrc(dataUrl);
          }
        } catch (error) {
          console.error('Failed to generate barcode', error);
          if (!cancelled) setSrc(null, error);
        }

        return;
      }

      try {
        const dataUrl = await renderCode(type, String(data), '', 24);

        if (!cancelled) {
          setSrc(dataUrl);
        }
      } catch (error) {
        console.error('Failed to generate QR code', error);
        if (!cancelled) setSrc(null, error);
      }
    };

    generate();

    return () => {
      cancelled = true;
    };
  }, [barcodeType, data, type, key, hasData]);

  return current?.src || null;
};

export const resolveDim = (dim, maxDim) => {
  if (typeof dim === 'string' && dim.endsWith('%')) {
    return (parseFloat(dim) / 100) * maxDim;
  }
  return Number(dim) || 0;
};

export const computeOptimalTextSize = (baseItem, textToFit, targetWidth, targetHeight) => {
  const fontFamily = baseItem.font ? baseItem.font.split('.')[0] : 'Arial';
  const fontStyleAttr = [
    baseItem.italic ? 'italic' : '',
    baseItem.weight || 700
  ].filter(Boolean).join(' ');

  let low = 6;
  let high = 800;
  let bestSize = low;

  const textNode = new Konva.Text({
    text: textToFit,
    fontFamily,
    fontStyle: fontStyleAttr,
    wrap: baseItem.no_wrap ? 'none' : 'word',
    lineHeight: baseItem.lineHeight ?? (String(textToFit).includes('\n') ? 1.15 : 1),
    padding: baseItem.padding !== undefined ? Number(baseItem.padding) : 0,
  });

  const words = String(textToFit).split(/\s+/).filter(Boolean);
  const tempWordNode = new Konva.Text({
    fontFamily,
    fontStyle: fontStyleAttr,
  });

  while (high - low >= 0.5) {
    const mid = (low + high) / 2;
    textNode.fontSize(mid);

    if (!baseItem.no_wrap) {
      textNode.width(targetWidth);
    } else {
      textNode.width(undefined);
    }

    const metrics = textNode.getClientRect();
    const italicBleed = baseItem.italic ? (mid * 0.15) : 0;

    let wordOverflow = false;
    tempWordNode.fontSize(mid);
    for (const word of words) {
      tempWordNode.text(word);
      if (tempWordNode.width() + italicBleed > targetWidth) {
        wordOverflow = true;
        break;
      }
    }

    if (metrics.width + italicBleed <= targetWidth && metrics.height <= targetHeight && !wordOverflow) {
      bestSize = mid;
      low = mid + 0.5;
    } else {
      high = mid - 0.5;
    }
  }

  textNode.destroy();
  tempWordNode.destroy();
  return Math.floor(bestSize * 10) / 10;
};

export const calculateAutoFitItem = (item, batchRecords = [{}], canvasWidth = 384, canvasHeight = 384) => {
  if (!item?.fit_to_width) return item;
  if (item.batch_scale_mode === 'individual') return item;

  const records = Array.isArray(batchRecords) && batchRecords.length > 0 ? batchRecords : [{}];
  const strings = records.map((record) => applyVars(item.text, record) || '');
  const uniqueStrings = [...new Set(strings)].filter((value) => String(value).length > 0);

  const resolvedW = resolveDim(item.width || 100, canvasWidth);
  const resolvedH = resolveDim(item.height || 50, canvasHeight);

  if (item.type === 'text') {
    const pad = item.padding !== undefined ? Number(item.padding) : 0;
    const targetWidth = Math.max(10, resolvedW - (pad * 2));
    const targetHeight = Math.max(10, resolvedH - (pad * 2));

    const probe = new Konva.Text({
      fontFamily: item.font ? item.font.split('.')[0] : 'Arial',
      fontStyle: [item.italic ? 'italic' : '', item.weight || 700].filter(Boolean).join(' '),
      fontSize: 100,
      lineHeight: item.lineHeight ?? 1
    });
    const stringsToTest = uniqueStrings
      .map((value) => {
        probe.text(String(value));
        const metrics = probe.getClientRect();
        const longestWordWidth = String(value).split(/\s+/).reduce((largest, word) => {
          probe.text(word);
          return Math.max(largest, probe.getClientRect().width);
        }, 0);
        return { value, score: Math.max(metrics.width / targetWidth, metrics.height / targetHeight, longestWordWidth / targetWidth) };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 25)
      .map(({ value }) => value);
    probe.destroy();

    let overallBestSize = null;
    for (const actualText of stringsToTest) {
      const bestSize = computeOptimalTextSize(item, actualText, targetWidth, targetHeight);
      if (overallBestSize === null || bestSize < overallBestSize) {
        overallBestSize = bestSize;
      }
    }

    return { ...item, size: overallBestSize || item.size };
  }

  if (item.type === 'icon_text') {
    const stringsToTest = uniqueStrings;
    let overallBestScale = null;

    for (const actualText of stringsToTest) {
      const textNode = new Konva.Text({
        text: actualText,
        fontFamily: item.font ? item.font.split('.')[0] : 'Arial',
        fontStyle: (item.weight || 700).toString(),
        fontSize: 100,
      });
      const tWidth = textNode.getClientRect().width;
      textNode.destroy();

      const baseRatio = item.icon_size / item.size;
      const testIconSize = 100 * baseRatio;
      const testGap = Math.max(4, 100 * 0.08);
      const totalW = testIconSize + testGap + tWidth;

      const scaleToFitWidth = resolvedW / totalW;
      const scaleToFitHeight = resolvedH / Math.max(testIconSize, 100);

      const bestScale = Math.min(scaleToFitWidth, scaleToFitHeight);
      if (overallBestScale === null || bestScale < overallBestScale) {
        overallBestScale = bestScale;
      }
    }

    if (overallBestScale) {
      const newSize = Math.floor(100 * overallBestScale * 10) / 10;
      const newIconSize = Math.floor(100 * (item.icon_size / item.size) * overallBestScale * 10) / 10;
      const GAP = Math.max(4, newSize * 0.08);
      const newH = Math.max(newIconSize, newSize);

      return {
        ...item,
        size: newSize,
        icon_size: newIconSize,
        icon_y: (newH - newIconSize) / 2,
        text_x: newIconSize + GAP,
        text_y: (newH / 2) - ((newSize * 0.71) / 2),
      };
    }
  }

  return item;
};

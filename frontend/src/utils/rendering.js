import { useEffect, useState } from 'react';
import Konva from 'konva';
import bwipjs from 'bwip-js';
import QRCode from 'qrcode';

export const applyVars = (str, record) => {
  if (!str) return str;

  let result = String(str);

  if (record) {
    Object.keys(record).forEach((key) => {
      const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`{{\\s*${escapedKey}\\s*}}`, 'g');
      result = result.replace(regex, String(record[key] ?? ''));
    });
  }

  const now = new Date();
  const formatYMD = (dateObj) => {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  };

  result = result.replace(/{{\s*\$date\s*}}/g, formatYMD(now));
  result = result.replace(/{{\s*\$time\s*}}/g, now.toTimeString().substring(0, 5));
  result = result.replace(/{{\s*\$date([+-])(\d+)\s*}}/g, (match, op, daysStr) => {
    const days = parseInt(daysStr, 10);
    const nextDate = new Date(now);
    nextDate.setDate(nextDate.getDate() + (op === '+' ? days : -days));
    return formatYMD(nextDate);
  });

  return result;
};

export const useCodeGenerator = (type, data, barcodeType) => {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const generate = async () => {
      if (!data || (type !== 'barcode' && type !== 'qrcode')) {
        if (!cancelled) setSrc(null);
        return;
      }

      if (type === 'barcode') {
        const canvas = document.createElement('canvas');

        try {
          let bcid = 'code128';
          if (barcodeType === 'code39') bcid = 'code39';
          if (barcodeType === 'ean13') bcid = 'ean13';

          bwipjs.toCanvas(canvas, {
            bcid,
            text: String(data),
            scale: 6,
            includetext: false,
            backgroundcolor: 'FFFFFF'
          });

          if (!cancelled) {
            setSrc(canvas.toDataURL('image/png'));
          }
        } catch (error) {
          console.error('Failed to generate barcode', error);
          if (!cancelled) setSrc(null);
        }

        return;
      }

      try {
        const dataUrl = await QRCode.toDataURL(String(data), {
          margin: 1,
          scale: 12,
          color: { dark: '#000000', light: '#FFFFFF' }
        });

        if (!cancelled) {
          setSrc(dataUrl);
        }
      } catch (error) {
        console.error('Failed to generate QR code', error);
        if (!cancelled) setSrc(null);
      }
    };

    generate();

    return () => {
      cancelled = true;
    };
  }, [barcodeType, data, type]);

  return src;
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
  let bestSize = baseItem.size || 24;

  const textNode = new Konva.Text({
    text: textToFit,
    fontFamily,
    fontStyle: fontStyleAttr,
    wrap: baseItem.no_wrap ? 'none' : 'word',
    lineHeight: baseItem.lineHeight ?? (String(textToFit).includes('\n') ? 1.15 : 1),
    padding: baseItem.padding !== undefined ? Number(baseItem.padding) : 0,
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

    if (metrics.width + italicBleed <= targetWidth && metrics.height <= targetHeight) {
      bestSize = mid;
      low = mid + 0.5;
    } else {
      high = mid - 0.5;
    }
  }

  textNode.destroy();
  return Math.floor(bestSize * 10) / 10;
};

export const calculateAutoFitItem = (item, batchRecords = [{}], canvasWidth = 384, canvasHeight = 384) => {
  if (!item?.fit_to_width) return item;
  if (item.batch_scale_mode === 'individual') return item;

  const records = Array.isArray(batchRecords) && batchRecords.length > 0 ? batchRecords : [{}];
  const strings = records.map((record) => applyVars(item.text, record) || '');
  const uniqueStrings = [...new Set(strings)].sort((a, b) => b.length - a.length);
  const stringsToTest = uniqueStrings.filter((value) => String(value).length > 0).slice(0, 10);

  const resolvedW = resolveDim(item.width || 100, canvasWidth);
  const resolvedH = resolveDim(item.height || 50, canvasHeight);

  if (item.type === 'text') {
    const pad = item.padding !== undefined ? Number(item.padding) : 0;
    const targetWidth = Math.max(10, resolvedW - (pad * 2));
    const targetHeight = Math.max(10, resolvedH - (pad * 2));

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

import { useEffect, useState } from 'react';
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

const measureWrappedText = (ctx, text, maxWidth) => {
  const lines = [];
  const paragraphs = String(text).split('\n');
  let maxLineWidth = 0;

  for (const paragraph of paragraphs) {
    const words = paragraph.split(' ');
    let currentLine = words[0] || '';

    for (let i = 1; i < words.length; i++) {
      const word = words[i];
      const testLine = `${currentLine} ${word}`;
      const metrics = ctx.measureText(testLine);

      if (metrics.width > maxWidth) {
        maxLineWidth = Math.max(maxLineWidth, ctx.measureText(currentLine).width);
        lines.push(currentLine);
        currentLine = word;
      } else {
        currentLine = testLine;
      }
    }

    maxLineWidth = Math.max(maxLineWidth, ctx.measureText(currentLine).width);
    lines.push(currentLine);
  }

  return { lines, maxLineWidth };
};

export const calculateAutoFitItem = (item) => {
  if (!item?.fit_to_width || item.type !== 'text') return item;

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
  const fontStyleAttr = [
    item.italic ? 'italic' : '',
    item.weight || 700
  ].filter(Boolean).join(' ');

  const pad = item.padding !== undefined ? Number(item.padding) : 4;
  const targetWidth = Math.max(10, (item.width || 100) - (pad * 2));
  const targetHeight = Math.max(10, (item.height || 50) - (pad * 2));
  const safeWidth = Math.max(10, targetWidth - 2);

  let low = 6;
  let high = 800;
  let bestSize = item.size || 24;

  while (high - low >= 0.5) {
    const mid = (low + high) / 2;
    ctx.font = `${fontStyleAttr} ${mid}px "${fontFamily}"`;
    const italicBleed = item.italic ? (mid * 0.15) : 0;

    let fits = false;

    if (item.no_wrap) {
      const lines = String(item.text || '').split('\n');
      let maxLineWidth = 0;

      for (const line of lines) {
        maxLineWidth = Math.max(maxLineWidth, ctx.measureText(line).width);
      }

      const textBlockHeight = mid * 1.15 * lines.length;
      fits = maxLineWidth + italicBleed <= safeWidth && textBlockHeight <= targetHeight;
    } else {
      const { lines: wrappedLines, maxLineWidth } = measureWrappedText(
        ctx,
        item.text || '',
        safeWidth - italicBleed
      );
      const textBlockHeight = mid * 1.15 * wrappedLines.length;
      fits = maxLineWidth + italicBleed <= safeWidth && textBlockHeight <= targetHeight;
    }

    if (fits) {
      bestSize = mid;
      low = mid + 0.5;
    } else {
      high = mid - 0.5;
    }
  }

  return {
    ...item,
    size: Math.floor(bestSize * 2) / 2
  };
};

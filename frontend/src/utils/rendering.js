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
            scale: 3,
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

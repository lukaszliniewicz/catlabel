import type { CanvasItem } from './document';

interface FieldChange { name: string; value: unknown; type: string; checked?: boolean }
interface GeometryPatch { x?: number; y?: number; width?: number; height?: number | `${number}%`; align?: 'center' }
const finite = (value: unknown, fallback: number): number => {
  if (typeof value !== 'number' && typeof value !== 'string') return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export function resolveElementDimension(value: unknown, span: number, fallback = 0): number {
  if (typeof value === 'string' && value.trim().endsWith('%')) {
    const percent = Number(value.trim().slice(0, -1));
    return Number.isFinite(percent) ? percent * span / 100 : fallback;
  }
  return finite(value, fallback);
}

export function centerElement(item: CanvasItem, width: number, height: number): GeometryPatch {
  const itemWidth = resolveElementDimension(item.width, width);
  let itemHeight = resolveElementDimension(item.height, height);
  if (!itemHeight && item.type === 'text') {
    const padding = finite(item.padding, item.invert || item.bg_white ? 4 : 0);
    const lines = String(item.text || '').split('\n').length;
    const lineHeight = finite(item.lineHeight, lines > 1 ? 1.15 : 1);
    itemHeight = finite(item.size, 12) * lineHeight * lines + 2 * padding;
  }
  return { x: (width - itemWidth) / 2, y: (height - itemHeight) / 2 };
}

export function fitElementWidth(item: CanvasItem, width: number, height: number): GeometryPatch {
  let nextHeight = item.height;
  const itemWidth = resolveElementDimension(item.width, width);
  const itemHeight = resolveElementDimension(item.height, height);
  if (item.type === 'qrcode') nextHeight = width;
  else if (item.type === 'image' && itemWidth > 0 && itemHeight > 0) nextHeight = Math.round(width * itemHeight / itemWidth);
  return { x: 0, width, height: nextHeight, align: 'center' };
}

export function buildElementChange(item: CanvasItem, field: FieldChange, width: number, height: number): Record<string, string | number | boolean> | null {
  let value: string | number | boolean;
  if (field.type === 'checkbox') value = Boolean(field.checked);
  else if (field.type === 'number') {
    if ((typeof field.value !== 'number' && typeof field.value !== 'string') || String(field.value).trim() === '') return null;
    value = finite(field.value, NaN);
    if (!Number.isFinite(value)) return null;
    if (['width', 'height', 'size'].includes(field.name) && value <= 0) return null;
  } else {
    if (typeof field.value !== 'string') return null;
    value = field.value;
  }
  if (item.type === 'qrcode' && (field.name === 'width' || field.name === 'height') && typeof value === 'number') return { width: value, height: value };
  if (item.type === 'image' && (field.name === 'width' || field.name === 'height') && typeof value === 'number') {
    const oldWidth = resolveElementDimension(item.width, width), oldHeight = resolveElementDimension(item.height, height);
    if (oldWidth > 0 && oldHeight > 0) return field.name === 'width'
      ? { width: value, height: Math.max(1, Math.round(value * oldHeight / oldWidth)) }
      : { height: value, width: Math.max(1, Math.round(value * oldWidth / oldHeight)) };
  }
  return { [field.name]: value };
}

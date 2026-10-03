import type { CanvasDocument, CanvasElement, PageLayout } from './generated/document';
export type CanvasItem = CanvasElement;
type RecordData = Record<string, unknown>;
type Border = 'none' | 'box' | 'top' | 'bottom' | 'cut_line';

interface EditorDocumentState {
  canvasWidth: number;
  canvasHeight: number;
  currentDpi: number;
  canvasBorder: Border;
  canvasBorderThickness: number;
  isRotated: boolean;
  splitMode: boolean;
  pageLayouts: PageLayout[];
  items: CanvasItem[];
  currentPage: number;
  batchRecords: RecordData[];
  printCopies: number;
}

export function resolveDpi(value: unknown, fallback: number = 203): number {
  const dpi = typeof value === 'number' || typeof value === 'string'
    ? Number(value) : NaN;
  if (Number.isFinite(dpi) && dpi > 0) return dpi;
  return Number.isFinite(fallback) && fallback > 0 ? fallback : 203;
}

// Percent dimensions and rotation are independent of resolution. Preserve them.
export function scaleItemForDpi<T extends RecordData>(item: T, scale: number): T {
  const next: RecordData = { ...item };
  const keys = [
    'x', 'y', 'width', 'height', 'size', 'padding', 'border_thickness',
    'strokeWidth', 'icon_size', 'icon_x', 'icon_y', 'text_x', 'text_y'
  ];
  for (const key of keys) {
    const value = next[key];
    if (typeof value === 'number' && Number.isFinite(value)) next[key] = value * scale;
  }
  if (Array.isArray(item.children)) {
    next.children = item.children.map((child: RecordData) => scaleItemForDpi(child, scale));
  }
  return next as T;
}

// One persisted shape for create, overwrite, AI snapshots and clean capture.
export function serializeCanvasDocument(state: EditorDocumentState): CanvasDocument {
  return {
    document_version: 1,
    dpi: resolveDpi(state.currentDpi),
    width: state.canvasWidth,
    height: state.canvasHeight,
    isRotated: state.isRotated,
    canvasBorder: state.canvasBorder,
    canvasBorderThickness: state.canvasBorderThickness || 4,
    splitMode: state.splitMode,
    pageLayouts: state.pageLayouts,
    items: state.items,
    currentPage: state.currentPage,
    batchRecords: state.batchRecords || [{}],
    printCopies: state.printCopies || 1
  };
}

import { resolveDpi, scaleItemForDpi } from './document';
import { calculateAutoFitItem } from '../utils/rendering';
import { buildLabelTemplateMarkup } from './templates';
import { normalizePageIndex } from '../utils/canvasPages';
import { MAX_BATCH_RECORDS, MAX_PRINT_COPIES } from '../utils/batchData';

export const recalcAutoFit = (items, batchRecords, cw, ch) => {
  let changed = false;

  const nextItems = items.map((item) => {
    if (item.fit_to_width) {
      const optimizedItem = calculateAutoFitItem(item, batchRecords, cw, ch);
      if (optimizedItem.size !== item.size) {
        changed = true;
        return optimizedItem;
      }
    }
    return item;
  });

  return changed ? nextItems : items;
};

export const buildTemplateHtml = (templateId, params = {}, width = 384, height = 384) =>
  buildLabelTemplateMarkup({ template_id: templateId, params, width, height }, {});

const normalizeCanvasState = (canvasState = {}) => {
  const items = Array.isArray(canvasState.items)
    ? canvasState.items.filter((item) => item && typeof item === 'object')
    : [];
  let pageLayouts = canvasState.pageLayouts;

  // Migration from old single-template/HTML structure
  if (!pageLayouts || pageLayouts.length === 0) {
    const activeTemplate = canvasState.activeTemplate || null;
    const htmlContent = canvasState.htmlContent || '';

    if (activeTemplate?.id) {
      pageLayouts = [{
        pageIndex: 0,
        activeTemplate,
        htmlContent: buildTemplateHtml(activeTemplate.id, activeTemplate.params || {}, canvasState.width || 384, canvasState.height || 384)
      }];
    } else {
      pageLayouts = [{ pageIndex: 0, htmlContent, activeTemplate: null }];
    }
  }

  const legacyTemplateItem = items.length === 1 && items[0]?.type === 'label_template' ? items[0] : null;
  if (legacyTemplateItem) {
    const templateId = legacyTemplateItem.template_id || 'title_subtitle';
    const params = legacyTemplateItem.params || {};
    return {
      ...canvasState,
      pageLayouts: [{
        pageIndex: 0,
        activeTemplate: { id: templateId, params },
        htmlContent: buildTemplateHtml(templateId, params, canvasState.width || 384, canvasState.height || 384)
      }],
      items: []
    };
  }

  return {
    ...canvasState,
    items,
    pageLayouts
  };
};

export const buildCanvasDocumentPatch = (canvasState = {}, currentState = {}) => {
  if (canvasState.document_version != null && canvasState.document_version !== 1) {
    throw new Error('This document version is unsupported. Update CatLabel before opening it.');
  }
  const normalized = normalizeCanvasState(canvasState);
  const fallbackDpi = resolveDpi(currentState.currentDpi, currentState.settings?.default_dpi);
  const savedDpi = resolveDpi(normalized.dpi ?? normalized.__dpi__, fallbackDpi);
  const currentDpi = currentState.selectedPrinter && currentState.selectedPrinterInfo
    ? resolveDpi(currentState.selectedPrinterInfo.dpi, savedDpi)
    : savedDpi;
  const dpiScale = currentDpi / savedDpi;
  const width = Math.max(1, Math.round((Number(normalized.width ?? currentState.canvasWidth) || 384) * dpiScale));
  const height = Math.max(1, Math.round((Number(normalized.height ?? currentState.canvasHeight) || 384) * dpiScale));
  if (width > 20_000 || height > 20_000) {
    throw new Error('This document exceeds the canvas dimension limit at the selected resolution.');
  }
  const normalizedBatchRecords = Array.isArray(normalized.batchRecords)
    ? normalized.batchRecords.filter((record) => record && typeof record === 'object').slice(0, MAX_BATCH_RECORDS)
    : [];
  const batchRecords = normalizedBatchRecords.length ? normalizedBatchRecords : [{}];
  const rawPageLayouts = (Array.isArray(normalized.pageLayouts) && normalized.pageLayouts.length
    ? normalized.pageLayouts
    : [{ pageIndex: 0, htmlContent: '', activeTemplate: null }]
  ).filter((layout) => layout && typeof layout === 'object').map((layout) => {
    const pageIndex = normalizePageIndex(layout?.pageIndex);
    if (!layout?.activeTemplate?.id) {
      return {
        ...layout,
        pageIndex,
        htmlContent: typeof layout.htmlContent === 'string' ? layout.htmlContent : '',
        activeTemplate: null
      };
    }

    return {
      ...layout,
      pageIndex,
      htmlContent: buildTemplateHtml(
        layout.activeTemplate.id,
        layout.activeTemplate.params || {},
        width,
        height
      )
    };
  });
  const pageLayouts = [...new Map(rawPageLayouts.map((layout) => [layout.pageIndex, layout])).values()];
  if (pageLayouts.length === 0) pageLayouts.push({ pageIndex: 0, htmlContent: '', activeTemplate: null });
  const items = (normalized.items || []).map((item, index) => scaleItemForDpi({
    ...item,
    id: String(item.id ?? `recovered-${index}`),
    pageIndex: normalizePageIndex(item.pageIndex)
  }, dpiScale));
  const allowedBorders = new Set(['none', 'box', 'top', 'bottom', 'cut_line']);

  return {
    canvasWidth: width,
    canvasHeight: height,
    currentDpi,
    canvasBorder: allowedBorders.has(normalized.canvasBorder) ? normalized.canvasBorder : 'none',
    canvasBorderThickness: Math.max(1, Number(normalized.canvasBorderThickness) || 4),
    splitMode: Boolean(normalized.splitMode),
    pageLayouts,
    isRotated: Boolean(normalized.isRotated),
    batchRecords,
    printCopies: Math.min(MAX_PRINT_COPIES, Math.max(1, Number(normalized.printCopies) || 1)),
    currentPage: normalizePageIndex(normalized.currentPage),
    items: recalcAutoFit(items, batchRecords, width, height),
    selectedId: null,
    selectedIds: [],
    selectedPagesForPrint: []
  };
};

import { recalcAutoFit } from '../../domain/normalization';
import { describePrintError } from '../../utils/apiErrors';
import { apiJson } from '../../utils/apiClient';
import { isPrintReceipt } from '../../domain/print';
import { isPreparedPrintReceipt } from '../../domain/preparedPrint';
import { serializeCanvasDocument } from '../../domain/document';
import { buildBatchMatrix, buildBatchSequence, getPrintJobCount, getRenderPixelCount, MAX_BATCH_RECORDS, MAX_PRINT_COPIES, MAX_PRINT_JOBS, MAX_RENDER_PIXELS } from '../../utils/batchData';

let nextPrintJobId = 0;

export const createBatchSlice = (set, get) => ({
  getStageB64: async () => {
    if (typeof window !== 'undefined' && window.__getStageB64) {
      return await window.__getStageB64();
    }
    return null;
  },
  batchRecords: [{}],
  printCopies: 1,
  selectedPagesForPrint: [],
  isPreparingForPrint: false,
  pendingPrintJob: null,
  printPreparationProgress: null,
  reportPrintPreparation: (jobId, completed) => {
    const state = get();
    if (!state.isPreparingForPrint || state.pendingPrintJob?.id !== jobId || !state.printPreparationProgress) return;
    set({ printPreparationProgress: { ...state.printPreparationProgress,
      completed: Math.max(state.printPreparationProgress.completed, Math.min(completed, state.printPreparationProgress.total)) } });
  },
  isPrinting: false,
  lastPrintReceipt: null,
  setIsPrinting: (val) => set({ isPrinting: val }),
  togglePageForPrint: (pageIndex) => set((state) => {
    const current = state.selectedPagesForPrint;
    if (current.includes(pageIndex)) {
      return { selectedPagesForPrint: current.filter((p) => p !== pageIndex) };
    }
    return { selectedPagesForPrint: [...current, pageIndex] };
  }),
  printPages: async (pageIndices) => {
    const state = get();

    if (state.isPreparingForPrint || state.isPrinting) {
      return;
    }

    if (!state.selectedPrinter) {
      set({ apiError: 'Select an available printer before printing. You can keep designing without one.' });
      return;
    }

    if (state.selectedPrinterInfo?.transport === 'offline') {
      set({ apiError: 'This is an offline profile. Scan and select the physical printer before printing.' });
      return;
    }

    const normalizedPageIndices = Array.from(
      new Set((pageIndices || []).map((pageIndex) => Math.max(0, Number(pageIndex) || 0)))
    ).sort((a, b) => a - b);
    if (normalizedPageIndices.length === 0) return;

    const printJobCount = getPrintJobCount({
      records: state.batchRecords?.length || 1,
      copies: state.printCopies || 1,
      pages: normalizedPageIndices.length
    });
    if (printJobCount > MAX_PRINT_JOBS) {
      set({ apiError: `This print request would create ${printJobCount.toLocaleString()} labels. `
        + `Reduce pages, records, or copies to ${MAX_PRINT_JOBS.toLocaleString()} jobs or fewer.` });
      return;
    }
    const renderPixels = getRenderPixelCount({
      width: state.canvasWidth,
      height: state.canvasHeight,
      jobs: printJobCount
    });
    if (renderPixels > MAX_RENDER_PIXELS) {
      set({ apiError: 'This print request is too large to render safely in memory. '
        + 'Reduce the label dimensions, pages, records, or copies and try again.' });
      return;
    }

    let itemsToPrint = state.items;
    let finalBatchRecords = state.batchRecords || [{}];
    let finalPageIndices = normalizedPageIndices;

    itemsToPrint = state.items.filter((item) =>
      normalizedPageIndices.includes(Number(item.pageIndex ?? 0))
    );

    set({
      isPreparingForPrint: true,
      printPreparationProgress: { completed: 0, total: printJobCount },
      lastPrintReceipt: null,
      pendingPrintJob: {
        id: ++nextPrintJobId,
        macAddress: state.selectedPrinter,
        splitMode: state.splitMode,
        pageIndices: finalPageIndices,
        copies: state.printCopies || 1,
        batchRecords: finalBatchRecords,
        dither: state.dither,
        canvasState: serializeCanvasDocument({ ...state, items: itemsToPrint })
      }
    });
  },
  onLocalRenderComplete: async (images, renderError = null, jobId) => {
    const state = get();
    const pendingPrintJob = state.pendingPrintJob;

    if (!pendingPrintJob || pendingPrintJob.id !== jobId || state.isPrinting || !state.isPreparingForPrint) return false;
    set({ isPreparingForPrint: false, printPreparationProgress: null });

    if (renderError) {
      set({ pendingPrintJob: null });
      set({ apiError: `Could not prepare labels for printing: ${renderError.message || renderError}` });
      return;
    }

    const prepared = isPreparedPrintReceipt(images) ? images : null;
    if (prepared && prepared.next_index !== prepared.total) {
      set({ pendingPrintJob: null, apiError: 'Label preparation is incomplete. Nothing was submitted.' });
      return false;
    }
    if (!prepared && (!images || images.length === 0)) {
      set({ pendingPrintJob: null });
      return;
    }

    set({ isPrinting: true });

    try {
      // A committed print can outlast a browser deadline. Keep the submission
      // guard until the backend responds; its printer operations own timeouts.
      const receipt = await apiJson(prepared ? `/api/print/prepared/${prepared.prepared_id}/commit` : '/api/print/images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: pendingPrintJob.macAddress,
          ...(prepared ? {} : { images }),
          split_mode: pendingPrintJob.splitMode,
          is_rotated: pendingPrintJob.canvasState.isRotated || false,
          dither: pendingPrintJob.dither
        })
      }, { timeoutMs: 0, fallback: 'Print failed', validate: isPrintReceipt,
        validationMessage: 'The server returned an unexpected print receipt. Some labels may already have printed. Check the physical output before submitting again.' });
      set({ lastPrintReceipt: { ...receipt, printerAddress: pendingPrintJob.macAddress } });
    } catch (e) {
      console.error(e);
      const message = await describePrintError(e);
      set({ apiError: `Print failed: ${message}` });
    } finally {
      set({ isPrinting: false, pendingPrintJob: null });
    }
  },
  setBatchRecords: (records) => set((state) => {
    const validRecords = Array.isArray(records) && records.length ? records : [{}];
    if (validRecords.length > MAX_BATCH_RECORDS) {
      return {
        batchGenerationError: `Batch data is limited to ${MAX_BATCH_RECORDS.toLocaleString()} records.`
      };
    }
    return {
      batchRecords: validRecords,
      batchGenerationError: '',
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  batchGenerationError: '',
  clearBatchGenerationError: () => set({ batchGenerationError: '' }),
  generateBatchMatrix: (matrixDef) => {
    try {
      get().setBatchRecords(buildBatchMatrix(matrixDef));
      return true;
    } catch (error) {
      set({ batchGenerationError: error.message });
      return false;
    }
  },
  generateBatchSequence: (seqDef) => {
    try {
      get().setBatchRecords(buildBatchSequence(seqDef));
      return true;
    } catch (error) {
      set({ batchGenerationError: error.message });
      return false;
    }
  },
  updateBatchRecord: (index, newRecord) => set((state) => {
    const newRecords = [...state.batchRecords];
    newRecords[index] = newRecord;
    return {
      batchRecords: newRecords,
      items: recalcAutoFit(state.items, newRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  addBatchRecord: (record = {}) => set((state) => {
    if (state.batchRecords.length >= MAX_BATCH_RECORDS) {
      return {
        batchGenerationError: `Batch data is limited to ${MAX_BATCH_RECORDS.toLocaleString()} records.`
      };
    }
    const newRecords = [...state.batchRecords, record];
    return {
      batchRecords: newRecords,
      batchGenerationError: '',
      items: recalcAutoFit(state.items, newRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  removeBatchRecord: (index) => set((state) => {
    const newRecords = state.batchRecords.filter((_, i) => i !== index);
    const validRecords = newRecords.length ? newRecords : [{}];
    return {
      batchRecords: validRecords,
      items: recalcAutoFit(state.items, validRecords, state.canvasWidth, state.canvasHeight)
    };
  }),
  setPrintCopies: (n) => set({
    printCopies: Math.min(MAX_PRINT_COPIES, Math.max(1, Number(n) || 1))
  })
});

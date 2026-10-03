import { recalcAutoFit } from '../../domain/normalization';
import { describePrintError } from '../../utils/apiErrors';
import { apiFetch } from '../../utils/apiClient';
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
  isPrinting: false,
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
      alert("Please select a printer first!");
      return;
    }

    if (state.selectedPrinterInfo?.transport === 'offline') {
      alert("This is an offline/manual printer profile. Scan and select a connected printer before printing.");
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
      alert(
        `This print request would create ${printJobCount.toLocaleString()} labels. `
        + `Reduce pages, records, or copies to ${MAX_PRINT_JOBS.toLocaleString()} jobs or fewer.`
      );
      return;
    }
    const renderPixels = getRenderPixelCount({
      width: state.canvasWidth,
      height: state.canvasHeight,
      jobs: printJobCount
    });
    if (renderPixels > MAX_RENDER_PIXELS) {
      alert(
        'This print request is too large to render safely in memory. '
        + 'Reduce the label dimensions, pages, records, or copies and try again.'
      );
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
      pendingPrintJob: {
        id: ++nextPrintJobId,
        macAddress: state.selectedPrinter,
        splitMode: state.splitMode,
        pageIndices: finalPageIndices,
        copies: state.printCopies || 1,
        batchRecords: finalBatchRecords,
        dither: state.dither,
        canvasState: {
          width: state.canvasWidth,
          height: state.canvasHeight,
          isRotated: state.isRotated,
          canvasBorder: state.canvasBorder,
          canvasBorderThickness: state.canvasBorderThickness || 4,
          splitMode: state.splitMode,
          pageLayouts: state.pageLayouts,
          items: itemsToPrint
        }
      }
    });
  },
  onLocalRenderComplete: async (images, renderError = null) => {
    const state = get();
    const pendingPrintJob = state.pendingPrintJob;

    set({ isPreparingForPrint: false });

    if (!pendingPrintJob) {
      return;
    }

    if (renderError) {
      set({ pendingPrintJob: null });
      alert(`Failed to prepare labels for printing:\n\n${renderError.message || renderError}`);
      return;
    }

    if (!images || images.length === 0) {
      set({ pendingPrintJob: null });
      return;
    }

    set({ isPrinting: true });

    try {
      await apiFetch(`/api/print/images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: pendingPrintJob.macAddress,
          images,
          split_mode: pendingPrintJob.splitMode,
          is_rotated: pendingPrintJob.canvasState.isRotated || false,
          dither: pendingPrintJob.dither
        })
      }, { timeoutMs: 120_000, fallback: 'Print failed' });
    } catch (e) {
      console.error(e);
      const message = await describePrintError(e);
      alert(`Failed to print:\n\n${message}`);
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

import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useStore } from '../../store';
import * as apiClient from '../../utils/apiClient';
const original = useStore.getState();
beforeEach(() => useStore.setState({ ...original, selectedPrinter: 'AA:BB:CC:DD:EE:FF', selectedPrinterInfo: { transport: 'ble' }, pendingPrintJob: null, isPrinting: false, isPreparingForPrint: false, lastPrintReceipt: null }, true));
afterEach(() => { useStore.setState(original, true); vi.restoreAllMocks(); });
test('pending rendering uses the central versioned DPI document snapshot', async () => {
  useStore.setState({ currentDpi: 300, canvasWidth: 600, canvasHeight: 300, items: [{ id: 'a', pageIndex: 0 }, { id: 'b', pageIndex: 1 }] });
  await useStore.getState().printPages([0]);
  expect(useStore.getState().pendingPrintJob.canvasState).toMatchObject({ document_version: 1, dpi: 300, width: 600, height: 300, items: [{ id: 'a' }] });
});
test('submission retains a receipt with physical completion unverified', async () => {
  const receipt = { status: 'submitted', submitted: 1, physical_completion: 'unverified', job_id: 'fixture', message: 'Data sent' };
  const submit = vi.spyOn(apiClient, 'apiJson').mockResolvedValue(receipt);
  await useStore.getState().printPages([0]); await useStore.getState().onLocalRenderComplete(['fixture-image'], null, useStore.getState().pendingPrintJob.id);
  expect(submit).toHaveBeenCalledWith('/api/print/images', expect.objectContaining({ method: 'POST' }), expect.objectContaining({ validate: expect.any(Function), timeoutMs: 0 }));
  expect(useStore.getState()).toMatchObject({ lastPrintReceipt: { ...receipt, printerAddress: 'AA:BB:CC:DD:EE:FF' }, isPrinting: false, pendingPrintJob: null });
});

test('cancelled or superseded preparation cannot submit and duplicate completion sends once', async () => {
  let finish;
  const receipt = { status: 'submitted', submitted: 1, physical_completion: 'unverified', job_id: 'one', message: 'Sent' };
  const submit = vi.spyOn(apiClient, 'apiJson').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await useStore.getState().printPages([0]); const oldId = useStore.getState().pendingPrintJob.id;
  await useStore.getState().onLocalRenderComplete([], new Error('Cancelled'), oldId);
  await useStore.getState().printPages([0]); const id = useStore.getState().pendingPrintJob.id;
  await useStore.getState().onLocalRenderComplete(['stale'], null, oldId);
  expect(useStore.getState()).toMatchObject({ isPreparingForPrint: true, pendingPrintJob: { id } });
  expect(submit).not.toHaveBeenCalled();
  const first = useStore.getState().onLocalRenderComplete(['image'], null, id);
  await useStore.getState().onLocalRenderComplete(['duplicate'], null, id);
  expect(submit).toHaveBeenCalledOnce();
  finish(receipt); await first;
  expect(useStore.getState().lastPrintReceipt.job_id).toBe('one');
});

test('a completed staged receipt commits once without serializing all image payloads', async () => {
  const receipt = { status: 'submitted', submitted: 1, physical_completion: 'unverified', job_id: 'staged', message: 'Sent' };
  const submit = vi.spyOn(apiClient, 'apiJson').mockResolvedValue(receipt);
  await useStore.getState().printPages([0]); const id = useStore.getState().pendingPrintJob.id;
  const staged = { prepared_id: 'a'.repeat(32), total: 1, next_index: 1 };
  await useStore.getState().onLocalRenderComplete(staged, null, id);
  await useStore.getState().onLocalRenderComplete(staged, null, id);
  expect(submit).toHaveBeenCalledOnce();
  expect(submit.mock.calls[0][0]).toBe(`/api/print/prepared/${staged.prepared_id}/commit`);
  expect(JSON.parse(submit.mock.calls[0][1].body)).toEqual(expect.objectContaining({ mac_address: 'AA:BB:CC:DD:EE:FF' }));
  expect(JSON.parse(submit.mock.calls[0][1].body)).not.toHaveProperty('images');
  expect(useStore.getState().lastPrintReceipt.job_id).toBe('staged');
});


test('a print still running after two minutes stays guarded until its receipt arrives', async () => {
  vi.useFakeTimers();
  const receipt = { status: 'submitted', submitted: 1, physical_completion: 'unverified', job_id: 'slow', message: 'Sent' };
  let finish;
  const request = vi.fn((_url, options) => new Promise(resolve => {
    finish = () => resolve(new Response(JSON.stringify(receipt), { status: 200 }));
    expect(options.signal.aborted).toBe(false);
  }));
  vi.stubGlobal('fetch', request);
  try {
    await useStore.getState().printPages([0]);
    const id = useStore.getState().pendingPrintJob.id;
    const submission = useStore.getState().onLocalRenderComplete(['image'], null, id);
    await vi.advanceTimersByTimeAsync(121_000);
    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0][1].signal.aborted).toBe(false);
    expect(useStore.getState()).toMatchObject({ isPrinting: true, pendingPrintJob: { id }, lastPrintReceipt: null });
    await useStore.getState().printPages([0]);
    await useStore.getState().onLocalRenderComplete(['duplicate'], null, id);
    expect(request).toHaveBeenCalledOnce();
    finish();
    await submission;
    expect(useStore.getState()).toMatchObject({ isPrinting: false, pendingPrintJob: null, lastPrintReceipt: { job_id: 'slow' } });
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

test('preparation progress rejects stale callbacks and cannot move backwards', async () => {
  await useStore.getState().printPages([0]);
  const id = useStore.getState().pendingPrintJob.id;
  useStore.getState().reportPrintPreparation(id, 1);
  useStore.getState().reportPrintPreparation(id, 0);
  expect(useStore.getState().printPreparationProgress).toEqual({ completed: 1, total: 1 });
  await useStore.getState().onLocalRenderComplete([], new Error('Cancelled'), id);
  await useStore.getState().printPages([0]);
  useStore.getState().reportPrintPreparation(id, 1);
  expect(useStore.getState().printPreparationProgress).toEqual({ completed: 0, total: 1 });
});

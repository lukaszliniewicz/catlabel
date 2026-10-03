import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { useCodeGenerator } from './rendering';

const generators = vi.hoisted(() => ({ barcode: vi.fn(), qr: vi.fn() }));
vi.mock('bwip-js', () => ({ default: { toCanvas: generators.barcode } }));
vi.mock('qrcode', () => ({ default: { toDataURL: generators.qr } }));
let root, container;
function Code({ type, data, barcodeType }) {
  const src = useCodeGenerator(type, data, barcodeType);
  return <output>{src || 'Pending'}</output>;
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  generators.barcode.mockReset(); generators.qr.mockReset();
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,barcode');
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); });

test('100 mounted copies share barcode generation with the original canvas options', async () => {
  await act(() => root.render(<>{Array.from({ length: 100 }, (_, index) => <Code key={index} type="barcode" data="shared-copy-100" barcodeType="code39" />)}</>));
  expect(generators.barcode).toHaveBeenCalledTimes(1);
  expect(generators.barcode.mock.calls[0][1]).toEqual({ bcid: 'code39', text: 'shared-copy-100', scale: 12, includetext: false, backgroundcolor: 'FFFFFF' });
  expect([...container.querySelectorAll('output')].every(output => output.textContent === 'data:image/png;base64,barcode')).toBe(true);
});

test('a late old QR generation cannot replace the new code value', async () => {
  let finishOld; generators.qr.mockImplementation(value => value === 'old-qr' ? new Promise(resolve => { finishOld = resolve; }) : Promise.resolve('data:image/png;base64,new'));
  await act(() => root.render(<Code type="qrcode" data="old-qr" />));
  await act(() => root.render(<Code type="qrcode" data="new-qr" />)); expect(container.textContent).toBe('data:image/png;base64,new');
  await act(() => finishOld('data:image/png;base64,old')); expect(container.textContent).toBe('data:image/png;base64,new');
  expect(generators.qr.mock.calls[1][1]).toEqual({ margin: 1, scale: 24, color: { dark: '#000000', light: '#FFFFFF' } });
});

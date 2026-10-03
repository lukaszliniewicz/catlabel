import { expect, test } from 'vitest';
import { isPreparedPrintReceipt, pngDataUrlToBlob } from './preparedPrint';
const receipt = { prepared_id: 'a'.repeat(32), total: 2, next_index: 1 };
test('only valid monotonic preparation DTOs cross the typed boundary', () => {
  expect(isPreparedPrintReceipt(receipt)).toBe(true);
  for (const invalid of [null, [], { ...receipt, prepared_id: '../unsafe' }, { ...receipt, total: 0 }, { ...receipt, total: Infinity }, { ...receipt, next_index: true }, { ...receipt, next_index: 3 }, { ...receipt, next_index: -1 }]) expect(isPreparedPrintReceipt(invalid)).toBe(false);
});
test('one PNG becomes a bounded binary blob without an accumulated base64 list', () => {
  const blob = pngDataUrlToBlob('data:image/png;base64,' + btoa('bytes'), 5);
  expect(blob.type).toBe('image/png'); expect(blob.size).toBe(5);
  expect(() => pngDataUrlToBlob('data:image/png;base64,' + btoa('too long'), 5)).toThrow('size limit');
  expect(() => pngDataUrlToBlob('data:image/jpeg;base64,AA==', 5)).toThrow('not a PNG');
  expect(() => pngDataUrlToBlob('data:image/png;base64,!broken', 5)).toThrow();
});

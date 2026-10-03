import { expect, test } from 'vitest';

import { isPrintReceipt } from './print';

test('accepts the empty receipt without claiming physical completion', () => {
  expect(isPrintReceipt({
    status: 'empty',
    submitted: 0,
    physical_completion: 'unverified',
    metadata: 'retained',
  })).toBe(true);
  expect(isPrintReceipt({
    status: 'empty',
    submitted: 0,
    physical_completion: 'complete',
  })).toBe(false);
  expect(isPrintReceipt({
    status: 'empty',
    submitted: 1,
    physical_completion: 'unverified',
  })).toBe(false);
});

test('accepts submitted receipts and rejects malformed required fields', () => {
  const receipt = {
    status: 'submitted',
    submitted: 3,
    physical_completion: 'unverified',
    job_id: 'e9c3a1b2',
    message: 'Label data sent. Check the printer for the physical output.',
    mac_address: 'AA:BB:CC:DD:EE:FF',
    transport_metadata: { attempt: 1 },
  };

  expect(isPrintReceipt(receipt)).toBe(true);

  for (const invalidSubmitted of ['3', -1, 0, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    expect(isPrintReceipt({ ...receipt, submitted: invalidSubmitted })).toBe(false);
  }
  expect(isPrintReceipt({ ...receipt, job_id: 9 })).toBe(false);
  expect(isPrintReceipt({ ...receipt, job_id: '' })).toBe(false);
});

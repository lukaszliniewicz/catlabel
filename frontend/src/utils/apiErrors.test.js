import { expect, test } from 'vitest';

import {
  ApiRequestError,
  apiErrorFromResponse,
  describePrintError,
} from './apiErrors';

test('structured print errors retain the backend stage and cause', async () => {
  const response = {
    status: 503,
    text: async () => JSON.stringify({
      detail: {
        message: 'Could not connect to the printer.',
        stage: 'connect',
        error: 'Access is denied.',
        suggestion: 'Pair the printer first.',
        error_id: 'deadbeef',
      },
    }),
  };

  const error = await apiErrorFromResponse(response, 'Print failed');
  expect(error).toBeInstanceOf(ApiRequestError);
  expect(error.stage).toBe('connect');
  expect(error.technicalDetail).toBe('Access is denied.');

  const message = await describePrintError(error);
  expect(message).toMatch(/Access is denied/);
  expect(message).toMatch(/reference: deadbeef/);
  expect(message).toMatch(/HTTP 503/);
});

test('network failures distinguish a stopped server from an API error', async () => {
  const message = await describePrintError(
    new TypeError('Failed to fetch'),
    async () => false,
  );
  expect(message).toMatch(/server stopped responding/i);
  expect(message).not.toMatch(/^Failed to fetch$/);
});

test('plain-text HTTP failures are still useful', async () => {
  const error = await apiErrorFromResponse({
    status: 500,
    text: async () => 'Internal Server Error',
  });
  expect(error.message).toBe('Internal Server Error');
  expect(error.status).toBe(500);
});

test('lost responses and timeouts warn about uncertain delivery', async () => {
  for (const error of [
    new TypeError('Failed to fetch'),
    new ApiRequestError('Request timed out.', { stage: 'frontend_request' }),
  ]) {
    const message = await describePrintError(error, async () => true);
    expect(message).toMatch(/physical output/i);
    expect(message).toMatch(/duplicate/i);
    expect(message).not.toMatch(/scan.*and retry/i);
  }
});

test('structured delivery uncertainty survives parsing', async () => {
  const error = await apiErrorFromResponse({
    status: 500,
    text: async () => JSON.stringify({ detail: {
      message: 'Some labels may already have printed.',
      delivery_uncertain: true,
      stage: 'end_page',
    } }),
  });
  expect(error.deliveryUncertain).toBe(true);
});

test('validation-list details remain readable', async () => {
  const error = await apiErrorFromResponse({
    status: 422,
    text: async () => JSON.stringify({ detail: [
      { loc: ['body', 'mac_address'], msg: 'Field required' },
      { loc: ['body', 'images'], msg: 'Input should be a valid list' },
    ] }),
  });

  expect(error.message).toBe('Field required; Input should be a valid list');
});

test('malformed structured error metadata is narrowed defensively', async () => {
  const error = await apiErrorFromResponse({
    status: 400,
    text: async () => JSON.stringify({ detail: {
      message: 7,
      stage: { name: 'connect' },
      error: ['bad field'],
      suggestion: false,
      error_id: 123,
      delivery_uncertain: 'yes',
    } }),
  });

  expect(error.status).toBe(400);
  expect(error.message).toContain('"message":7');
  expect(error.stage).toBeUndefined();
  expect(error.technicalDetail).toBeUndefined();
  expect(error.suggestion).toBeUndefined();
  expect(error.errorId).toBeUndefined();
  expect(error.deliveryUncertain).toBeUndefined();
});

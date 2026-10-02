import { ApiRequestError, apiErrorFromResponse } from './apiErrors';

const DEFAULT_TIMEOUT_MS = 30_000;

export const isArrayPayload = (value) => Array.isArray(value);
export const isObjectPayload = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

export const apiFetch = async (input, init = {}, options = {}) => {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const externalSignal = init.signal;
  let timedOut = false;

  const abortFromExternalSignal = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) abortFromExternalSignal();
  else externalSignal?.addEventListener('abort', abortFromExternalSignal, { once: true });

  const timeoutId = timeoutMs > 0
    ? globalThis.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeoutMs)
    : null;

  try {
    const headers = new Headers(init.headers);
    headers.set('X-CatLabel-Client', '1');
    const response = await fetch(input, { ...init, headers, signal: controller.signal });
    if (!response.ok) {
      throw await apiErrorFromResponse(response, options.fallback || 'Request failed');
    }
    return response;
  } catch (error) {
    if (timedOut) {
      const timeoutLabel = timeoutMs >= 1000
        ? `${Math.round(timeoutMs / 1000)} seconds`
        : `${timeoutMs} milliseconds`;
      throw new ApiRequestError(`Request timed out after ${timeoutLabel}.`, {
        status: 0,
        stage: 'frontend_request'
      });
    }
    throw error;
  } finally {
    if (timeoutId !== null) globalThis.clearTimeout(timeoutId);
    externalSignal?.removeEventListener('abort', abortFromExternalSignal);
  }
};

export const apiJson = async (input, init = {}, options = {}) => {
  const response = await apiFetch(input, init, options);
  const data = await response.json();
  if (options.validate && !options.validate(data)) {
    throw new ApiRequestError(options.validationMessage || 'The server returned an unexpected response.', {
      status: response.status,
      stage: 'response_validation'
    });
  }
  return data;
};

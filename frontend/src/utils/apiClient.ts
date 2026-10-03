import { ApiRequestError, apiErrorFromResponse } from './apiErrors';

const DEFAULT_TIMEOUT_MS = 30_000;

export interface ApiRequestOptions {
  timeoutMs?: number | undefined;
  fallback?: string | undefined;
}

export interface ApiJsonOptions extends ApiRequestOptions {
  validate?: ((value: unknown) => boolean) | undefined;
  validationMessage?: string | undefined;
}

export const isArrayPayload = (value: unknown): value is unknown[] => Array.isArray(value);

export const isObjectPayload = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

type ResponseDecoder<T> = (response: Response) => T | Promise<T>;

const timeoutError = (timeoutMs: number): ApiRequestError => {
  const timeoutLabel = timeoutMs >= 1000
    ? `${Math.round(timeoutMs / 1000)} seconds`
    : `${timeoutMs} milliseconds`;
  return new ApiRequestError(`Request timed out after ${timeoutLabel}.`, {
    status: 0,
    stage: 'frontend_request',
  });
};

const requestWithDeadline = async <T>(
  input: RequestInfo | URL,
  init: RequestInit,
  options: ApiRequestOptions,
  decode: ResponseDecoder<T>,
): Promise<T> => {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const externalSignal = init.signal;
  if (externalSignal?.aborted) throw externalSignal.reason;

  let timedOut = false;
  let externallyAborted = false;
  let rejectOnAbort!: (reason: unknown) => void;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectOnAbort = reject;
  });

  const abortFromExternalSignal = (): void => {
    externallyAborted = true;
    const reason: unknown = externalSignal?.reason;
    controller.abort(reason);
    rejectOnAbort(reason);
  };
  externalSignal?.addEventListener('abort', abortFromExternalSignal, { once: true });

  let timeoutId: ReturnType<typeof globalThis.setTimeout> | undefined;
  if (timeoutMs > 0) {
    timeoutId = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort();
      rejectOnAbort(controller.signal.reason);
    }, timeoutMs);
  }

  try {
    const request = (async (): Promise<T> => {
      const headers = new Headers(init.headers);
      headers.set('X-CatLabel-Client', '1');
      const response = await fetch(input, { ...init, headers, signal: controller.signal });
      if (!response.ok) {
        throw await apiErrorFromResponse(response, options.fallback || 'Request failed');
      }
      return await decode(response);
    })();

    return await Promise.race([request, aborted]);
  } catch (error: unknown) {
    if (externallyAborted) throw externalSignal?.reason;
    if (timedOut) throw timeoutError(timeoutMs);
    throw error;
  } finally {
    if (timeoutId !== undefined) globalThis.clearTimeout(timeoutId);
    externalSignal?.removeEventListener('abort', abortFromExternalSignal);
  }
};

export const apiFetch = (
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<Response> => requestWithDeadline(input, init, options, (response) => response);

export const apiBlob = (
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<Blob> => requestWithDeadline(input, init, options, (response) => response.blob());

export function apiJson<T>(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  options: ApiJsonOptions & { validate: (value: unknown) => value is T },
): Promise<T>;
export function apiJson(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: ApiJsonOptions,
): Promise<unknown>;
export async function apiJson(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: ApiJsonOptions = {},
): Promise<unknown> {
  return requestWithDeadline(input, init, options, async (response) => {
    const data: unknown = await response.json();
    if (options.validate && !options.validate(data)) {
      throw new ApiRequestError(options.validationMessage || 'The server returned an unexpected response.', {
        status: response.status,
        stage: 'response_validation',
      });
    }
    return data;
  });
}

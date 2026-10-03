export interface ApiRequestErrorDetails {
  status?: number | undefined;
  stage?: string | undefined;
  technicalDetail?: string | undefined;
  suggestion?: string | undefined;
  errorId?: string | undefined;
  deliveryUncertain?: boolean | undefined;
}

export class ApiRequestError extends Error {
  readonly status: number | undefined;
  readonly stage: string | undefined;
  readonly technicalDetail: string | undefined;
  readonly suggestion: string | undefined;
  readonly errorId: string | undefined;
  readonly deliveryUncertain: boolean | undefined;

  constructor(message: string, details: ApiRequestErrorDetails = {}) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = details.status;
    this.stage = details.stage;
    this.technicalDetail = details.technicalDetail;
    this.suggestion = details.suggestion;
    this.errorId = details.errorId;
    this.deliveryUncertain = details.deliveryUncertain;
  }
}

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
);

const stringField = (value: UnknownRecord, field: string): string | undefined => {
  const candidate = value[field];
  return typeof candidate === 'string' ? candidate : undefined;
};

const detailText = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value
      .map((item: unknown) => {
        if (isRecord(item)) {
          return stringField(item, 'msg')
            || stringField(item, 'message')
            || detailText(item);
        }
        return detailText(item);
      })
      .filter((item: string) => Boolean(item))
      .join('; ');
  }
  if (isRecord(value)) {
    const message = stringField(value, 'message');
    if (message) return message;
    const error = stringField(value, 'error');
    if (error) return error;
    try {
      return JSON.stringify(value) ?? '';
    } catch {
      return '';
    }
  }
  return '';
};

export const apiErrorFromResponse = async (
  response: Pick<Response, 'status' | 'text'>,
  fallback = 'Request failed',
): Promise<ApiRequestError> => {
  let payload: unknown = null;
  let responseText = '';

  try {
    responseText = await response.text();
    payload = responseText ? JSON.parse(responseText) : null;
  } catch {
    // Plain-text and empty error responses are valid failure modes.
  }

  const topLevel = isRecord(payload) ? payload : null;
  const detailCandidate = topLevel?.detail;
  const detail: unknown = detailCandidate ?? payload;
  const structured = isRecord(detail) ? detail : {};
  const message = stringField(structured, 'message')
    || detailText(detail)
    || responseText.trim()
    || `${fallback} (HTTP ${response.status})`;

  return new ApiRequestError(message, {
    status: response.status,
    stage: stringField(structured, 'stage'),
    technicalDetail: stringField(structured, 'error'),
    suggestion: stringField(structured, 'suggestion'),
    errorId: stringField(structured, 'error_id'),
    deliveryUncertain: typeof structured.delivery_uncertain === 'boolean'
      ? structured.delivery_uncertain
      : undefined,
  });
};

const checkServerHealth = async (): Promise<boolean> => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch('/api/health', {
      headers: { 'X-CatLabel-Client': '1' },
      cache: 'no-store',
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
};

const errorMessage = (error: unknown): string | undefined => {
  if (
    error !== null
    && (typeof error === 'object' || typeof error === 'function')
    && 'message' in error
    && typeof error.message === 'string'
  ) {
    return error.message;
  }
  return undefined;
};

const isNetworkFetchError = (error: unknown): boolean => (
  error instanceof TypeError
  || /failed to fetch|networkerror|network request failed|load failed/i.test(errorMessage(error) || '')
);

export const describePrintError = async (
  error: unknown,
  healthCheck: () => boolean | Promise<boolean> = checkServerHealth,
): Promise<string> => {
  if (error instanceof ApiRequestError) {
    const lines = [error.message];
    if (error.stage === 'frontend_request') {
      lines.push('The browser stopped waiting, but the printer may still be working. Check the physical output before submitting again; retrying can produce duplicate labels.');
    }
    if (error.technicalDetail && error.technicalDetail !== error.message) {
      lines.push(`Technical detail: ${error.technicalDetail}`);
    }
    if (error.suggestion) lines.push(`Next step: ${error.suggestion}`);

    const reference = [
      error.stage ? `stage: ${error.stage}` : null,
      error.status ? `HTTP ${error.status}` : null,
      error.errorId ? `reference: ${error.errorId}` : null,
    ].filter(Boolean).join(', ');
    if (reference) lines.push(`Diagnostic: ${reference}`);
    return lines.join('\n\n');
  }

  if (isNetworkFetchError(error)) {
    const serverIsRunning = await healthCheck();
    if (!serverIsRunning) {
      return [
        'The CatLabel server stopped responding while the print request was running.',
        'Some labels may already have printed. Check the physical output before resubmitting; retrying can produce duplicates. Reopen CatLabel and check the launcher window for the underlying Python or Bluetooth error.',
      ].join('\n\n');
    }
    return [
      'The browser lost the print request, although the CatLabel server is responding again.',
      'The printer may still be working. Check the physical output before resubmitting; retrying can produce duplicates. Check the launcher window for the underlying Bluetooth error.',
      `Browser detail: ${errorMessage(error) || 'Network request failed'}`,
    ].join('\n\n');
  }

  return errorMessage(error) || 'An unknown print error occurred.';
};

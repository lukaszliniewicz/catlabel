interface EmptyPrintReceipt {
  status: 'empty';
  submitted: 0;
  physical_completion: 'unverified';
  [metadata: string]: unknown;
}

interface SubmittedPrintReceipt {
  status: 'submitted';
  submitted: number;
  physical_completion: 'unverified';
  job_id: string;
  message: string;
  mac_address?: string;
  [metadata: string]: unknown;
}

export type PrintReceipt = EmptyPrintReceipt | SubmittedPrintReceipt;

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
);

export const isPrintReceipt = (value: unknown): value is PrintReceipt => {
  if (!isRecord(value) || value.physical_completion !== 'unverified') return false;

  if (value.status === 'empty') {
    return value.submitted === 0;
  }

  if (value.status !== 'submitted') return false;
  if (
    typeof value.submitted !== 'number'
    || !Number.isSafeInteger(value.submitted)
    || value.submitted <= 0
    || typeof value.job_id !== 'string'
    || value.job_id.length === 0
    || typeof value.message !== 'string'
  ) {
    return false;
  }

  return !Object.prototype.hasOwnProperty.call(value, 'mac_address')
    || typeof value.mac_address === 'string';
};

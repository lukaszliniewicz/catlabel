export interface PreparedPrintReceipt {
  prepared_id: string;
  total: number;
  next_index: number;
}

export const isPreparedPrintReceipt = (value: unknown): value is PreparedPrintReceipt => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  return typeof receipt.prepared_id === 'string' && /^[a-f0-9]{32}$/.test(receipt.prepared_id)
    && typeof receipt.total === 'number' && Number.isSafeInteger(receipt.total) && receipt.total > 0
    && typeof receipt.next_index === 'number' && Number.isSafeInteger(receipt.next_index)
    && receipt.next_index >= 0 && receipt.next_index <= receipt.total;
};

export function pngDataUrlToBlob(value: unknown, maxBytes: number): Blob {
  const prefix = 'data:image/png;base64,';
  if (typeof value !== 'string' || !value.startsWith(prefix)) throw new Error('The rendered label is not a PNG image.');
  const encoded = value.slice(prefix.length);
  if (!encoded.length || encoded.length > 4 * Math.ceil(maxBytes / 3)) throw new Error('The rendered label exceeds the image size limit.');
  const binary = atob(encoded);
  if (binary.length > maxBytes) throw new Error('The rendered label exceeds the image size limit.');
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new Blob([bytes], { type: 'image/png' });
}

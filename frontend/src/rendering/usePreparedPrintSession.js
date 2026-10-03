import { useCallback, useEffect, useRef, useState } from 'react';
import { apiJson } from '../utils/apiClient';
import { isPreparedPrintReceipt, pngDataUrlToBlob } from '../domain/preparedPrint';
import resourceLimits from '../../../catlabel/data/resource_limits.json';

const discard = async preparedId => {
  try { await apiJson(`/api/print/prepared/${preparedId}`, { method: 'DELETE' }); }
  catch { /* Unknown/expired or interrupted cleanup is also covered by server expiry. */ }
};

export function usePreparedPrintSession(total) {
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);
  const sessionRef = useRef(null);
  const handedOff = useRef(false);
  const cancelled = useRef(false);
  const controllerRef = useRef(null);
  useEffect(() => {
    if (total === 0) return undefined;
    let active = true;
    cancelled.current = false;
    const controller = new AbortController();
    controllerRef.current = controller;
    // Let creation finish so a late successful response can still be discarded.
    apiJson('/api/print/prepared', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_jobs: total })
    }, { validate: isPreparedPrintReceipt, validationMessage: 'The server returned invalid preparation data.' }).then(receipt => {
      if (receipt.total !== total || receipt.next_index !== 0) { void discard(receipt.prepared_id); throw new Error('The server returned unexpected preparation data.'); }
      if (!active || cancelled.current) { void discard(receipt.prepared_id); return; }
      sessionRef.current = receipt;
      setSession(receipt);
    }).catch(reason => { if (active && !cancelled.current) setError(reason instanceof Error ? reason : new Error(String(reason))); });
    return () => {
      active = false;
      cancelled.current = true;
      controller.abort();
      if (sessionRef.current && !handedOff.current) { void discard(sessionRef.current.prepared_id); sessionRef.current = null; }
    };
  }, [total]);
  const cancel = useCallback(() => {
    cancelled.current = true;
    controllerRef.current?.abort();
    if (sessionRef.current && !handedOff.current) { void discard(sessionRef.current.prepared_id); sessionRef.current = null; }
  }, []);
  const upload = useCallback(async (value, index) => {
    const current = sessionRef.current;
    if (!current || cancelled.current || handedOff.current) throw new Error('Print preparation is no longer active.');
    const body = new FormData();
    body.append('file', pngDataUrlToBlob(value, resourceLimits.max_image_bytes), `label-${index}.png`);
    const receipt = await apiJson(`/api/print/prepared/${current.prepared_id}/pages/${index}`, {
      method: 'POST', body, signal: controllerRef.current?.signal
    }, { validate: isPreparedPrintReceipt, validationMessage: 'The server returned invalid preparation progress.' });
    if (cancelled.current || receipt.prepared_id !== current.prepared_id || receipt.total !== total || receipt.next_index !== index + 1) {
      throw new Error('The preparation acknowledgement does not match this label.');
    }
    sessionRef.current = receipt;
    return receipt;
  }, [total]);
  const handOff = useCallback(() => {
    const current = sessionRef.current;
    if (!current || cancelled.current || current.next_index !== total) throw new Error('Label preparation is incomplete.');
    handedOff.current = true;
    return current;
  }, [total]);
  const rejectHandOff = useCallback(() => {
    if (sessionRef.current) { void discard(sessionRef.current.prepared_id); sessionRef.current = null; }
  }, []);
  return { ready: Boolean(session), error, upload, handOff, cancel, rejectHandOff };
}

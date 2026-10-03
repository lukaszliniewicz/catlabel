import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { serializeCanvasDocument } from '../domain/document';
import HeadlessPage from './HeadlessPage';

export default function CanvasCapture() {
  const pending = useRef(null);
  const [request, setRequest] = useState(null);
  useEffect(() => {
    const capture = () => new Promise((resolve, reject) => {
      if (pending.current) { reject(new Error('A clean canvas capture is already in progress.')); return; }
      const state = useStore.getState(), id = crypto.randomUUID();
      const timer = setTimeout(() => {
        if (pending.current?.id !== id) return;
        pending.current = null; setRequest(null);
        reject(new Error('Canvas capture timed out. Try again after the label finishes loading.'));
      }, 90_000);
      pending.current = { id, resolve, reject, timer };
      setRequest({ id, pageIndex: state.currentPage, record: state.batchRecords?.[0] || {}, state: serializeCanvasDocument(state) });
    });
    window.__getStageB64 = capture;
    return () => {
      if (window.__getStageB64 === capture) delete window.__getStageB64;
      const active = pending.current; pending.current = null;
      if (active) { clearTimeout(active.timer); active.reject(new Error('Canvas capture was cancelled.')); }
    };
  }, []);
  const finish = (id, data, error) => {
    const active = pending.current;
    if (active?.id !== id) return;
    pending.current = null; clearTimeout(active.timer); setRequest(null);
    if (error) active.reject(error); else active.resolve(data);
  };
  return request && <div aria-hidden="true" style={{ position: 'fixed', left: '-100000px', top: 0 }}>
    <HeadlessPage key={request.id} state={request.state} record={request.record} pageIndex={request.pageIndex}
      onReady={data => finish(request.id, data)} onError={error => finish(request.id, null, error)} />
  </div>;
}

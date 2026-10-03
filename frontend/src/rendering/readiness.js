import { apiBlob } from '../utils/apiClient';

// Readiness belongs to one immutable render job. Never reuse it across snapshots.
export function createRenderReadiness() {
  const resources = new Map();
  const waiters = new Set();
  let scheduled = false;
  const check = () => {
    scheduled = false;
    const error = [...resources.values()].find((resource) => resource.error)?.error;
    const pending = [...resources.values()].some((resource) => !resource.ready);
    if (!error && pending) return;
    for (const waiter of [...waiters]) waiter.finish(error);
  };
  const schedule = () => {
    if (!scheduled) {
      scheduled = true;
      queueMicrotask(check);
    }
  };
  return {
    set(token, ready, error = null) { resources.set(token, { ready, error }); schedule(); },
    remove(token) { resources.delete(token); schedule(); },
    wait(signal) {
      return new Promise((resolve, reject) => {
        const waiter = {
          finish(error) {
            waiters.delete(waiter);
            signal?.removeEventListener('abort', abort);
            if (error) reject(error); else resolve();
          }
        };
        const abort = () => waiter.finish(new Error('Label rendering was cancelled.'));
        if (signal?.aborted) { abort(); return; }
        waiters.add(waiter);
        signal?.addEventListener('abort', abort, { once: true });
        schedule();
      });
    }
  };
}

export function loadRenderImage(src, signal) {
  if (src.startsWith('catlabel://artifacts/')) return loadManagedImage(src, signal);
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(image);
    };
    const abort = () => finish(new Error('Image rendering was cancelled.'));
    const timer = setTimeout(() => finish(new Error('A label image did not load within 8 seconds.')), 8_000);
    image.onload = () => finish(null);
    image.onerror = () => finish(new Error('A label image could not be loaded.'));
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener('abort', abort, { once: true });
    image.src = src;
  });
}

async function loadManagedImage(src, signal) {
  const assetId = encodeURIComponent(src.split('/').at(-1));
  const blob = await apiBlob(`/api/assets/${assetId}`, { signal }, {
    timeoutMs: 8_000, fallback: 'The design image could not be loaded.'
  });
  if (signal?.aborted) throw signal.reason;
  const objectUrl = URL.createObjectURL(blob);
  try {
    return await loadRenderImage(objectUrl, signal);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export const nextPaint = () => new Promise((resolve) => requestAnimationFrame(resolve));

export async function prepareRenderFonts(items, defaultFont = 'Arial') {
  if (!document.fonts) return;
  const requests = new Set([`normal 400 16px "${defaultFont.split('.')[0].replace(/["\\]/g, '')}"`]);
  const collect = (entries) => entries.forEach((item) => {
    const font = String(item.font || defaultFont).split('.')[0].replace(/["\\]/g, '');
    const weight = Number(item.weight) || 700;
    requests.add(`${item.italic ? 'italic' : 'normal'} ${weight} 16px "${font}"`);
    if (Array.isArray(item.children)) collect(item.children);
  });
  collect(items || []);
  await Promise.all([...requests].map((font) => document.fonts.load(font)));
  await document.fonts.ready;
}

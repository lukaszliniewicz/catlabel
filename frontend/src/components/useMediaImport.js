import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { apiJson, isObjectPayload } from '../utils/apiClient';
import limits from '../../../catlabel/data/resource_limits.json';

const changedMessage = 'The design changed during import. Nothing was added; choose the file again when ready.';
const sameDocument = (state, captured) => state.documentSessionId === captured.documentSessionId
  && state.documentRevision === captured.documentRevision && state.currentPage === captured.currentPage;

const readFile = (file, signal) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  const finish = (error, value) => {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
    reader.onload = reader.onerror = reader.onabort = null;
    if (reader.readyState === 1) reader.abort();
    if (error) reject(error); else resolve(value);
  };
  const cancel = () => finish(signal.reason);
  const timer = setTimeout(() => finish(new Error('Reading the image timed out.')), 30_000);
  signal.addEventListener('abort', cancel, { once: true });
  reader.onload = () => typeof reader.result === 'string' ? finish(null, reader.result) : finish(new Error('The image could not be read.'));
  reader.onerror = () => finish(new Error('The image could not be read.'));
  reader.onabort = () => finish(new Error('Image reading was cancelled.'));
  if (signal.aborted) cancel(); else {
    try { reader.readAsDataURL(file); } catch (error) { finish(error); }
  }
});

const imageDimensions = (source, signal) => new Promise((resolve, reject) => {
  const image = new window.Image();
  const finish = (error, value) => {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
    image.onload = image.onerror = null;
    image.src = '';
    if (error) reject(error); else resolve(value);
  };
  const cancel = () => finish(signal.reason);
  const timer = setTimeout(() => finish(new Error('An imported image timed out while loading.')), 8_000);
  signal.addEventListener('abort', cancel, { once: true });
  image.onload = () => {
    const width = image.naturalWidth, height = image.naturalHeight;
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0
      || width > limits.max_dimension || height > limits.max_dimension || width * height > limits.max_render_pixels) {
      finish(new Error('An imported image exceeds the supported dimensions.'));
    } else finish(null, { width, height });
  };
  image.onerror = () => finish(new Error('An imported image could not be decoded. Nothing was added.'));
  if (signal.aborted) cancel(); else image.src = source;
});

const validPdfImages = value => {
  if (!isObjectPayload(value) || !Array.isArray(value.images) || !value.images.length || value.images.length > limits.max_print_jobs) return false;
  let bytes = 0;
  return value.images.every(source => {
    if (typeof source !== 'string' || !source.startsWith('data:image/png;base64,')
      || source.length > 4 * Math.ceil(limits.max_image_bytes / 3) + 22) return false;
    bytes += source.length;
    return bytes <= limits.max_request_bytes;
  });
};

export default function useMediaImport() {
  const task = useRef(null);
  const [status, setStatus] = useState({ busy: false, message: '', error: '' });
  useEffect(() => {
    const unsubscribe = useStore.subscribe(state => {
      const active = task.current;
      if (active && !sameDocument(state, active.captured)) active.controller.abort(new Error(changedMessage));
    });
    return () => {
      unsubscribe();
      const active = task.current; task.current = null;
      active?.controller.abort(new Error('Import cancelled because the editor closed.'));
    };
  }, []);

  const importFile = async (event, kind) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || task.current) return;
    const captured = useStore.getState();
    const active = { captured, controller: new AbortController() };
    task.current = active;
    setStatus({ busy: true, message: kind === 'pdf' ? 'Converting PDF…' : 'Reading image…', error: '' });
    try {
      const sizeLimit = kind === 'pdf' ? limits.max_upload_bytes : limits.max_image_bytes;
      if (file.size > sizeLimit) throw new Error(`The file exceeds the ${sizeLimit / 1024 / 1024} MiB import limit.`);
      let sources;
      if (kind === 'pdf') {
        const body = new FormData(); body.append('file', file);
        const response = await apiJson('/api/pdf/convert', { method: 'POST', body, signal: active.controller.signal }, {
          timeoutMs: 120_000, validate: validPdfImages, validationMessage: 'The PDF conversion response was invalid. Nothing was added.'
        });
        sources = response.images;
      } else sources = [await readFile(file, active.controller.signal)];
      if (task.current !== active || active.controller.signal.aborted) throw active.controller.signal.reason || new Error('Import cancelled.');
      if (captured.items.length + sources.length > limits.max_canvas_entries) throw new Error('Import would exceed the supported canvas item count.');
      setStatus({ busy: true, message: `Preparing ${sources.length} image${sources.length === 1 ? '' : 's'}…`, error: '' });
      let y = 0, pixels = 0;
      const imported = [];
      for (const source of sources) {
        const dimensions = await imageDimensions(source, active.controller.signal);
        pixels += dimensions.width * dimensions.height;
        if (pixels > limits.max_render_pixels) throw new Error('Imported pages exceed the supported total image pixel budget. Nothing was added.');
        const width = Math.min(dimensions.width, captured.canvasWidth);
        const height = width * dimensions.height / dimensions.width;
        imported.push({ id: crypto.randomUUID(), type: 'image', src: source, x: 0, y, width, height, pageIndex: captured.currentPage });
        y += height + 10;
      }
      if (active.controller.signal.aborted) throw active.controller.signal.reason;
      if (!sameDocument(useStore.getState(), captured)) throw new Error(changedMessage);
      task.current = null;
      const last = imported[imported.length - 1];
      // Commit all pages once, after every decode succeeds and ownership is checked.
      useStore.setState(state => ({ items: [...state.items, ...imported], selectedId: last.id, selectedIds: [last.id] }));
      setStatus({ busy: false, message: `${imported.length} image${imported.length === 1 ? '' : 's'} imported.`, error: '' });
    } catch (error) {
      if (task.current === active) setStatus({ busy: false, message: '', error: error?.message || 'Import failed. Nothing was added.' });
    } finally {
      if (task.current === active) task.current = null;
    }
  };
  return { ...status, importImage: event => importFile(event, 'image'), importPdf: event => importFile(event, 'pdf'),
    cancel: () => task.current?.controller.abort(new Error('Import cancelled before adding anything to the canvas.')) };
}

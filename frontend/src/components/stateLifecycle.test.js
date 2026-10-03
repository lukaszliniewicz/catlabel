import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useStore } from '../store';
import LocalBatchRenderer from './LocalBatchRenderer';
import HeadlessRenderer from '../HeadlessRenderer';
import BatchPrintModal from './BatchPrintModal';
import TemplateWizardModal from './TemplateWizardModal';
import PresetPickerModal from './PresetPickerModal';

const pages = vi.hoisted(() => []);
vi.mock('./HeadlessPage', () => ({ default: (props) => {
  pages.push(props);
  return React.createElement('div', { 'data-render-page': props.pageIndex });
} }));
let root;
let container;
const originalState = useStore.getState();
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  pages.length = 0;
  useStore.setState({ ...originalState, items: [], pageLayouts: [], batchRecords: [{}], labelPresets: [], fetchFonts: vi.fn().mockResolvedValue(true) }, true);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  document.getElementById('render-done')?.remove();
  delete window.__INJECTED_PAYLOAD__;
  delete window.__RENDERED_IMAGES__;
  delete window.__RENDER_ERROR__;
  useStore.setState(originalState, true);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const render = (Component, props = {}) => act(() => root.render(React.createElement(Component, props)));
const job = (id) => ({ id, canvasState: { width: 100, height: 100 }, batchRecords: [{ name: id }], copies: 1, pageIndices: [0, 1] });
const changeSelect = async (element, value) => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(element, value);
  await act(() => element.dispatchEvent(new Event('change', { bubbles: true })));
};

test('replacement render jobs reset progress and reject old callbacks and timers', async () => {
  vi.useFakeTimers();
  const onComplete = vi.fn();
  useStore.setState({ pendingPrintJob: job(1) });
  await render(LocalBatchRenderer, { onComplete });
  const oldPage = pages.at(-1);
  await act(() => oldPage.onReady('old-first'));
  expect(container.textContent).toContain('Rendering 1 of 2');
  await act(() => useStore.setState({ pendingPrintJob: job(2) }));
  expect(container.textContent).toContain('Rendering 0 of 2');
  await act(() => oldPage.onReady('stale'));
  await act(() => vi.advanceTimersByTime(50));
  expect(onComplete).not.toHaveBeenCalled();
  expect(pages.at(-1).pageIndex).toBe(0);
  expect(pages.at(-1).record.name).toBe(2);
  await act(() => pages.at(-1).onReady('new-first'));
  await act(() => vi.advanceTimersByTime(50));
  expect(pages.at(-1).pageIndex).toBe(1);
  await act(() => pages.at(-1).onReady('new-second'));
  expect(onComplete).toHaveBeenCalledExactlyOnceWith(['new-first', 'new-second'], null, 2);
});

test('headless payloads publish their own completion once', async () => {
  window.__RENDERED_IMAGES__ = ['stale'];
  window.__RENDER_ERROR__ = 'stale';
  window.__INJECTED_PAYLOAD__ = { canvas_state: { width: 100, height: 100, items: [] }, copies: 1 };
  await render(HeadlessRenderer);
  expect(window.__RENDERED_IMAGES__).toEqual([]);
  expect(window.__RENDER_ERROR__).toBeNull();
  await act(() => pages.at(-1).onReady('fresh'));
  expect(window.__RENDERED_IMAGES__).toEqual(['fresh']);
  expect(document.getElementById('render-done')).not.toBeNull();
  await act(() => pages.at(-1).onReady('duplicate'));
  expect(window.__RENDERED_IMAGES__).toEqual(['fresh']);
});

test('CSV overrides survive canvas edits and new variables get matching defaults', async () => {
  vi.stubGlobal('FileReader', class {
    readAsText() { this.onload({ target: { result: 'name,alias,new\nOriginal,Custom,Added' } }); }
  });
  useStore.setState({ items: [{ id: 'text', type: 'text', text: '{{ name }}' }] });
  await render(BatchPrintModal, { onClose: vi.fn() });
  const upload = container.querySelector('input[type=file]');
  Object.defineProperty(upload, 'files', { value: [new File(['unused'], 'labels.csv')] });
  await act(() => upload.dispatchEvent(new Event('change', { bubbles: true })));
  await changeSelect(container.querySelector('select'), 'alias');
  await act(() => useStore.setState({ items: [{ id: 'text', type: 'text', text: '{{ name }} {{ new }}' }] }));
  const selectors = container.querySelectorAll('select');
  expect(selectors[0].value).toBe('alias');
  expect(selectors[1].value).toBe('new');
  const apply = [...container.querySelectorAll('button')].find((button) => button.textContent.includes('Apply'));
  await act(() => apply.click());
  expect(useStore.getState().batchRecords).toEqual([{ name: 'Custom', new: 'Added' }]);
});

test('template defaults initialize immediately and reset for batch mode and a new template', async () => {
  const template = { id: 'one', name: 'One', fields: [{ name: 'title', label: 'Title', type: 'text', default: 'First' }] };
  const onClose = vi.fn();
  await render(TemplateWizardModal, { template, onClose });
  expect(document.querySelector('input[type=text]').value).toBe('First');
  await act(() => document.querySelector('input[type=checkbox]').click());
  expect(document.querySelector('input[type=text]').value).toBe('{{ title }}');
  await act(() => document.querySelector('input[type=checkbox]').click());
  expect(document.querySelector('input[type=text]').value).toBe('First');
  await render(TemplateWizardModal, { template: { ...template, id: 'two', name: 'Two', fields: [{ ...template.fields[0], default: 'Second' }] }, onClose });
  expect(document.querySelector('input[type=text]').value).toBe('Second');
  expect(document.querySelector('input[type=checkbox]').checked).toBe(false);
});

test('preset state changes preserve the focused card DOM identity', async () => {
  useStore.setState({ labelPresets: [{ id: 1, name: 'Roll', width_mm: 48, height_mm: 30, media_type: 'continuous' }], canvasWidth: 100, canvasHeight: 100, selectedPrinterInfo: null });
  await render(PresetPickerModal, { onClose: vi.fn() });
  const card = [...document.querySelectorAll('button')].find((button) => button.title === 'Roll');
  card.focus();
  await act(() => useStore.setState({ canvasWidth: 150 }));
  expect([...document.querySelectorAll('button')].find((button) => button.title === 'Roll')).toBe(card);
  expect(document.activeElement).toBe(card);
});

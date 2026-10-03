import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import PropertiesPanel from './PropertiesPanel';
import { useStore } from '../store';
import { TEMPLATE_METADATA } from '../domain/templates';
vi.mock('./AIAssistant', () => ({ default: () => <span>Assistant fixture</span> }));
let root, container;
const original = useStore.getState();
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); useStore.setState({ isNarrowLayout: false, isPropertiesOpen: true }); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); });
test('tabs use one tab stop and arrow/Home/End navigation with associated panels', async () => {
  await act(() => root.render(<PropertiesPanel />));
  const tabs = [...container.querySelectorAll('[role=tab]')];
  expect(tabs.filter(tab => tab.tabIndex === 0)).toEqual([tabs[1]]);
  const key = async value => {
    const active = container.querySelector('[role=tab][aria-selected=true]');
    active.focus();
    await act(() => active.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })));
  };
  await key('ArrowRight');
  expect(document.activeElement).toBe(tabs[2]);
  expect(tabs[2].getAttribute('aria-selected')).toBe('true');
  expect(container.querySelector('[role=tabpanel]').id).toBe(tabs[2].getAttribute('aria-controls'));
  await key('Home'); expect(document.activeElement).toBe(tabs[0]);
  await key('End'); expect(document.activeElement).toBe(tabs[3]);
  expect(container.textContent).toContain('Assistant fixture');
  await key('ArrowRight'); expect(document.activeElement).toBe(tabs[0]);
});

test.each(['canvas', 'text', 'group', 'html', 'shape', 'qrcode', 'barcode'])('%s fields expose names and visible-label associations', async kind => {
  if (kind !== 'canvas') useStore.setState({ selectedId: 'fixture', items: [{ id: 'fixture', type: kind, x: 0, y: 0, width: 100, height: 100, text: 'Fixture', data: '123', size: 12, icon_x: 0, icon_y: 0, text_x: 0, text_y: 0 }] });
  await act(() => root.render(<PropertiesPanel />));
  if (kind !== 'canvas') await act(() => container.querySelector('[aria-label="Element and layout"]').click());
  for (const field of container.querySelectorAll('input, select, textarea')) {
    expect(Boolean(field.getAttribute('aria-label') || field.labels?.length), field.outerHTML).toBe(true);
  }
  for (const label of container.querySelectorAll('label[for]')) expect(label.control, label.outerHTML).not.toBeNull();
});

test('panel resizing supports pointer cancellation and matching keyboard limits', async () => {
  await act(() => root.render(<PropertiesPanel />));
  const separator = container.querySelector('[role=separator]');
  const pointer = async (type, x) => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.assign(event, { pointerId: 4, clientX: x, pointerType: 'touch' });
    await act(() => separator.dispatchEvent(event));
  };
  await pointer('pointerdown', 100);
  await pointer('pointermove', 300);
  expect(separator.getAttribute('aria-valuenow')).toBe('280');
  await pointer('pointercancel', 300);
  await pointer('pointermove', 0);
  expect(separator.getAttribute('aria-valuenow')).toBe('280');
  const right = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
  await act(() => separator.dispatchEvent(right));
  expect(right.defaultPrevented).toBe(true);
  expect(separator.getAttribute('aria-valuenow')).toBe('280');
});

test.each(['raw', 'levels'])('printer %s density and energy controls retain their own labels', async scale => {
  useStore.setState({ selectedPrinter: 'offline:fixture', selectedPrinterInfo: { capabilities: { density: { available: true, scale, min: 1, max: 5 }, energy: { available: true, min: 1000, max: 5000 }, feed: { available: true }, speed: { available: true } } } });
  await act(() => root.render(<PropertiesPanel />));
  for (const field of container.querySelectorAll('input, select')) expect(Boolean(field.getAttribute('aria-label') || field.labels?.length), field.outerHTML).toBe(true);
  for (const label of container.querySelectorAll('label[for]')) expect(label.control, label.outerHTML).not.toBeNull();
});

test('template parameters and generated HTML retain label associations', async () => {
  useStore.setState({ selectedId: null, currentPage: 0, pageLayouts: [{ pageIndex: 0, htmlContent: '', activeTemplate: { id: TEMPLATE_METADATA[0].id, params: {} } }] });
  await act(() => root.render(<PropertiesPanel />));
  await act(() => container.querySelector('[aria-label="Element and layout"]').click());
  for (const field of container.querySelectorAll('input, select, textarea')) expect(Boolean(field.getAttribute('aria-label') || field.labels?.length), field.outerHTML).toBe(true);
  for (const label of container.querySelectorAll('label[for]')) expect(label.control, label.outerHTML).not.toBeNull();
});

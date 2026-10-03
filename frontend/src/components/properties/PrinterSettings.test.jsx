import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { useStore } from '../../store';
import * as apiClient from '../../utils/apiClient';
import PrinterSettings from './PrinterSettings';
let root, container;
const original = useStore.getState();
const profile = { id: 1, name: null, mac_address: 'printer-a', transport: 'BLE', default_darkness: 3, speed: 0, energy: 3, feed_lines: 50, paper_mode: null };
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  useStore.setState({ ...original, selectedPrinter: 'printer-a', selectedPrinterInfo: { capabilities: { density: { available: true, min: 1, max: 5 } } }, printerProfile: profile }, true);
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); vi.restoreAllMocks(); });
const mount = () => act(() => root.render(<PrinterSettings />));
const save = () => act(() => [...container.querySelectorAll('button')].find(button => button.textContent.includes('Save Printer Settings')).click());
test('pending and failed saves never announce success and retain the edited profile', async () => {
  let reject;
  vi.spyOn(apiClient, 'apiJson').mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  await mount(); await save();
  expect(container.textContent).toContain('Saving printer settings'); expect(container.textContent).not.toContain('settings saved');
  await act(() => reject(new Error('Printer profile rejected')));
  expect(container.querySelector('[role=alert]').textContent).toBe('Printer profile rejected');
  expect(container.textContent).not.toContain('settings saved'); expect(useStore.getState().printerProfile.energy).toBe(3);
});
test('acknowledgement belongs to submitted values and keeps edits made during the request', async () => {
  let resolve;
  const api = vi.spyOn(apiClient, 'apiJson').mockImplementation(() => new Promise(done => { resolve = done; }));
  await mount(); await save();
  expect(JSON.parse(api.mock.calls[0][1].body).paper_mode).toBe('');
  await act(() => useStore.setState({ printerProfile: { ...profile, energy: 4 } }));
  await act(() => resolve(profile));
  expect(container.textContent).toContain('changed since the last save'); expect(useStore.getState().printerProfile.energy).toBe(4);
});
test('older printer save cannot replace a later printer acknowledgement', async () => {
  const pending = [];
  vi.spyOn(apiClient, 'apiJson').mockImplementation(() => new Promise(resolve => pending.push(resolve)));
  await mount(); await save();
  await act(() => useStore.setState({ selectedPrinter: 'printer-b', printerProfile: { ...profile, energy: 4 } }));
  await save(); await act(() => pending[1]({ ...profile, energy: 4 }));
  expect(container.textContent).toContain('Printer settings saved');
  await act(() => pending[0](profile));
  expect(container.textContent).toContain('Printer settings saved'); expect(container.textContent).not.toContain('changed since');
});
test('dithering reflects external store changes without an unrelated panel render', async () => {
  await mount(); await act(() => useStore.getState().setDither(false));
  expect(container.querySelector('input[type=checkbox]').checked).toBe(false);
});

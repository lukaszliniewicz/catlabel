import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { useStore } from '../store';
import * as apiClient from '../utils/apiClient';
import OnboardingWizard from './OnboardingWizard';
import Sidebar from './Sidebar';

const original = useStore.getState();
let container;
let root;
const pd01 = { name: 'PD01', model_id: 'pd01_v5g', vendor: 'generic', protocol_family: 'v5g',
  width_mm: 48.8, width_px: 384, dpi: 200, media_type: 'continuous' };
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  useStore.setState({ ...original, items: [], pageLayouts: [], manualPrinters: [],
    selectedPrinter: null, selectedPrinterInfo: null, onboardingComplete: false, showOnboarding: false }, true);
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  useStore.setState(original, true);
  vi.restoreAllMocks();
});
const mount = Component => act(() => root.render(<Component />));
const click = text => act(() => [...container.querySelectorAll('button')].find(button => button.textContent.includes(text)).click());
const models = () => vi.spyOn(apiClient, 'apiFetch').mockImplementation(async url => ({
  json: async () => url.endsWith('supported_models') ? { models: [pd01,
    { ...pd01, name: 'Other', model_id: 'other', protocol_family: 'classic' }] } : {}
}));

test('Start designing completes welcome without scanning, AI configuration or settings writes', async () => {
  const api = models();
  const mediaType = useStore.getState().settings.intended_media_type;
  await mount(OnboardingWizard);
  await click('Start designing');
  expect(useStore.getState()).toMatchObject({ onboardingComplete: true, showOnboarding: false,
    selectedPrinter: null, showAiConfig: false });
  expect(useStore.getState().settings.intended_media_type).toBe(mediaType);
  expect(localStorage.getItem('catlabel_onboarding_completed_v1')).toBe('1');
  expect(api.mock.calls.map(([url]) => url)).toEqual(['/api/printers/supported_models']);
});

test('model search shows geometry and protocol, and a selected offline profile is remembered', async () => {
  models();
  await mount(OnboardingWizard);
  await click('Manual Setup');
  await click('Generic Chinese');
  const input = container.querySelector('input[type=search]');
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'PD01');
  await act(() => input.dispatchEvent(new Event('input', { bubbles: true })));
  expect(container.textContent).toContain('48.8 mm');
  expect(container.textContent).toContain('v5g');
  expect(container.textContent).not.toContain('Other');
  await click('PD01');
  expect(useStore.getState()).toMatchObject({ selectedPrinter: 'manual-pd01_v5g',
    selectedPrinterInfo: { transport: 'offline', dpi: 200, protocol_family: 'v5g' } });
  await act(() => useStore.setState({ selectedPrinter: null, selectedPrinterInfo: null }));
  await act(() => useStore.getState().restorePrinterChoice());
  expect(useStore.getState().selectedPrinter).toBe('manual-pd01_v5g');
  await useStore.getState().printPages([0]);
  expect(useStore.getState()).toMatchObject({ isPreparingForPrint: false, pendingPrintJob: null });
  expect(useStore.getState().apiError).toContain('offline profile');
});

test('Sidebar waits for an explicit scan and discovery preserves the selected offline profile', async () => {
  const offline = { ...pd01, transport: 'offline', address: 'manual-pd01_v5g' };
  useStore.setState({ selectedPrinter: offline.address, selectedPrinterInfo: offline, manualPrinters: [offline] });
  const api = vi.spyOn(apiClient, 'apiJson').mockResolvedValue({ devices: [{ ...pd01, address: 'fixture-device', transport: 'ble' }] });
  await mount(Sidebar);
  expect(api).not.toHaveBeenCalled();
  await click('Scan for Printers');
  expect(api).toHaveBeenCalledTimes(1);
  expect(useStore.getState().selectedPrinter).toBe(offline.address);
  expect(container.textContent).toContain('Offline profile: design and export now');
});

test('malformed model data shows a setup error while designing remains available', async () => {
  vi.spyOn(apiClient, 'apiFetch').mockResolvedValue({ json: async () => ({ models: {} }) });
  await mount(OnboardingWizard);
  expect(container.querySelector('[role=alert]').textContent).toContain('Printer model data is malformed');
  await click('Start designing');
  expect(useStore.getState().onboardingComplete).toBe(true);
});

test('closing setup aborts its outstanding discovery request', async () => {
  let scanSignal;
  vi.spyOn(apiClient, 'apiFetch').mockImplementation(async (url, init) => {
    if (url.endsWith('/scan')) {
      scanSignal = init.signal;
      return new Promise(() => {});
    }
    return { json: async () => ({ models: [pd01] }) };
  });
  await mount(OnboardingWizard);
  await click('Scan Bluetooth');
  expect(scanSignal.aborted).toBe(false);
  await act(() => root.render(null));
  expect(scanSignal.aborted).toBe(true);
});

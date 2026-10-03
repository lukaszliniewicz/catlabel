import { expect, test } from 'vitest';

import {
  isPrinterProfile,
  isPrinterScanResponse,
  isPrinterSupportedModelsResponse,
} from './printer';

const unavailable = { available: false };

const niimbotModel = {
  name: 'D11/D110 (15mm)',
  vendor: 'niimbot',
  vendor_display: 'Niimbot',
  model_id: 'D110',
  width_px: 120,
  width_mm: 15,
  dpi: 203,
  media_type: 'pre-cut',
  protocol_family: 'niimbot',
  protocol_variant: 'd110',
  default_energy: 3,
  max_density: 5,
  capabilities: {
    speed: unavailable,
    energy: unavailable,
    density: { available: true, min: 1, max: 5, default: 3 },
    feed: unavailable,
  },
};

const genericModel = {
  name: 'Generic label printer',
  vendor: 'generic',
  vendor_display: 'Generic / Cat Printers',
  model: 'GENERIC-1',
  model_no: 'GENERIC-1',
  model_id: 'GENERIC-1',
  width_px: 384,
  width_mm: 48,
  dpi: 203,
  media_type: 'continuous',
  protocol_family: 'legacy',
  protocol_variant: null,
  default_speed: 0,
  default_energy: 5000,
  min_energy: 1,
  max_energy: 65535,
  max_speed: 100,
  max_density: null,
  min_density: null,
  default_density: null,
  supported_paper_modes: [{ value: 'plain', label: 'Plain' }],
  capabilities: {
    speed: { available: true, min: 0, max: 100, default: 0 },
    energy: { available: true, min: 1, max: 65535, step: 500, default: 5000 },
    density: unavailable,
    feed: { available: true, default: 50 },
  },
};

test('supported-model response accepts vendor-specific capability variation and extra metadata', () => {
  expect(isPrinterSupportedModelsResponse({
    models: [niimbotModel, genericModel],
    snapshot_version: 4,
  })).toBe(true);
});

test('hardware and model guards reject malformed consumed fields', () => {
  expect(isPrinterSupportedModelsResponse({ models: [{ ...genericModel, width_px: '384' }] })).toBe(false);
  expect(isPrinterSupportedModelsResponse({
    models: [{
      ...niimbotModel,
      capabilities: {
        ...niimbotModel.capabilities,
        density: { available: true, min: 1, max: 5, default: '3' },
      },
    }],
  })).toBe(false);
});

test('scan response accepts nullable pairing and classic or BLE transports', () => {
  const discovered = {
    ...niimbotModel,
    detection_status: 'recognized',
    address: 'AA:BB:CC:DD:EE:FF',
    display_address: 'AA:BB:CC:DD:EE:FF',
    paired: null,
    transport: 'ble',
  };

  expect(isPrinterScanResponse({ devices: [discovered], failures: [] })).toBe(true);
  expect(isPrinterScanResponse({
    devices: [{ ...discovered, transport: 'offline' }],
    failures: [],
  })).toBe(false);
  expect(isPrinterScanResponse({ devices: [discovered], failures: [{ message: 'adapter' }] })).toBe(false);
});

test('printer profile preserves backend nullable settings', () => {
  expect(isPrinterProfile({
    id: 7,
    mac_address: 'AA:BB:CC:DD:EE:FF',
    name: null,
    transport: 'BLE',
    default_darkness: 3,
    speed: null,
    energy: null,
    feed_lines: null,
    paper_mode: null,
    server_metadata: { revision: 1 },
  })).toBe(true);

  expect(isPrinterProfile({
    id: 7,
    mac_address: 'AA:BB:CC:DD:EE:FF',
    name: null,
    transport: 'BLE',
    default_darkness: 3,
    speed: null,
    energy: null,
    feed_lines: '0',
    paper_mode: null,
  })).toBe(false);
});

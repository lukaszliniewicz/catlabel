type DeviceTransport = 'ble' | 'classic';
type DetectionStatus = 'recognized' | 'ambiguous' | 'unknown';

interface PrinterCapability {
  available: boolean;
  min?: number | null;
  max?: number | null;
  default?: number | null;
  step?: number | null;
  recommended_min?: number | null;
  recommended_max?: number | null;
  allow_auto?: boolean;
  scale?: string;
  [metadata: string]: unknown;
}

interface PrinterCapabilities {
  speed: PrinterCapability;
  energy: PrinterCapability;
  density: PrinterCapability;
  feed: PrinterCapability;
  [metadata: string]: unknown;
}

interface PaperModeOption {
  value: string;
  label: string;
  [metadata: string]: unknown;
}

interface HardwareInfo {
  name: string;
  vendor: string;
  vendor_display: string;
  model_id: string;
  width_px: number;
  width_mm: number;
  dpi: number;
  media_type: string;
  protocol_family: string;
  capabilities: PrinterCapabilities;
  model?: string;
  model_no?: string;
  default_speed?: number;
  default_energy?: number;
  min_energy?: number;
  max_energy?: number;
  max_speed?: number;
  max_density?: number | null;
  min_density?: number | null;
  default_density?: number | null;
  protocol_variant?: string | null;
  support_state?: string;
  support_note?: string | null;
  supported_paper_modes?: PaperModeOption[];
  detection_status?: DetectionStatus;
  detection_candidates?: string[];
  [metadata: string]: unknown;
}

export type SupportedPrinterModel = HardwareInfo;

export interface DiscoveredPrinter extends HardwareInfo {
  address: string;
  display_address: string;
  paired: boolean | null;
  transport: DeviceTransport | null;
}

export interface PrinterSupportedModelsResponse {
  models: SupportedPrinterModel[];
  [metadata: string]: unknown;
}

export interface PrinterScanResponse {
  devices: DiscoveredPrinter[];
  failures: string[];
  [metadata: string]: unknown;
}

export interface PrinterProfile {
  id: number | null;
  mac_address: string;
  name: string | null;
  transport: string;
  default_darkness: number;
  speed: number | null;
  energy: number | null;
  feed_lines: number | null;
  paper_mode: string | null;
  [metadata: string]: unknown;
}

type UnknownRecord = Record<string, unknown>;
type ValueGuard<T> = (value: unknown) => value is T;

const isRecord = (value: unknown): value is UnknownRecord => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
);

const isFiniteNumber = (value: unknown): value is number => (
  typeof value === 'number' && Number.isFinite(value)
);

const isNullableFiniteNumber = (value: unknown): value is number | null => (
  value === null || isFiniteNumber(value)
);

const isString = (value: unknown): value is string => typeof value === 'string';

const isNullableString = (value: unknown): value is string | null => (
  value === null || isString(value)
);

const hasOptionalField = <T>(
  value: UnknownRecord,
  field: string,
  guard: ValueGuard<T>,
): boolean => (
  !Object.prototype.hasOwnProperty.call(value, field) || guard(value[field])
);

const isStringArray = (value: unknown): value is string[] => (
  Array.isArray(value) && value.every((item: unknown) => isString(item))
);

const isPaperModeOption = (value: unknown): value is PaperModeOption => (
  isRecord(value)
  && isString(value.value)
  && isString(value.label)
);

const isPaperModeOptionArray = (value: unknown): value is PaperModeOption[] => (
  Array.isArray(value) && value.every((item: unknown) => isPaperModeOption(item))
);

const isPrinterCapability = (value: unknown): value is PrinterCapability => (
  isRecord(value)
  && typeof value.available === 'boolean'
  && hasOptionalField(value, 'min', isNullableFiniteNumber)
  && hasOptionalField(value, 'max', isNullableFiniteNumber)
  && hasOptionalField(value, 'default', isNullableFiniteNumber)
  && hasOptionalField(value, 'step', isNullableFiniteNumber)
  && hasOptionalField(value, 'recommended_min', isNullableFiniteNumber)
  && hasOptionalField(value, 'recommended_max', isNullableFiniteNumber)
  && hasOptionalField(value, 'allow_auto', (item): item is boolean => typeof item === 'boolean')
  && hasOptionalField(value, 'scale', isString)
);

const isPrinterCapabilities = (value: unknown): value is PrinterCapabilities => (
  isRecord(value)
  && isPrinterCapability(value.speed)
  && isPrinterCapability(value.energy)
  && isPrinterCapability(value.density)
  && isPrinterCapability(value.feed)
);

const isHardwareInfo = (value: unknown): value is HardwareInfo => (
  isRecord(value)
  && isString(value.name)
  && isString(value.vendor)
  && isString(value.vendor_display)
  && isString(value.model_id)
  && isFiniteNumber(value.width_px)
  && isFiniteNumber(value.width_mm)
  && isFiniteNumber(value.dpi)
  && isString(value.media_type)
  && isString(value.protocol_family)
  && isPrinterCapabilities(value.capabilities)
  && hasOptionalField(value, 'model', isString)
  && hasOptionalField(value, 'model_no', isString)
  && hasOptionalField(value, 'default_speed', isFiniteNumber)
  && hasOptionalField(value, 'default_energy', isFiniteNumber)
  && hasOptionalField(value, 'min_energy', isFiniteNumber)
  && hasOptionalField(value, 'max_energy', isFiniteNumber)
  && hasOptionalField(value, 'max_speed', isFiniteNumber)
  && hasOptionalField(value, 'max_density', isNullableFiniteNumber)
  && hasOptionalField(value, 'min_density', isNullableFiniteNumber)
  && hasOptionalField(value, 'default_density', isNullableFiniteNumber)
  && hasOptionalField(value, 'protocol_variant', isNullableString)
  && hasOptionalField(value, 'support_state', isString)
  && hasOptionalField(value, 'support_note', isNullableString)
  && hasOptionalField(value, 'supported_paper_modes', isPaperModeOptionArray)
  && hasOptionalField(
    value,
    'detection_status',
    (item): item is DetectionStatus => item === 'recognized' || item === 'ambiguous' || item === 'unknown',
  )
  && hasOptionalField(value, 'detection_candidates', isStringArray)
);

const isSupportedPrinterModel = (value: unknown): value is SupportedPrinterModel => (
  isHardwareInfo(value)
);

const isDiscoveredPrinter = (value: unknown): value is DiscoveredPrinter => (
  isHardwareInfo(value)
  && isRecord(value)
  && isString(value.address)
  && isString(value.display_address)
  && (typeof value.paired === 'boolean' || value.paired === null)
  && (value.transport === 'ble' || value.transport === 'classic' || value.transport === null)
);

export const isPrinterSupportedModelsResponse = (
  value: unknown,
): value is PrinterSupportedModelsResponse => (
  isRecord(value)
  && Array.isArray(value.models)
  && value.models.every((model: unknown) => isSupportedPrinterModel(model))
);

export const isPrinterScanResponse = (value: unknown): value is PrinterScanResponse => (
  isRecord(value)
  && Array.isArray(value.devices)
  && value.devices.every((device: unknown) => isDiscoveredPrinter(device))
  && isStringArray(value.failures)
);

export const isPrinterProfile = (value: unknown): value is PrinterProfile => (
  isRecord(value)
  && (isFiniteNumber(value.id) || value.id === null)
  && isString(value.mac_address)
  && isNullableString(value.name)
  && isString(value.transport)
  && isFiniteNumber(value.default_darkness)
  && isNullableFiniteNumber(value.speed)
  && isNullableFiniteNumber(value.energy)
  && isNullableFiniteNumber(value.feed_lines)
  && isNullableString(value.paper_mode)
);

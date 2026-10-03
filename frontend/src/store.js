import { create } from 'zustand';
import { withHistory } from './state/history';
import { createDocumentSlice } from './state/slices/document';
import { createSelectionSlice } from './state/slices/selection';
import { createPrinterSlice } from './state/slices/printer';
import { createSettingsSlice } from './state/slices/settings';
import { createPersistenceSlice } from './state/slices/persistence';
import { createBatchSlice } from './state/slices/batch';
import { createUiSlice } from './state/slices/ui';

// One store and one history wrapper preserve atomic cross-slice updates.
export const useStore = create(withHistory((set, get) => ({
  ...createDocumentSlice(set, get),
  ...createSelectionSlice(set, get),
  ...createPrinterSlice(set, get),
  ...createSettingsSlice(set, get),
  ...createPersistenceSlice(set, get),
  ...createBatchSlice(set, get),
  ...createUiSlice(set, get),
})));

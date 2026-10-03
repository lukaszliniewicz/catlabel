import { apiFetch, apiJson, isArrayPayload, isObjectPayload } from '../../utils/apiClient';
import { errorMessage } from '../errors';
import { scaleItemForDpi } from '../../domain/document';
import { buildTemplateHtml, recalcAutoFit } from '../../domain/normalization';

export const createSettingsSlice = (set, get) => ({
  theme: 'auto',
  dither: true,
  setDither: (val) => set({ dither: val }),
  fonts: [],
  labelPresets: [],
  addresses: [],
  settings: { paper_width_mm: 58.0, print_width_mm: 48.0, default_dpi: 203, speed: 0, energy: 0, feed_lines: 50, default_font: 'RobotoCondensed.ttf', intended_media_type: 'unknown' },
  settingsLoaded: false,
  fetchPresets: async () => {
    try {
      let data = await apiJson('/api/presets', {}, {
        validate: isArrayPayload,
        validationMessage: 'Preset data is malformed.'
      });

      const standard48 = data.find((p) => p.name.includes('Standard Square (48x48mm)'));
      const a6Shipping = data.find((p) => p.name.includes('A6 Shipping'));

      data = data.filter((p) => p !== standard48 && p !== a6Shipping);

      if (standard48) data.unshift(standard48);
      if (a6Shipping) data.push(a6Shipping);

      set({ labelPresets: data });
    } catch (e) {
      console.error("Failed to fetch presets", e);
      set({ apiError: errorMessage(e, 'Failed to load presets.') });
    }
  },
  savePreset: async (presetData) => {
    const { name, description, media_type } = presetData;
    const state = get();
    const widthMm = parseFloat(state.getPxToMm(state.canvasWidth));
    const heightMm = parseFloat(state.getPxToMm(state.canvasHeight));

    try {
      await apiFetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: description || null,
          media_type: media_type || 'any',
          width_mm: widthMm,
          height_mm: heightMm,
          is_rotated: state.isRotated,
          split_mode: state.splitMode,
          border: state.canvasBorder
        })
      });
      await state.fetchPresets();
    } catch (e) {
      console.error("Failed to save preset", e);
      set({ apiError: errorMessage(e, 'Failed to save the preset.') });
    }
  },
  fetchAddresses: async () => {
    try {
      const data = await apiJson('/api/addresses', {}, {
        validate: isArrayPayload,
        validationMessage: 'Address data is malformed.'
      });
      set({ addresses: data });
    } catch (e) {
      console.error("Failed to fetch addresses", e);
      set({ apiError: errorMessage(e, 'Failed to load addresses.') });
    }
  },
  saveAddress: async (addr) => {
    try {
      await apiFetch('/api/addresses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addr)
      });
      get().fetchAddresses();
    } catch (e) {
      console.error("Failed to save address", e);
      set({ apiError: errorMessage(e, 'Failed to save the address.') });
    }
  },
  deleteAddress: async (id) => {
    try {
      await apiFetch(`/api/addresses/${id}`, { method: 'DELETE' });
      get().fetchAddresses();
    } catch (e) {
      console.error("Failed to delete address", e);
      set({ apiError: errorMessage(e, 'Failed to delete the address.') });
    }
  },
  fetchSettings: async () => {
    try {
      const data = await apiJson('/api/settings', {}, {
        validate: isObjectPayload,
        validationMessage: 'Settings data is malformed.'
      });
      set({ settings: data, settingsLoaded: true });
    } catch (e) {
      console.error("Failed to fetch settings", e);
      set({ settingsLoaded: true, apiError: errorMessage(e, 'Failed to load settings.') });
    }
  },
  fetchFonts: async () => {
    try {
      const data = await apiJson('/api/fonts', {}, {
        validate: isArrayPayload,
        validationMessage: 'Font data is malformed.'
      });
      set({ fonts: data });

      const oldStyle = document.getElementById('catlabel-uploaded-fonts');
      oldStyle?.remove();
      const style = document.createElement('style');
      style.id = 'catlabel-uploaded-fonts';
      let css = '';
      data.forEach(font => {
        if (!font || typeof font.name !== 'string' || typeof font.file_path !== 'string') return;
        const fontName = font.name.split('.')[0].replace(/[^\w -]/g, '').trim();
        const filePath = font.file_path.replace(/\\/g, '/').replace(/^\/+/, '');
        if (!fontName || filePath.includes('..') || /["'()\r\n]/.test(filePath)) return;
        css += `@font-face { font-family: '${fontName}'; src: url('/${encodeURI(filePath)}'); }\n`;
      });
      style.appendChild(document.createTextNode(css));
      document.head.appendChild(style);
      return true;
    } catch (e) {
      console.error("Failed to fetch fonts", e);
      set({ apiError: errorMessage(e, 'Failed to load fonts.') });
      return false;
    }
  },
  uploadFont: async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      await apiFetch('/api/fonts', {
        method: 'POST',
        body: formData
      });
      await get().fetchFonts();
    } catch (e) {
      console.error("Failed to upload font", e);
      set({ apiError: errorMessage(e, 'Failed to upload the font file.') });
    }
  },
  setTheme: (theme) => set({ theme }),
  setSettings: (settings) => set({ settings }),
  updateSettingsAPI: async (newSettings) => {
    const previous = get();
    const rollback = {
      settings: previous.settings,
      currentDpi: previous.currentDpi,
      canvasWidth: previous.canvasWidth,
      canvasHeight: previous.canvasHeight,
      items: previous.items,
      pageLayouts: previous.pageLayouts
    };
    const requestedDpi = Number(newSettings?.default_dpi);
    const currentDpi = previous.currentDpi || previous.settings?.default_dpi || 203;
    const shouldScaleForDpi = !previous.selectedPrinter
      && Number.isFinite(requestedDpi)
      && requestedDpi > 0
      && Math.abs(requestedDpi - currentDpi) > 0.001;

    if (shouldScaleForDpi) {
      const scale = requestedDpi / currentDpi;
      const nextWidth = Math.max(1, Math.round(previous.canvasWidth * scale));
      const nextHeight = Math.max(1, Math.round(previous.canvasHeight * scale));
      set({
        settings: newSettings,
        currentDpi: requestedDpi,
        canvasWidth: nextWidth,
        canvasHeight: nextHeight,
        items: recalcAutoFit(previous.items.map((item) => scaleItemForDpi(item, scale)), previous.batchRecords, nextWidth, nextHeight),
        pageLayouts: previous.pageLayouts.map((layout) => layout.activeTemplate ? {
          ...layout,
          htmlContent: buildTemplateHtml(layout.activeTemplate.id, layout.activeTemplate.params, nextWidth, nextHeight)
        } : layout)
      });
    } else {
      set({ settings: newSettings });
    }
    try {
      await apiFetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings)
      });
    } catch (e) {
      console.error("Failed to save settings", e);
      set({ ...rollback, apiError: errorMessage(e, 'Failed to save settings.') });
    }
  }
});

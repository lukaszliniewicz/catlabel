import { resolveDpi, scaleItemForDpi } from '../../domain/document';
import { buildTemplateHtml, recalcAutoFit } from '../../domain/normalization';
import { apiFetch } from '../../utils/apiClient';
import { errorMessage } from '../errors';

let printerProfileRequestId = 0;

export const createPrinterSlice = (set, get) => ({
  selectedPrinter: null,
  selectedPrinterInfo: null,
  manualPrinters: (() => {
    if (typeof window === 'undefined') return [];
    try {
      const saved = JSON.parse(window.localStorage.getItem('catlabel_manual_printers') || '[]');
      return Array.isArray(saved)
        ? saved.filter((printer) => printer && typeof printer === 'object' && typeof printer.address === 'string').slice(0, 100)
        : [];
    } catch (e) {
      console.error('Failed to load manual printers', e);
      return [];
    }
  })(),
  addManualPrinter: (printer) => set((state) => {
    const newManual = [...state.manualPrinters.filter((p) => p.address !== printer.address), printer];
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('catlabel_manual_printers', JSON.stringify(newManual));
    }
    return { manualPrinters: newManual };
  }),
  removeManualPrinter: (address) => set((state) => {
    const newManual = state.manualPrinters.filter((p) => p.address !== address);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('catlabel_manual_printers', JSON.stringify(newManual));
    }
    return { manualPrinters: newManual };
  }),
  printerProfile: { speed: 0, energy: 0, feed_lines: 50, paper_mode: null },
  setSelectedPrinter: async (mac, info) => {
    const requestId = ++printerProfileRequestId;
    const currentState = get();
    let newW = currentState.canvasWidth;
    let newH = currentState.canvasHeight;
    let nextItems = currentState.items;
    let rot = currentState.isRotated;
    let border = currentState.canvasBorder;

    // Use the exact DPI passed by the hardware info payload
    const activeDpi = info ? resolveDpi(info.dpi) : resolveDpi(currentState.currentDpi);
    const calcMmToPx = (mm) => Math.round(mm * (activeDpi / 25.4));

    if (info) {
      const isNewPrinter = currentState.selectedPrinterInfo?.address !== mac;
      const isPreCutMedia = info.media_type === 'pre-cut';
      const previousDpi = currentState.currentDpi || currentState.settings?.default_dpi || 203;
      const dpiScale = activeDpi / previousDpi;

      if (Math.abs(dpiScale - 1) > 0.001) {
        newW = Math.max(1, Math.round(currentState.canvasWidth * dpiScale));
        newH = Math.max(1, Math.round(currentState.canvasHeight * dpiScale));
        nextItems = currentState.items.map((item) => scaleItemForDpi(item, dpiScale));
      }

      const hasDocument = currentState.currentProjectId != null || currentState.items.length > 0
        || currentState.pageLayouts.some((layout) => layout.htmlContent || layout.activeTemplate);
      if (isNewPrinter && !hasDocument) {
        if (isPreCutMedia) {
          const model = info.model_id ? info.model_id.toLowerCase() : '';

          if (model === 'd11' || model === 'd110' || model === 'd101') {
            newW = calcMmToPx(40);
            newH = calcMmToPx(15);
            rot = true;
          } else if (model === 'b1' || model === 'b21' || model === 'b18') {
            newW = calcMmToPx(50);
            newH = calcMmToPx(30);
            rot = true;
          } else {
            newW = info.width_px || calcMmToPx(48);
            newH = info.width_px || calcMmToPx(48);
            rot = false;
          }
          border = 'none';
        } else {
          const hardwareWidth = info.width_px || 384;
          const currentPrintHeadDimension = currentState.isRotated ? newH : newW;

          if (currentPrintHeadDimension <= hardwareWidth) {
            // Keep the current physical dimensions after the DPI conversion above.
          } else if (hardwareWidth === 384) {
            newW = hardwareWidth;
            newH = hardwareWidth;
            rot = false;
          } else if (hardwareWidth > 384) {
            newW = hardwareWidth;
            newH = Math.round(hardwareWidth * 1.5);
            rot = false;
          } else {
            newW = calcMmToPx(40);
            newH = hardwareWidth;
            rot = true;
            border = 'none';
          }
        }
      }
    }

    set({
      selectedPrinter: mac,
      selectedPrinterInfo: info,
      currentDpi: activeDpi,
      canvasWidth: newW,
      canvasHeight: newH,
      isRotated: rot,
      canvasBorder: border,
      items: recalcAutoFit(nextItems, currentState.batchRecords, newW, newH),
      pageLayouts: currentState.pageLayouts.map(l => l.activeTemplate ? {
        ...l,
        htmlContent: buildTemplateHtml(l.activeTemplate.id, l.activeTemplate.params, newW, newH)
      } : l)
    });

    if (!mac) {
      set({ printerProfile: { speed: 0, energy: 0, feed_lines: 50, paper_mode: null } });
      return;
    }

    try {
      const res = await apiFetch(`/api/printers/${mac}/profile`);
      let profile = (await res.json()) || {};
      if (requestId !== printerProfileRequestId || get().selectedPrinter !== mac) return;
      const caps = info?.capabilities || {};

      // =========================================================================
      // INTELLIGENT OFFLINE-TO-PHYSICAL PROFILE MIGRATION
      // =========================================================================
      if (info && info.transport !== 'offline') {
        const isVirginProfile =
          (profile?.speed ?? 0) <= 0 &&
          (profile?.energy ?? 0) <= 0 &&
          (profile?.feed_lines ?? 50) === 50;

        if (isVirginProfile) {
          const manualPrinters = (get().manualPrinters || []).filter(
            (printer) => printer && printer.address && printer.address !== mac
          );

          const infoModelId = String(info.model_id || '').trim().toLowerCase();
          const infoVendor = String(info.vendor || '').trim().toLowerCase();
          const infoProtocolFamily = String(info.protocol_family || '').trim().toLowerCase();
          const infoMediaType = String(info.media_type || '').trim().toLowerCase();

          let bestMatch = infoModelId
            ? manualPrinters.find(
                (printer) => String(printer.model_id || '').trim().toLowerCase() === infoModelId
              )
            : null;

          if (!bestMatch && infoVendor && infoProtocolFamily && infoMediaType) {
            bestMatch = manualPrinters.find((printer) =>
              String(printer.vendor || '').trim().toLowerCase() === infoVendor &&
              String(printer.protocol_family || '').trim().toLowerCase() === infoProtocolFamily &&
              String(printer.media_type || '').trim().toLowerCase() === infoMediaType
            );
          }

          if (bestMatch) {
            try {
              const manRes = await apiFetch(`/api/printers/${bestMatch.address}/profile`);
              const manProfile = (await manRes.json()) || {};
              if (requestId !== printerProfileRequestId || get().selectedPrinter !== mac) return;
              const migratedSpeed = Number(manProfile?.speed ?? 0);
              const migratedEnergy = Number(manProfile?.energy ?? 0);
              const migratedFeedLines = Number(manProfile?.feed_lines ?? 50);

              const migratedPaperMode = manProfile?.paper_mode || null;
              const hasCustomSettings =
                migratedSpeed > 0 ||
                migratedEnergy > 0 ||
                migratedFeedLines !== 50 ||
                !!migratedPaperMode;

              if (hasCustomSettings) {
                profile = {
                  ...profile,
                  speed: migratedSpeed > 0 ? migratedSpeed : profile?.speed,
                  energy: migratedEnergy > 0 ? migratedEnergy : profile?.energy,
                  feed_lines: migratedFeedLines !== 50 ? migratedFeedLines : profile?.feed_lines,
                  paper_mode: migratedPaperMode || profile?.paper_mode
                };

                await apiFetch(`/api/printers/${mac}/profile`, {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(profile)
                });

                console.log(
                  `[Profile Sync] Safely migrated settings from compatible offline profile (${bestMatch.name}) to physical device ${mac}.`
                );
              }
            } catch (mergeError) {
              console.error("Failed to migrate offline profile settings", mergeError);
            }
          }
        }
      }
      // =========================================================================

      const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

      const profileEnergy = Number(profile?.energy);
      const hasProfileEnergy = profile?.energy !== null && profile?.energy !== undefined && Number.isFinite(profileEnergy);
      const hasDensityOverride = hasProfileEnergy && profileEnergy > 0;
      const normalizedEnergy = caps.density?.available
        ? (caps.density.allow_auto && !hasDensityOverride
            ? 0
            : clamp(
                hasDensityOverride ? profileEnergy : (caps.density.default ?? caps.density.min ?? 1),
                caps.density.min ?? 1,
                caps.density.max ?? 8
              ))
        : (caps.energy?.available
            ? clamp(
                (profile?.energy > 0 ? profile.energy : caps.energy.default) || 5000,
                caps.energy.min || 1,
                caps.energy.max || 65535
              )
            : 0);

      const normalizedSpeed = caps.speed?.available
        ? clamp(
            profile?.speed > 0 ? profile.speed : (caps.speed.default || 0),
            caps.speed.min || 0,
            caps.speed.max || 100
          )
        : 0;

      const normalizedFeed = caps.feed?.available
        ? Math.max(0, profile?.feed_lines ?? (caps.feed.default || 50))
        : 0;
      const supportedPaperModes = Array.isArray(info?.supported_paper_modes) ? info.supported_paper_modes : [];
      const supportedPaperValues = supportedPaperModes.map((mode) => mode.value).filter(Boolean);
      const normalizedPaperMode = supportedPaperValues.length > 0
        ? (supportedPaperValues.includes(profile?.paper_mode) ? profile.paper_mode : supportedPaperValues[0])
        : null;

      if (requestId !== printerProfileRequestId || get().selectedPrinter !== mac) return;
      set({
        printerProfile: {
          ...profile,
          speed: normalizedSpeed,
          energy: normalizedEnergy,
          feed_lines: normalizedFeed,
          paper_mode: normalizedPaperMode
        }
      });
    } catch (e) {
      console.error("Failed to fetch or merge printer profile", e);
      if (requestId === printerProfileRequestId && get().selectedPrinter === mac) {
        set({
          printerProfile: { speed: 0, energy: 0, feed_lines: 50, paper_mode: null },
          apiError: errorMessage(e, 'Failed to load the printer profile.')
        });
      }
    }
  }
});

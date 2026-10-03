import TEMPLATE_CATALOG from '../../../catlabel/data/templates.json';
import { applyVars } from './variables';
import { sanitizeLabelHtml } from '../utils/htmlSecurity';

const DEFAULT_ICON_SRC = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJibGFjayIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5Z29uIHBvaW50cz0iMTIgMiAxNS4wOSA4LjI2IDIyIDkuMjcgMTcgMTQuMTQgMTguMTggMjEuMDIgMTIgMTcuNzcgNS44MiAyMS4wMiA3IDE0LjE0IDIgOS4yNyA4LjkxIDguMjYgMTIgMiI+PC9wb2x5Z29uPjwvc3ZnPg==';

const buildJarApothecaryMarkup = (p) => {
  const showHeader = p.show_header === true;
  const showSubtitle = p.show_subtitle === true;

  return `
  <div class="label-canvas-container" style="padding: 4%;">
    <div style="border: 3px solid black; height: 100%; width: 100%; outline: 1px solid black; outline-offset: -5px; display: flex; flex-direction: column; padding: 6%; text-align: center; gap: 2%;">
      ${showHeader ? `
      <div class="bound-box" style="flex: 0.5;">
        <div class="auto-text" style="letter-spacing: 2px; font-weight: 700; white-space: nowrap;">${p.header_text || ''}</div>
      </div>` : ''}
      <div class="bound-box" style="flex: 2;">
        <div class="auto-text" style="font-weight: 900; text-transform: uppercase; font-family: serif; white-space: nowrap;">${p.title || ''}</div>
      </div>
      ${showSubtitle ? `
      <div style="display: flex; align-items: center; justify-content: center; gap: 4px; flex: 0.2; min-height: 0;">
        <div style="height: 1px; background: black; width: 25%;"></div>
        <div class="bound-box" style="flex: 0 0 10%;"><div class="auto-text">✧</div></div>
        <div style="height: 1px; background: black; width: 25%;"></div>
      </div>
      <div class="bound-box" style="flex: 0.8;">
        <div class="auto-text" style="font-style: italic; font-weight: bold; font-family: serif;">${p.subtitle_text || ''}</div>
      </div>` : ''}
    </div>
  </div>
  `;
};

const buildJarFarmhouseMarkup = (p) => {
  const showHeader = p.show_header === true;
  const showSubtitle = p.show_subtitle === true;

  return `
  <div class="label-canvas-container" style="display: flex; flex-direction: column; border: 4px solid black; padding: 0;">
    <div style="height: 15%; background: repeating-linear-gradient(45deg, transparent, transparent 3px, black 3px, black 6px); border-bottom: 2px solid black;"></div>
    <div style="flex: 1; display: flex; flex-direction: column; align-items: center; padding: 4%; text-align: center; gap: 2%; min-width: 0; min-height: 0;">
      ${showHeader ? `
      <div class="bound-box" style="flex: 0.5; width: 100%;">
        <div class="auto-text" style="letter-spacing: 2px; font-weight: 700; white-space: nowrap;">${p.header_text || ''}</div>
      </div>` : ''}
      <div class="bound-box" style="flex: 2; width: 100%;">
        <div class="auto-text" style="font-weight: 900; text-transform: uppercase; font-style: italic; font-family: serif; white-space: nowrap;">${p.title || ''}</div>
      </div>
      ${showSubtitle ? `
      <div style="width: 80%; height: 2px; background: black; flex-shrink: 0;"></div>
      <div class="bound-box" style="flex: 1; width: 100%;">
        <div class="auto-text" style="font-weight: bold; letter-spacing: 2px; text-transform: uppercase; white-space: nowrap;">${p.subtitle_text || ''}</div>
      </div>` : ''}
    </div>
    <div style="height: 15%; background: repeating-linear-gradient(45deg, transparent, transparent 3px, black 3px, black 6px); border-top: 2px solid black;"></div>
  </div>
  `;
};

export const TEMPLATE_METADATA = [
  { ...TEMPLATE_CATALOG.find(template => template.id === 'spice_jar'), html: (p) => {
      const isFarmhouse = p.style === 'jar_farmhouse';
      return isFarmhouse ? buildJarFarmhouseMarkup(p) : buildJarApothecaryMarkup(p);
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'title_subtitle'), html: (p) => `
      <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">
        <div class="bound-box" style="flex: 2.0;">
          <div class="auto-text" style="font-weight: 900; text-transform: uppercase; white-space: nowrap;">${p.title || ''}</div>
        </div>
        <div style="height: 3px; background: black; width: 100%; margin: 2% auto; flex-shrink: 0;"></div>
        <div class="bound-box" style="flex: 1.0;">
          <div class="auto-text" style="font-weight: 700;">${p.subtitle || ''}</div>
        </div>
      </div>` },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'icon_text'), html: (p) => {
      const isRow = p.direction !== 'col';
      const iconSrc = p.icon_src || DEFAULT_ICON_SRC;

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: ${isRow ? 'row' : 'column'}; padding: 4%; gap: ${isRow ? '6%' : '4%'}; align-items: center; justify-content: center;">
          <div style="flex: 0 1 auto; ${isRow ? 'height: 100%;' : 'width: 100%;'} aspect-ratio: 1/1; display: flex; align-items: center; justify-content: center;">
            <img src="${iconSrc}" style="width: 100%; height: 100%; object-fit: contain;" />
          </div>
          <div class="bound-box" style="flex: 1; align-items: ${isRow ? 'flex-start' : 'center'}; justify-content: center;">
            <div class="auto-text" style="font-weight: 900; text-align: ${isRow ? 'left' : 'center'};">${p.text || ''}</div>
          </div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'qr_text'), html: (p, isLandscape) => {
      const qrHtml = p.data ? `<div class="catlabel-code" data-type="qrcode" data-value="${p.data}"></div>` : '';

      if (!qrHtml) {
        return `<div class="label-canvas-container" style="padding: 6%;"><div class="bound-box"><div class="auto-text" style="font-weight: 900; text-align: center;">${p.text || ''}</div></div></div>`;
      }

      if (isLandscape) {
        return `
          <div class="label-canvas-container" style="display: flex; flex-direction: row; padding: 4%; gap: 6%;">
            <div style="flex: 0 1 auto; height: 100%; aspect-ratio: 1/1; display: flex; align-items: center; justify-content: center; margin: auto 0;">${qrHtml}</div>
            <div class="bound-box" style="flex: 1;"><div class="auto-text" style="font-weight: 900; text-align: left;">${p.text || ''}</div></div>
          </div>`;
      }

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">
          <div style="flex: 0 1 auto; width: 100%; aspect-ratio: 1/1; display: flex; align-items: center; justify-content: center;">${qrHtml}</div>
          <div class="bound-box" style="flex: 1;"><div class="auto-text" style="font-weight: 900;">${p.text || ''}</div></div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'price_tag'), html: (p, isLandscape) => {
      const hasCode = p.code_type && p.code_type !== 'none' && p.code_data;
      const isQR = p.code_type === 'qrcode';
      const codeHtml = hasCode ? `<div class="catlabel-code" data-type="${isQR ? 'qrcode' : 'barcode'}" data-format="code128" data-value="${p.code_data}"></div>` : '';

      if (isLandscape) {
        return `
          <div class="label-canvas-container" style="display: flex; flex-direction: row; padding: 4%; gap: 4%;">
            <div style="flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; gap: 4%;">
              <div style="flex: 1; display: flex; flex-direction: row; gap: 2%;">
                <div class="bound-box" style="flex: 0.2; align-items: flex-start;"><div class="auto-text" style="font-weight: 900;">${p.currency_symbol || ''}</div></div>
                <div class="bound-box" style="flex: 0.6;"><div class="auto-text" style="font-weight: 900; white-space: nowrap;">${p.price_main || ''}</div></div>
                <div style="flex: 0.2; display: flex; flex-direction: column;">
                  <div class="bound-box" style="flex: 1; align-items: flex-start;"><div class="auto-text" style="font-weight: 900; text-decoration: underline;">${p.price_cents || '00'}</div></div>
                  <div class="bound-box" style="flex: 1; align-items: flex-start;"><div class="auto-text" style="font-weight: 700;">${p.unit || ''}</div></div>
                </div>
              </div>
              <div class="bound-box" style="flex: 0.4; border-top: 2px solid black; padding-top: 2%;">
                <div class="auto-text" style="font-weight: 800; text-transform: uppercase; white-space: nowrap;">${p.product_name || ''}</div>
              </div>
            </div>
            ${hasCode ? `<div class="bound-box" style="${isQR ? 'flex: 0 1 auto; height: 100%; aspect-ratio: 1/1; margin: auto 0;' : 'flex: 0.6; min-width: 0;'}">${codeHtml}</div>` : ''}
          </div>`;
      }

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">
          <div style="flex: 1; display: flex; flex-direction: row; gap: 2%;">
            <div class="bound-box" style="flex: 0.2; align-items: flex-start;"><div class="auto-text" style="font-weight: 900;">${p.currency_symbol || ''}</div></div>
            <div class="bound-box" style="flex: 0.6;"><div class="auto-text" style="font-weight: 900; white-space: nowrap;">${p.price_main || ''}</div></div>
            <div style="flex: 0.2; display: flex; flex-direction: column;">
              <div class="bound-box" style="flex: 1; align-items: flex-start;"><div class="auto-text" style="font-weight: 900; text-decoration: underline;">${p.price_cents || '00'}</div></div>
              <div class="bound-box" style="flex: 1; align-items: flex-start;"><div class="auto-text" style="font-weight: 700;">${p.unit || ''}</div></div>
            </div>
          </div>
          <div class="bound-box" style="flex: 0.3; border-top: 2px solid black; padding-top: 2%;">
            <div class="auto-text" style="font-weight: 800; text-transform: uppercase; white-space: nowrap;">${p.product_name || ''}</div>
          </div>
          ${hasCode ? `<div class="bound-box" style="${isQR ? 'flex: 0 1 auto; width: 100%; aspect-ratio: 1/1; margin: 0 auto;' : 'flex: 0.6; min-height: 0;'}">${codeHtml}</div>` : ''}
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'inventory_tag'), html: (p, isLandscape) => {
      const isQR = p.code_type !== 'barcode';
      const codeHtml = p.code_data ? `<div class="catlabel-code" data-type="${isQR ? 'qrcode' : 'barcode'}" data-format="code128" data-value="${p.code_data}"></div>` : '';
      
      const codeContainerStyle = isLandscape
        ? (isQR ? `flex: 0 1 auto; height: 100%; aspect-ratio: 1/1; margin: auto 0;` : `flex: 0.6; min-width: 0;`)
        : (isQR ? `flex: 0 1 auto; width: 100%; aspect-ratio: 1/1; margin: 0 auto;` : `flex: 0.6; min-height: 0;`);

      const mainLayout = isLandscape ? 'row' : 'column';

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: ${mainLayout}; padding: 2%; gap: 4%;">
          ${codeHtml && isLandscape ? `<div style="${codeContainerStyle}">${codeHtml}</div>` : ''}
          <div style="flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 2%;">
            <div class="bound-box" style="flex: 1; background: black; color: white; border-radius: 2px;">
              <div class="auto-text" style="font-weight: 900; letter-spacing: 1px; white-space: nowrap;">${p.department || ''}</div>
            </div>
            ${codeHtml && !isLandscape ? `<div style="${codeContainerStyle}">${codeHtml}</div>` : ''}
            <div class="bound-box" style="flex: 1.5; justify-content: ${isLandscape ? 'flex-start' : 'center'};">
              <div class="auto-text" style="font-weight: 800; text-align: ${isLandscape ? 'left' : 'center'};">${p.title || ''}</div>
            </div>
            <div class="bound-box" style="flex: 1; justify-content: ${isLandscape ? 'flex-start' : 'center'};">
              <div class="auto-text" style="font-weight: 600; font-family: monospace; text-align: ${isLandscape ? 'left' : 'center'}; white-space: nowrap;">${p.sku || ''}</div>
            </div>
          </div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'cable_flag'), html: (p, isLandscape) => `
      <div class="label-canvas-container" style="position: relative; display: flex; flex-direction: ${isLandscape ? 'row' : 'column'}; padding: 0;">
        <div style="position: absolute; z-index: 10; ${isLandscape ? 'top: 0; bottom: 0; left: 50%; border-left: 3px dashed black; transform: translateX(-50%);' : 'left: 0; right: 0; top: 50%; border-top: 3px dashed black; transform: translateY(-50%);'}"></div>
        <div style="flex: 1; min-width: 0; min-height: 0; padding: 6%; display: flex; align-items: center; justify-content: center;"><div class="bound-box"><div class="auto-text" style="font-weight: 900; text-align: center;">${p.text || ''}</div></div></div>
        <div style="flex: 1; min-width: 0; min-height: 0; padding: 6%; display: flex; align-items: center; justify-content: center;"><div class="bound-box"><div class="auto-text" style="font-weight: 900; text-align: center;">${p.text || ''}</div></div></div>
      </div>` },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'shipping_address'), html: (p, isLandscape) => {
      if (isLandscape) {
        return `
          <div class="label-canvas-container" style="display: flex; flex-direction: row; padding: 0;">
            <div style="width: 15%; background: black; color: white; display: flex; align-items: center; justify-content: center; writing-mode: vertical-rl; transform: rotate(180deg);">
              <div class="bound-box" style="padding: 4%;">
                <div class="auto-text" style="font-weight: 900; letter-spacing: 2px; white-space: nowrap;">${p.service || ''}</div>
              </div>
            </div>
            <div style="flex: 1; display: flex; flex-direction: column; padding: 4%; gap: 2%;">
              <div style="flex: 0.35; display: flex; flex-direction: row; gap: 4%;">
                <div style="flex: 0.15; font-weight: 900; font-size: 10px; display: flex; align-items: flex-start;">FROM:</div>
                <div class="bound-box" style="flex: 0.85; align-items: flex-start; justify-content: flex-start;">
                  <div class="auto-text" style="font-weight: 600; text-align: left;">${p.sender || ''}</div>
                </div>
              </div>
              <div style="height: 2px; background: black; width: 100%; flex-shrink: 0;"></div>
              <div style="flex: 0.65; display: flex; flex-direction: column; gap: 2%;">
                <div style="background: black; color: white; padding: 2px 6px; font-weight: 900; align-self: flex-start; font-size: 12px; border-radius: 2px;">SHIP TO:</div>
                <div class="bound-box" style="flex: 1; align-items: flex-start; justify-content: flex-start;">
                  <div class="auto-text" style="font-weight: 900; text-align: left; line-height: 1.1 !important;">${p.recipient || ''}</div>
                </div>
              </div>
            </div>
          </div>`;
      }

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 0;">
          <div style="height: 15%; background: black; color: white; display: flex; align-items: center; justify-content: center;">
            <div class="bound-box" style="padding: 2%;">
              <div class="auto-text" style="font-weight: 900; letter-spacing: 2px; white-space: nowrap;">${p.service || ''}</div>
            </div>
          </div>
          <div style="flex: 1; display: flex; flex-direction: column; padding: 4%; gap: 3%;">
            <div class="bound-box" style="flex: 0.3; align-items: flex-start; justify-content: flex-start;">
              <div class="auto-text" style="font-weight: 600; text-align: left;">${p.sender || ''}</div>
            </div>
            <div style="height: 2px; background: black; width: 100%; flex-shrink: 0;"></div>
            <div style="flex: 0.7; display: flex; flex-direction: column; gap: 2%;">
              <div style="font-weight: 900; font-size: 14px; display: flex; align-items: flex-start;">TO:</div>
              <div class="bound-box" style="flex: 1; align-items: flex-start; justify-content: flex-start;">
                <div class="auto-text" style="font-weight: 900; text-align: left; line-height: 1.1 !important;">${p.recipient || ''}</div>
              </div>
            </div>
          </div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'warning_banner'), html: (p) => `
      <div class="label-canvas-container" style="background: black; color: white; padding: 4%;">
        <div class="bound-box" style="border: max(2px, 4cqmin) solid white; padding: 4%;">
          <div class="auto-text" style="font-weight: 900; text-transform: uppercase; letter-spacing: 2px; white-space: pre-wrap;">${p.text || ''}</div>
        </div>
      </div>` },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'sale_tag'), html: (p, isLandscape) => {
      if (isLandscape) {
        return `
          <div class="label-canvas-container" style="display: flex; flex-direction: row; padding: 0;">
            <div style="flex: 1; padding: 4%; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; gap: 2%;">
              <div class="bound-box" style="flex: 0.4; align-items: flex-end; justify-content: flex-start;">
                <div class="auto-text" style="font-weight: 700; text-align: left; white-space: nowrap;">${p.product_name || ''}</div>
              </div>
              <div class="bound-box" style="flex: 0.6; align-items: flex-start; justify-content: flex-start;">
                <div class="auto-text" style="font-weight: 900; text-decoration: line-through; text-decoration-thickness: 3px; text-align: left; white-space: nowrap;">${p.currency || ''}${p.old_price || ''}</div>
              </div>
            </div>
            <div style="flex: 1.2; background: black; color: white; display: flex; align-items: center; justify-content: center; padding: 4%;">
              <div class="bound-box"><div class="auto-text" style="font-weight: 900; white-space: nowrap;">${p.currency || ''}${p.new_price || ''}</div></div>
            </div>
          </div>`;
      }

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 0;">
          <div style="flex: 1; padding: 4%; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 2%;">
            <div class="bound-box" style="flex: 0.4;">
              <div class="auto-text" style="font-weight: 700; white-space: nowrap;">${p.product_name || ''}</div>
            </div>
            <div class="bound-box" style="flex: 0.6;">
              <div class="auto-text" style="font-weight: 900; text-decoration: line-through; text-decoration-thickness: 3px; white-space: nowrap;">${p.currency || ''}${p.old_price || ''}</div>
            </div>
          </div>
          <div style="flex: 1.2; background: black; color: white; display: flex; align-items: center; justify-content: center; padding: 4%;">
            <div class="bound-box"><div class="auto-text" style="font-weight: 900; white-space: nowrap;">${p.currency || ''}${p.new_price || ''}</div></div>
          </div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'asset_tag'), html: (p, isLandscape) => {
      const hasCode = p.code_type !== 'none';
      const isQR = p.code_type === 'qrcode';
      const codeHtml = hasCode ? `<div class="catlabel-code" data-type="${isQR ? 'qrcode' : 'barcode'}" data-format="code128" data-value="${p.asset_id}"></div>` : '';

      const codeContainerStyle = isLandscape
        ? (isQR ? `flex: 0 1 auto; height: 100%; aspect-ratio: 1/1; margin: auto 0;` : `flex: 0.6; min-width: 0;`)
        : (isQR ? `flex: 0 1 auto; width: 100%; aspect-ratio: 1/1; margin: 0 auto;` : `flex: 0.6; min-height: 0;`);

      if (isLandscape && codeHtml) {
        return `
          <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 4%; gap: 6%;">
            <div class="bound-box" style="flex: 1; background: black; color: white; border-radius: 2px;">
              <div class="auto-text" style="font-weight: 900; letter-spacing: 2px; white-space: nowrap;">${p.department || ''}</div>
            </div>
            <div style="flex: 3; min-width: 0; min-height: 0; display: flex; gap: 6%;">
              ${hasCode ? `<div style="${codeContainerStyle}">${codeHtml}</div>` : ''}
              <div style="flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 4%;">
                <div class="bound-box" style="flex: 2; justify-content: flex-start;"><div class="auto-text" style="font-weight: 900; text-align: left; white-space: nowrap; font-family: monospace;">${p.asset_id || ''}</div></div>
                <div class="bound-box" style="flex: 1.5; justify-content: flex-start;"><div class="auto-text" style="font-weight: 500; font-style: italic; text-align: left;">${p.description || ''}</div></div>
              </div>
            </div>
          </div>`;
      }

      return `
        <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 4%; gap: 6%;">
          <div class="bound-box" style="flex: 1; background: black; color: white; border-radius: 2px;">
            <div class="auto-text" style="font-weight: 900; letter-spacing: 2px; white-space: nowrap;">${p.department || ''}</div>
          </div>
          ${hasCode ? `<div style="${codeContainerStyle}">${codeHtml}</div>` : ''}
          <div class="bound-box" style="flex: 1.5;"><div class="auto-text" style="font-weight: 900; white-space: nowrap; font-family: monospace;">${p.asset_id || ''}</div></div>
          <div class="bound-box" style="flex: 1;"><div class="auto-text" style="font-weight: 500; font-style: italic;">${p.description || ''}</div></div>
        </div>`;
    } },
  { ...TEMPLATE_CATALOG.find(template => template.id === 'expiration_date'), html: (p) => {
      let html = `<div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">`;
      if (p.product_name) html += `<div class="bound-box" style="flex: 1.5;"><div class="auto-text" style="font-weight: 800; text-transform: uppercase;">${p.product_name}</div></div>`;
      if (p.made_date) html += `<div class="bound-box" style="flex: 1;"><div class="auto-text" style="font-weight: 600; white-space: nowrap;">MFG: ${p.made_date}</div></div>`;
      html += `<div class="bound-box" style="flex: 2.5; background: black; color: white; padding: 2%; border-radius: 4px;"><div class="auto-text" style="font-weight: 900; white-space: nowrap; letter-spacing: 1px;">EXP: ${p.exp_date || ''}</div></div></div>`;
      return html;
    } },
];

const escapeHtml = (value = '') => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const formatText = (value = '') => escapeHtml(value).replace(/\n/g, '<br />');

const LEGACY_FIELD_NAMES = [
  'text',
  'title',
  'subtitle',
  'custom_html',
  'icon_src',
  'direction',
  'data',
  'currency_symbol',
  'price_main',
  'price_cents',
  'unit',
  'product_name',
  'barcode',
  'department',
  'sku',
  'code_type',
  'code_data',
  'service',
  'sender',
  'recipient',
  'old_price',
  'new_price',
  'currency',
  'asset_id',
  'description',
  'style',
  'exp_date',
  'made_date',
  'show_header',
  'header_text',
  'show_subtitle',
  'subtitle_text'
];

const getTemplateMetadata = (templateId) =>
  TEMPLATE_METADATA.find((template) => template.id === templateId) || TEMPLATE_METADATA.find(t => t.id === 'title_subtitle');

const resolveTemplateParams = (item = {}, record = {}) => {
  const templateId = item.template_id || 'title_subtitle';
  const templateMetadata = getTemplateMetadata(templateId);
  const sourceParams = item.params && typeof item.params === 'object' ? item.params : {};
  const mergedParams = {};

  (templateMetadata.fields || []).forEach((field) => {
    mergedParams[field.name] = sourceParams[field.name] ?? item[field.name] ?? field.default ?? '';
  });

  LEGACY_FIELD_NAMES.forEach((fieldName) => {
    if (mergedParams[fieldName] === undefined) {
      mergedParams[fieldName] = sourceParams[fieldName] ?? item[fieldName] ?? '';
    }
  });

  const resolvedParams = {};
  Object.entries(mergedParams).forEach(([key, value]) => {
    if (typeof value === 'boolean') {
      resolvedParams[key] = value;
      return;
    }
    const resolvedValue = applyVars(value ?? '', record);
    resolvedParams[key] = key === 'custom_html'
      ? sanitizeLabelHtml(resolvedValue)
      : formatText(resolvedValue);
  });

  return resolvedParams;
};

export const buildLabelTemplateMarkup = (item = {}, record = {}) => {
  const templateId = item.template_id || 'title_subtitle';
  const p = resolveTemplateParams(item, record);
  const isLandscape = Number(item.width || 384) > Number(item.height || 384);
  const templateMetadata = getTemplateMetadata(templateId);

  if (typeof templateMetadata.html === 'function') {
    return templateMetadata.html(p, isLandscape);
  }

  let rawHtml = templateMetadata.html || '<div class="label-canvas-container"><div class="bound-box"><div class="auto-text">{{ text }}</div></div></div>';
  Object.entries(p).forEach(([key, val]) => {
    const regex = new RegExp(`{{\\s*${key}\\s*}}`, 'g');
    rawHtml = rawHtml.replace(regex, val);
  });
  return rawHtml;
};

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
  {
    id: 'spice_jar',
    category: 'Dedicated',
    name: 'Pantry / Spice Jar',
    description: 'Elegant typography for home organization. Highly adaptable.',
    fields: [
      {
        name: 'style',
        label: 'Design Style',
        type: 'select',
        options: [
          { label: 'Apothecary (Classic)', value: 'jar_apothecary' },
          { label: 'Farmhouse (Stripes & Clean)', value: 'jar_farmhouse' },
        ],
        default: 'jar_apothecary',
      },
      { name: 'show_header', label: 'Include Top Header', type: 'boolean', default: true },
      { name: 'header_text', label: 'Top Header Text', type: 'text', default: 'PREMIUM' },
      { name: 'title', label: 'Main Label', type: 'text', default: 'BASIL' },
      { name: 'show_subtitle', label: 'Include Subtitle', type: 'boolean', default: true },
      { name: 'subtitle_text', label: 'Subtitle / Details', type: 'text', default: 'Sweet & Aromatic' },
    ],
    html: (p) => {
      const isFarmhouse = p.style === 'jar_farmhouse';
      return isFarmhouse ? buildJarFarmhouseMarkup(p) : buildJarApothecaryMarkup(p);
    },
  },
  {
    id: 'title_subtitle',
    category: 'Layout',
    name: 'Title & Subtitle',
    description: 'Stacked text with a large bold title.',
    fields: [
      { name: 'title', label: 'Title', type: 'text', default: 'MAIN TITLE' },
      { name: 'subtitle', label: 'Subtitle', type: 'text', default: 'Subheading text goes here' },
    ],
    html: (p) => `
      <div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">
        <div class="bound-box" style="flex: 2.0;">
          <div class="auto-text" style="font-weight: 900; text-transform: uppercase; white-space: nowrap;">${p.title || ''}</div>
        </div>
        <div style="height: 3px; background: black; width: 100%; margin: 2% auto; flex-shrink: 0;"></div>
        <div class="bound-box" style="flex: 1.0;">
          <div class="auto-text" style="font-weight: 700;">${p.subtitle || ''}</div>
        </div>
      </div>`,
  },
  {
    id: 'icon_text',
    category: 'Layout',
    name: 'Icon + Text',
    description: 'A clean icon next to your text.',
    fields: [
      { name: 'icon_src', label: 'Icon', type: 'icon' },
      { name: 'text', label: 'Text', type: 'text', default: 'Label' },
      {
        name: 'direction',
        label: 'Layout',
        type: 'select',
        options: [
          { label: 'Row (Left to Right)', value: 'row' },
          { label: 'Column (Top to Bottom)', value: 'col' },
        ],
        default: 'row',
      },
    ],
    html: (p) => {
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
    },
  },
  {
    id: 'qr_text',
    category: 'Layout',
    name: 'QR Code + Text',
    description: 'A QR code with adjacent text.',
    fields: [
      { name: 'data', label: 'QR Data', type: 'text', default: 'https://google.com' },
      { name: 'text', label: 'Text', type: 'textarea', default: 'Scan Me' },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'price_tag',
    category: 'Dedicated',
    name: 'Price Tag with Barcode',
    description: 'Retail price tag. Automatically adapts to square or wide labels.',
    fields: [
      { name: 'currency_symbol', label: 'Currency Symbol', type: 'text', default: '$' },
      { name: 'price_main', label: 'Main Price', type: 'text', default: '19' },
      { name: 'price_cents', label: 'Cents', type: 'text', default: '99' },
      { name: 'unit', label: 'Unit (e.g. /ea)', type: 'text', default: '' },
      { name: 'product_name', label: 'Product Name', type: 'text', default: 'Product Name' },
      {
        name: 'code_type',
        label: 'Code Type',
        type: 'select',
        options: [
          { label: 'Barcode', value: 'barcode' },
          { label: 'QR Code', value: 'qrcode' },
          { label: 'None', value: 'none' },
        ],
        default: 'barcode',
      },
      { name: 'code_data', label: 'Code Data', type: 'text', default: '123456789' },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'inventory_tag',
    category: 'Dedicated',
    name: 'Inventory Tag',
    description: 'Professional asset tag with inverted department header and QR/Barcode.',
    fields: [
      { name: 'department', label: 'Department / Category', type: 'text', default: 'WAREHOUSE' },
      { name: 'title', label: 'Item Name', type: 'text', default: 'Item Name' },
      { name: 'sku', label: 'SKU / Subtext', type: 'text', default: 'SKU-123' },
      {
        name: 'code_type',
        label: 'Code Type',
        type: 'select',
        options: [
          { label: 'QR Code', value: 'qrcode' },
          { label: 'Barcode', value: 'barcode' },
        ],
        default: 'qrcode',
      },
      { name: 'code_data', label: 'Code Data', type: 'text', default: 'INV-001' },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'cable_flag',
    category: 'Dedicated',
    name: 'Cable Flag',
    description: 'Fold-over tag with a dashed center line. Repeats text on both sides.',
    fields: [{ name: 'text', label: 'Cable ID / Text', type: 'text', default: 'CABLE-01' }],
    html: (p, isLandscape) => `
      <div class="label-canvas-container" style="position: relative; display: flex; flex-direction: ${isLandscape ? 'row' : 'column'}; padding: 0;">
        <div style="position: absolute; z-index: 10; ${isLandscape ? 'top: 0; bottom: 0; left: 50%; border-left: 3px dashed black; transform: translateX(-50%);' : 'left: 0; right: 0; top: 50%; border-top: 3px dashed black; transform: translateY(-50%);'}"></div>
        <div style="flex: 1; min-width: 0; min-height: 0; padding: 6%; display: flex; align-items: center; justify-content: center;"><div class="bound-box"><div class="auto-text" style="font-weight: 900; text-align: center;">${p.text || ''}</div></div></div>
        <div style="flex: 1; min-width: 0; min-height: 0; padding: 6%; display: flex; align-items: center; justify-content: center;"><div class="bound-box"><div class="auto-text" style="font-weight: 900; text-align: center;">${p.text || ''}</div></div></div>
      </div>`,
  },
  {
    id: 'shipping_address',
    category: 'Dedicated',
    name: 'Shipping Address',
    description: 'Professional shipping label with service banner and sender/recipient blocks.',
    fields: [
      { name: 'service', label: 'Service Type', type: 'text', default: 'PRIORITY' },
      { name: 'sender', label: 'Sender Address', type: 'textarea', default: 'John Doe\n123 Sender St.' },
      { name: 'recipient', label: 'Recipient Address', type: 'textarea', default: 'Jane Smith\n456 Recipient Ave.' },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'warning_banner',
    category: 'Dedicated',
    name: 'Warning Banner',
    description: 'Inverted black background with bold white text.',
    fields: [{ name: 'text', label: 'Warning Text', type: 'text', default: 'FRAGILE' }],
    html: (p) => `
      <div class="label-canvas-container" style="background: black; color: white; padding: 4%;">
        <div class="bound-box" style="border: max(2px, 4cqmin) solid white; padding: 4%;">
          <div class="auto-text" style="font-weight: 900; text-transform: uppercase; letter-spacing: 2px; white-space: pre-wrap;">${p.text || ''}</div>
        </div>
      </div>`,
  },
  {
    id: 'sale_tag',
    category: 'Dedicated',
    name: 'Retail Sale Tag',
    description: 'High contrast inverted price box.',
    fields: [
      { name: 'product_name', label: 'Product', type: 'text', default: 'Sale Item' },
      { name: 'old_price', label: 'Old Price', type: 'text', default: '29.99' },
      { name: 'new_price', label: 'New Price', type: 'text', default: '19.99' },
      { name: 'currency', label: 'Currency', type: 'text', default: '$' },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'asset_tag',
    category: 'Dedicated',
    name: 'IT Asset Tag',
    description: 'Header bar, QR code, and details.',
    fields: [
      { name: 'department', label: 'Department', type: 'text', default: 'IT DEPT' },
      { name: 'asset_id', label: 'Asset ID', type: 'text', default: 'AST-0001' },
      { name: 'description', label: 'Description', type: 'text', default: 'Laptop Computer' },
      {
        name: 'code_type',
        label: 'Code Type',
        type: 'select',
        options: [
          { label: 'QR Code', value: 'qrcode' },
          { label: 'Barcode', value: 'barcode' },
          { label: 'None', value: 'none' },
        ],
        default: 'qrcode',
      },
    ],
    html: (p, isLandscape) => {
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
    },
  },
  {
    id: 'expiration_date',
    category: 'Dedicated',
    name: 'Expiration / Batch Date',
    description: 'Prominent expiration date.',
    fields: [
      { name: 'product_name', label: 'Product Name (Optional)', type: 'text', default: '' },
      { name: 'exp_date', label: 'Expiration Date', type: 'date', default: '2025-12-31' },
      { name: 'made_date', label: 'Mfg / Made On (Optional)', type: 'date', default: '' },
    ],
    html: (p) => {
      let html = `<div class="label-canvas-container" style="display: flex; flex-direction: column; padding: 6%; gap: 4%;">`;
      if (p.product_name) html += `<div class="bound-box" style="flex: 1.5;"><div class="auto-text" style="font-weight: 800; text-transform: uppercase;">${p.product_name}</div></div>`;
      if (p.made_date) html += `<div class="bound-box" style="flex: 1;"><div class="auto-text" style="font-weight: 600; white-space: nowrap;">MFG: ${p.made_date}</div></div>`;
      html += `<div class="bound-box" style="flex: 2.5; background: black; color: white; padding: 2%; border-radius: 4px;"><div class="auto-text" style="font-weight: 900; white-space: nowrap; letter-spacing: 1px;">EXP: ${p.exp_date || ''}</div></div></div>`;
      return html;
    },
  },
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

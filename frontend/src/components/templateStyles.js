export const TEMPLATE_MAP = {
  default: { container: 'layout-default', text: 'text-standard', sub: null },
  center: { container: 'layout-center', text: 'text-standard', sub: null },
  maximize: { container: 'layout-center', text: 'text-maximized', sub: null },
  title_subtitle: { container: 'layout-flex-col', text: 'text-title', sub: 'text-subtitle' },
  warning_banner: { container: 'layout-banner', text: 'text-bold-inverted', sub: null },
  price_tag: { container: 'layout-price', text: 'text-huge-price', sub: 'text-product-name' },
  address: { container: 'layout-address', text: 'text-address', sub: null },
  custom: { container: 'layout-default', text: null, sub: null }
};

export const LABEL_TEMPLATE_STYLES = `
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  background: white;
}
body {
  overflow: hidden;
}
.label-canvas-container {
  container-type: size;
  container-name: label;
  width: 100%;
  height: 100%;
  background-color: white;
  box-sizing: border-box;
  overflow: hidden;
  padding: 4cqmin;
  display: flex;
}
.label-canvas-container * {
  box-sizing: border-box;
}
.label-copy {
  max-width: 100%;
  max-height: 100%;
  overflow-wrap: anywhere;
}
.layout-default {
  justify-content: flex-start;
  align-items: flex-start;
}
.layout-center {
  justify-content: center;
  align-items: center;
  text-align: center;
}
.layout-flex-col {
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
  gap: 4cqh;
}
.layout-banner {
  justify-content: center;
  align-items: center;
  text-align: center;
  padding: 0 6cqw;
  background: #111827;
  color: white;
}
.layout-price {
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
  text-align: center;
  padding: 10cqh 5cqw;
}
.layout-address {
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  text-align: left;
  padding: 8cqh 10cqw;
}
.text-standard {
  width: 100%;
  font-size: 22cqh;
  font-weight: 700;
  line-height: 1.05;
}
.text-maximized {
  width: 100%;
  font-size: 72cqh;
  font-weight: 900;
  line-height: 0.85;
  text-align: center;
}
.text-title {
  width: 100%;
  font-size: 32cqh;
  font-weight: 900;
  line-height: 0.95;
}
.text-subtitle {
  width: 100%;
  font-size: 16cqh;
  font-weight: 600;
  line-height: 1.1;
}
.text-bold-inverted {
  width: 100%;
  font-size: 30cqh;
  font-weight: 900;
  line-height: 0.95;
  text-transform: uppercase;
}
.text-huge-price {
  font-size: 45cqh;
  font-weight: 900;
  line-height: 1;
}
.text-product-name {
  font-size: 15cqh;
  font-weight: 700;
  line-height: 1.1;
  text-transform: uppercase;
  color: #333333;
}
.text-address {
  width: 100%;
  font-size: 18cqh;
  font-weight: 700;
  line-height: 1.4;
  white-space: pre-wrap;
}
`;

const escapeHtml = (value = '') => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const formatText = (value = '') => escapeHtml(value).replace(/\n/g, '<br />');

export const sanitizeLabelHtml = (html = '') => {
  const clean = String(html)
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?>[\s\S]*?<\/iframe>/gi, '')
    .replace(/<(object|embed|form)[\s\S]*?>[\s\S]*?<\/\1>/gi, '')
    .replace(/\son\w+\s*=\s*(".*?"|'.*?'|[^\s>]+)/gi, '')
    .replace(/javascript\s*:/gi, '')
    .trim();

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(clean, 'text/html');
    const serializer = new XMLSerializer();

    let xmlString = '';
    Array.from(doc.body.childNodes).forEach((node) => {
      xmlString += serializer.serializeToString(node);
    });

    return xmlString;
  } catch (e) {
    console.error('HTML to XML serialization failed', e);
    return clean;
  }
};

export const buildLabelTemplateMarkup = (record = {}) => {
  const safeRecord = record && typeof record === 'object' ? record : {};
  const templateId = safeRecord.template_id || 'default';
  const activeTemplate = TEMPLATE_MAP[templateId] || TEMPLATE_MAP.default;

  if (templateId === 'custom') {
    return [
      '<div class="label-canvas-container">',
      `<div style="width:100%;height:100%;">${sanitizeLabelHtml(safeRecord.custom_html || '')}</div>`,
      '</div>'
    ].join('');
  }

  if (templateId === 'title_subtitle' || templateId === 'price_tag') {
    return [
      `<div class="label-canvas-container ${activeTemplate.container}">`,
      `<div class="label-copy ${activeTemplate.text}">${formatText(safeRecord.title || '')}</div>`,
      `<div class="label-copy ${activeTemplate.sub}">${formatText(safeRecord.subtitle || '')}</div>`,
      '</div>'
    ].join('');
  }

  return [
    `<div class="label-canvas-container ${activeTemplate.container}">`,
    `<div class="label-copy ${activeTemplate.text}">${formatText(safeRecord.text || safeRecord.title || '')}</div>`,
    '</div>'
  ].join('');
};

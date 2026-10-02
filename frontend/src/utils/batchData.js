import resourceLimits from '../../../catlabel/data/resource_limits.json';

export const MAX_BATCH_RECORDS = resourceLimits.max_batch_records;
export const MAX_PRINT_JOBS = resourceLimits.max_print_jobs;
export const MAX_PRINT_COPIES = resourceLimits.max_print_copies;
export const MAX_RENDER_PIXELS = resourceLimits.max_render_pixels;

const limitError = (kind, count, limit) => new RangeError(
  `${kind} would create ${count.toLocaleString()} entries; the safety limit is ${limit.toLocaleString()}.`
);

export const buildBatchMatrix = (matrixDefinition, limit = MAX_BATCH_RECORDS) => {
  const keys = Object.keys(matrixDefinition || {});
  if (keys.length === 0) return [{}];

  const valuesByKey = keys.map((key) => {
    const values = String(matrixDefinition[key] || '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    return values.length > 0 ? values : [''];
  });

  const combinationCount = valuesByKey.reduce((count, values) => {
    const nextCount = count * values.length;
    if (!Number.isSafeInteger(nextCount) || nextCount > limit) {
      throw limitError('This matrix', nextCount, limit);
    }
    return nextCount;
  }, 1);

  if (combinationCount > limit) {
    throw limitError('This matrix', combinationCount, limit);
  }

  let records = [{}];
  keys.forEach((key, keyIndex) => {
    records = records.flatMap((record) => valuesByKey[keyIndex].map((value) => ({
      ...record,
      [key]: value
    })));
  });
  return records;
};

export const buildBatchSequence = (definition, limit = MAX_BATCH_RECORDS) => {
  const { varName, start, end, prefix = '', suffix = '', padding = 0 } = definition || {};
  if (!String(varName || '').trim()) return [{}];

  const sequenceStart = Number.parseInt(start, 10) || 0;
  const sequenceEnd = Number.parseInt(end, 10) || 0;
  const count = Math.abs(sequenceEnd - sequenceStart) + 1;
  if (count > limit) throw limitError('This sequence', count, limit);

  const pad = Math.max(0, Number.parseInt(padding, 10) || 0);
  const step = sequenceStart <= sequenceEnd ? 1 : -1;
  const records = [];

  for (
    let value = sequenceStart;
    step > 0 ? value <= sequenceEnd : value >= sequenceEnd;
    value += step
  ) {
    records.push({
      [String(varName).trim()]: `${prefix}${String(value).padStart(pad, '0')}${suffix}`
    });
  }

  return records.length ? records : [{}];
};

export const getPrintJobCount = ({ records = 1, copies = 1, pages = 1 } = {}) => (
  Math.max(1, Number(records) || 1)
  * Math.max(1, Number(copies) || 1)
  * Math.max(1, Number(pages) || 1)
);

export const getRenderPixelCount = ({ width = 1, height = 1, jobs = 1 } = {}) => (
  Math.max(1, Number(width) || 1)
  * Math.max(1, Number(height) || 1)
  * Math.max(1, Number(jobs) || 1)
);

const collectTemplateText = (item) => {
  if (!item) return [];
  return [
    item.text,
    item.title,
    item.subtitle,
    item.data,
    item.html,
    item.custom_html,
    ...Object.values(item.params || {}),
    ...(item.children || []).flatMap(collectTemplateText)
  ].filter((value) => value !== null && value !== undefined);
};

export const extractTemplateVariables = ({ items = [], pageLayouts = [] } = {}) => {
  const variables = new Set();
  const values = [
    ...(Array.isArray(items) ? items : []).flatMap(collectTemplateText),
    ...(Array.isArray(pageLayouts) ? pageLayouts : []).flatMap((layout) => [
      layout?.htmlContent,
      ...Object.values(layout?.activeTemplate?.params || {})
    ])
  ];

  values.forEach((value) => {
    const matches = String(value || '').match(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g) || [];
    matches.forEach((match) => variables.add(match.replace(/[{}]/g, '').trim()));
  });

  return [...variables];
};

const parseCsvRows = (input) => {
  const text = String(input || '').replace(/^\uFEFF/, '');
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const nextChar = text[index + 1];

    if (quoted) {
      if (char === '"' && nextChar === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"' && field.length === 0) {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && nextChar === '\n') index += 1;
      row.push(field);
      if (row.some((value) => value.trim() !== '')) rows.push(row);
      row = [];
      field = '';
    } else {
      field += char;
    }
  }

  if (quoted) throw new Error('The CSV contains an unterminated quoted field.');
  row.push(field);
  if (row.some((value) => value.trim() !== '')) rows.push(row);
  return rows;
};

export const parseCsvRecords = (input, limit = MAX_BATCH_RECORDS) => {
  const rows = parseCsvRows(input);
  if (rows.length === 0) return { headers: [], records: [] };

  const headers = rows[0].map((header) => header.trim());
  if (headers.some((header) => !header)) {
    throw new Error('Every CSV column must have a non-empty header.');
  }
  if (new Set(headers).size !== headers.length) {
    throw new Error('CSV column headers must be unique.');
  }

  const dataRows = rows.slice(1);
  if (dataRows.length > limit) throw limitError('This CSV', dataRows.length, limit);

  const records = dataRows.map((values) => Object.fromEntries(
    headers.map((header, index) => [header, values[index]?.trim() || ''])
  ));
  return { headers, records };
};

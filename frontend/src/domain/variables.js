export const applyVars = (str, record) => {
  if (!str) return str;

  let result = String(str);

  if (record) {
    Object.keys(record).forEach((key) => {
      const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`{{\\s*${escapedKey}\\s*}}`, 'g');
      result = result.replace(regex, String(record[key] ?? ''));
    });
  }

  const now = new Date();
  const formatYMD = (dateObj) => {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  };

  result = result.replace(/{{\s*\$date\s*}}/g, formatYMD(now));
  result = result.replace(/{{\s*\$time\s*}}/g, now.toTimeString().substring(0, 5));
  result = result.replace(/{{\s*\$date([+-])(\d+)\s*}}/g, (match, op, daysStr) => {
    const days = parseInt(daysStr, 10);
    const nextDate = new Date(now);
    nextDate.setDate(nextDate.getDate() + (op === '+' ? days : -days));
    return formatYMD(nextDate);
  });

  return result;
};

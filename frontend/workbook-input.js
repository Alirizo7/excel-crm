// User input uses a decimal comma or dot; spaces separate groups of thousands.
// Formula syntax stays unchanged (commas there separate function arguments).
export function parseInputNumber(value) {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (!/^[+-]?(?:(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?%?$/.test(text)) return null;
  const normalized = text.replace(/[ \u00a0\u202f]/g, '').replace(',', '.');
  // Only normalize numbers within Excel's 15 significant digits.
  const digits = normalized.split(/[eE]/)[0].replace(/\D/g, '').replace(/^0+/, '');
  if (digits.length > 15) return null;
  const number = Number(normalized.replace(/%$/, '')) / (text.endsWith('%') ? 100 : 1);
  return Number.isFinite(number) ? number : null;
}

export function normalizePlainPaste(text, isTextCell) {
  return text.split('\n').map((line, row) => line.split('\t').map((value, col) => {
    if (isTextCell(row, col)) return value;
    const number = parseInputNumber(value);
    if (number === null) return value;
    // Let the engine retain a percentage format when the user supplies one.
    return value.trim().endsWith('%') ? value.trim().replace(/[ \u00a0\u202f]/g, '').replace(',', '.') : String(number);
  }).join('\t')).join('\n');
}

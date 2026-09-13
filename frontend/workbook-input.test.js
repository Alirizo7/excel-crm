import test from 'node:test';
import assert from 'node:assert/strict';
import { parseInputNumber, normalizePlainPaste } from './workbook-input.js';

test('decimal comma, dot, signs, grouping, exponent and percentage', () => {
  for (const [text, value] of [['3,5',3.5],['1,234',1.234],['3.5',3.5],['-0,25',-.25],
    ['0',0],['+3,5',3.5],[' 1 234,56 ',1234.56],['1\u00a0234,5',1234.5],
    ['1\u202f234.5',1234.5],[',5',.5],['3,5e2',350],['3,5%',.035]]) {
    assert.equal(parseInputNumber(text), value, text);
  }
});

test('never reinterpret formulas, dates, literal text or malformed numbers', () => {
  for (const text of ['', ' ', "'3,5", '=SUM(A1,A2)', '1,2,3', '1,234.56', '12 34',
    '13.09.2026', '01/02/2026', '3,5 кг', '12345678901234567', '1e999']) {
    assert.equal(parseInputNumber(text), null, text);
  }
});

test('tabular paste preserves text cells and formulas while converting numeric columns', () => {
  const text = "3,5\t1,234\t'=SUM(A1,A2)\n-1 200,25\t001,234\t=SUM(A1,A2)";
  assert.equal(normalizePlainPaste(text, (r,c) => r===1 && c===1),
    "3.5\t1.234\t'=SUM(A1,A2)\n-1200.25\t001,234\t=SUM(A1,A2)");
  assert.equal(normalizePlainPaste('3,5%\r\n4,5', () => false), '3.5%\n4.5');
});

import { UniverSheetsNodeCorePreset } from '@univerjs/preset-sheets-node-core';
import { createUniver, LocaleType } from '@univerjs/presets';
import localeDefault from '@univerjs/preset-sheets-node-core/locales/en-US';

const localeModule = { default: localeDefault };

// stdin/stdout protocol: financial data never goes into command-line arguments.
let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) {
  input += chunk;
  if (input.length > 20 * 1024 * 1024) throw new Error('Workbook too large');
}
const data = JSON.parse(input);
const isolated = [];
for (const [sid, sheet] of Object.entries(data.sheets)) {
  for (const [r, row] of Object.entries(sheet.cellData ?? {})) {
    for (const [c, cell] of Object.entries(row)) {
      if (!cell?.f) continue;
      cell.f = cell.f.replace(/^=\+/, '=');
      // A legacy bare range can spill over existing financial cells in modern
      // engines. Preserve it as an explicit error, without overwriting neighbors.
      if (/^=(?:(?:'[^']+'|[\p{L}\p{N}_ ]+)!)?\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+$/u.test(cell.f)) {
        isolated.push([sid, r, c, cell.f]);
        cell.f = '=NA()';
      }
    }
  }
}
const { univer, univerAPI } = createUniver({
  locale: LocaleType.EN_US,
  locales: { [LocaleType.EN_US]: localeModule.default ?? localeModule },
  presets: [UniverSheetsNodeCorePreset({ formula: { initialFormulaComputing: 0 } })],
});
try {
  const book = univerAPI.createWorkbook(data);
  const engine = univerAPI.getFormula();
  engine.executeCalculation();
  await engine.onCalculationResultApplied(20000);
  const output = book.save();
  for (const [sid, r, c, formula] of isolated) output.sheets[sid].cellData[r][c].f = formula;
  process.stdout.write(JSON.stringify(output));
} finally {
  univer.dispose();
}

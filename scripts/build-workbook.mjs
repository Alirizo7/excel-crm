import { build } from 'esbuild';
await build({entryPoints: ['frontend/workbook.js'], bundle: true, minify: true,
  outdir: 'static/workbook', format: 'iife', target: ['es2022'], legalComments: 'linked',
  define: {'process.env.NODE_ENV': '"production"'}, logLevel: 'info'});
await build({entryPoints: ['scripts/calculate-workbook.mjs'], bundle: true, minify: true,
  outfile: 'scripts/calculate-workbook.bundle.mjs', platform: 'node', format: 'esm', target: ['node22'],
  legalComments: 'linked', define: {'process.env.NODE_ENV': '"production"'}, logLevel: 'info'});

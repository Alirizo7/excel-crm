import { createRequire } from 'node:module';
import test from 'node:test';
import assert from 'node:assert/strict';
import { serializeWorkbook, insertRowFromTemplate } from './workbook-state.js';
const require=createRequire(import.meta.url);
const { createUniver, LocaleType }=require('@univerjs/presets');
const { UniverSheetsNodeCorePreset, InsertRowCommand, SetRangeValuesMutation, SetRowDataMutation,
  SheetInterceptorService }=require('@univerjs/preset-sheets-node-core');
const locale=require('@univerjs/preset-sheets-node-core/locales/en-US');

test('autosave preserves undo/redo and stable row identity with the real engine', async()=>{
  const {univer,univerAPI:api}=createUniver({locale:LocaleType.EN_US,
    locales:{[LocaleType.EN_US]:locale.default??locale},presets:[UniverSheetsNodeCorePreset()]});
  try{
    const book=api.createWorkbook({id:'audit',name:'Audit',sheetOrder:['s'],sheets:{s:{id:'s',name:'Data',
      rowCount:20,columnCount:5,cellData:{3:{0:{v:10,t:2}}}}}});
    const ws=book.getActiveSheet();ws.getRange('A4').setValue(12);
    const first=serializeWorkbook(book);
    const rowId=first.sheets.s.rowData[3].custom.rowId;
    assert.match(rowId,/^[a-f0-9]{32}$/);
    assert.equal(serializeWorkbook(book).sheets.s.rowData[3].custom.rowId,rowId);
    book.undo();assert.equal(ws.getRange('A4').getValue(),10);
    serializeWorkbook(book);
    book.redo();assert.equal(ws.getRange('A4').getValue(),12);
    assert.equal(serializeWorkbook(book).sheets.s.rowData[3].custom.rowId,rowId);
  }finally{univer.dispose();}
});

test('inserted row copies relative/absolute formulas and is undone in one step',async()=>{
  const {univer,univerAPI:api}=createUniver({locale:LocaleType.EN_US,
    locales:{[LocaleType.EN_US]:locale.default??locale},presets:[UniverSheetsNodeCorePreset()]});
  try{
    const book=api.createWorkbook({id:'rows',name:'Rows',sheetOrder:['s'],sheets:{s:{id:'s',name:'Data',
      rowCount:20,columnCount:5,cellData:{0:{0:{v:2}},3:{0:{v:10},1:{f:'=$A$1+A4'}},4:{0:{v:99},1:{f:'=$A$1+A5'}}}}}});
    const ws=book.getActiveSheet();serializeWorkbook(book);
    const before=book.save();
    assert.ok(await insertRowFromTemplate(api,book,ws,3,univer.__getInjector().get(SheetInterceptorService),
      {insert:InsertRowCommand.id,values:SetRangeValuesMutation.id,rows:SetRowDataMutation.id}));
    assert.equal(ws.getRange('B5').getFormulas()[0][0],'=$A$1+A5');
    assert.equal(ws.getRange('B6').getFormulas()[0][0],'=$A$1+A6');
    assert.equal(ws.getRange('A6').getValue(),99);
    assert.equal(ws.getRange('A5').getValue(),null);
    const insertedId=serializeWorkbook(book).sheets.s.rowData[4].custom.rowId;
    book.undo();
    assert.equal(ws.getRange('A5').getValue(),99);
    assert.equal(ws.getRange('B5').getFormulas()[0][0],'=$A$1+A5');
    assert.equal(book.save().sheets.s.rowCount,before.sheets.s.rowCount);
    serializeWorkbook(book);
    book.redo();
    assert.equal(ws.getRange('A6').getValue(),99);
    assert.equal(ws.getRange('B5').getFormulas()[0][0],'=$A$1+A5');
    assert.equal(serializeWorkbook(book).sheets.s.rowData[4].custom.rowId,insertedId);
  }finally{univer.dispose();}
});

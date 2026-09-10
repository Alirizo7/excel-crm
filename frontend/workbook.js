import { createUniver, LocaleType } from '@univerjs/presets';
import { UniverSheetsCorePreset, SetRangeValuesMutation, InsertRowCommand, RemoveRowCommand,
  InsertColCommand, RemoveColCommand, MoveRowsCommand, MoveColsCommand } from '@univerjs/preset-sheets-core';
import ru from '@univerjs/preset-sheets-core/locales/ru-RU';
import '@univerjs/preset-sheets-core/lib/index.css';

const root = document.getElementById('workbook-app');
const ui = JSON.parse(document.getElementById('workbook-messages').textContent);
const $ = id => document.getElementById('wb-' + id);
const readonly = root.dataset.readonly === 'true';
const canFormulas = root.dataset.formulas === 'true';
const token = root.querySelector('[name=csrfmiddlewaretoken]').value;
const bareRange = /^=(?:(?:'[^']+'|[\p{L}\p{N}_ ]+)!)?\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+$/u;
const errorValues = new Set(['#REF!', '#VALUE!', '#DIV/0!', '#NAME?', '#N/A', '#NUM!', '#NULL!', '#SPILL!', '#CYCLE!']);
let api, book, revision, appliedRevision, timer, popupTimer, ready = false, internal = false;
let dirty = false, saving = null, sequence = 0, blocked = false, editActive = false;
const masked = new Map();
const colName = c => { let s = ''; for (c++; c; c=Math.floor((c-1)/26)) s=String.fromCharCode(65+(c-1)%26)+s; return s; };
function message(text) { $('message').textContent=text; $('message').hidden=false; clearTimeout(popupTimer); popupTimer=setTimeout(()=>$('message').hidden=true,7000); }
function status(text, state='saved') { $('status').textContent=text; $('status').parentElement.dataset.state=state; }
function mode() { return canFormulas && !!$('formula-mode')?.checked; }
function key(sheet,r,c) { return `${sheet.id}:${sheet.rowData?.[r]?.custom?.rowId || r}:${c}`; }
function active() { const ws=book.getActiveSheet(), a=ws.getSelection()?.getCurrentCell(); return {ws,r:a?.actualRow ?? 0,c:a?.actualColumn ?? 0}; }
function navigate(ws,range) {
  const row=range.getRow(), col=range.getColumn();
  if(ws.getSheet().getSnapshot().rowData?.[row]?.hd)ws.showRows(row,1);
  range.activate();ws.scrollToCell(row,col);
}
function originalFormula(sheet,r,c,cell) { return cell?.f === '=NA()' && masked.has(key(sheet,r,c)) ? masked.get(key(sheet,r,c)) : cell?.f; }
function serialize() {
  const data=book.save();
  for (const sid of data.sheetOrder) {
    const sheet=data.sheets[sid], ws=book.getSheetBySheetId(sid);
    for (const [r,row] of Object.entries(sheet.cellData || {})) {
      sheet.rowData ??= {}; sheet.rowData[r] ??= {}; sheet.rowData[r].custom ??= {};
      sheet.rowData[r].custom.rowId ??= crypto.randomUUID().replaceAll('-','');
      for (const [c,cell] of Object.entries(row)) {
        if (!cell) continue;
        if (cell.si) { const f=ws.getRange(+r,+c).getFormulas()[0][0]; if(f)cell.f=f; delete cell.si; }
        if(cell.f) cell.f=originalFormula(sheet,r,c,cell).replace(/^=\+/, '=');
      }
    }
    // Persist generated row IDs into the in-memory workbook as well.
    ws.setRowCustom(Object.fromEntries(Object.entries(sheet.rowData).map(([r,d])=>[r,d.custom])));
  }
  return data;
}
function syncBar() {
  if(!ready || document.activeElement===$('cell') || document.activeElement===$('address')) return;
  const {ws,r,c}=active(), sheet=ws.getSheet().getSnapshot(), cell=sheet.cellData?.[r]?.[c];
  const f=originalFormula(sheet,r,c,cell);
  $('address').value=colName(c)+(r+1);
  $('cell').value=f || (cell?.v ?? cell?.p?.body?.dataStream?.replace(/[\r\n]+$/,'') ?? '');
  $('cell').disabled=readonly || (!!f && !mode());
  $('cell-apply').disabled=$('cell').disabled;
  $('cell-kind').textContent=f? ui.formula : ui.value;
}
function showErrors(errors) {
  $('error-count').textContent=errors.length;
  const list=$('errors-list'); list.replaceChildren();
  if(!errors.length) { const li=document.createElement('li');li.textContent=ui.noErrors;list.append(li); }
  for(const error of errors) {
    const li=document.createElement('li'), button=document.createElement('button');
    button.textContent=`${error.sheet}!${error.cell} · ${error.error}`;
    button.addEventListener('click',()=>{ const ws=book.getSheetByName(error.sheet);ws.activate();navigate(ws,ws.getRange(error.cell));syncBar(); });
    li.append(button); if(error.legacy){const note=document.createElement('small');note.textContent=ui.legacyRange;li.append(note);} list.append(li);
  }
}
function browserErrors() {
  if(!ready)return;
  const data=book.save(), errors=[];
  for(const sheet of Object.values(data.sheets)) for(const [r,row] of Object.entries(sheet.cellData || {})) for(const [c,cell] of Object.entries(row)) {
    if(cell && (cell.f||cell.si) && errorValues.has(cell.v)) errors.push({sheet:sheet.name,cell:colName(+c)+(+r+1),error:cell.v,legacy:masked.has(key(sheet,r,c))});
  }
  showErrors(errors);
}
function markDirty() { if(!ready || internal || readonly)return; dirty=true;sequence++;status(ui.dirty,'dirty');$('recovery').hidden=false;clearTimeout(timer);timer=setTimeout(()=>save(),1800);syncBar(); }
async function save() {
  clearTimeout(timer);
  if(readonly || blocked || !ready)return !dirty;
  if(editActive) { timer=setTimeout(()=>save(),1000);return false; }
  if(saving){ await saving; if(dirty&&!blocked)return save(); return !dirty; }
  if(!dirty)return true;
  const at=sequence;
  saving=(async()=>{
    status(ui.saving,'saving');
    try {
      internal=true; const data=serialize();internal=false;
      const response=await fetch(root.dataset.save,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({revision,data})});
      const result=await response.json();
      if(!response.ok){ if(response.status===409)blocked=true;throw new Error(result.error || ui.failed); }
      revision=result.revision;appliedRevision=result.applied_revision;$('revision').textContent=revision;
      dirty=sequence!==at;showErrors(result.errors);$('stage').textContent=revision===appliedRevision?ui.applied:ui.draft;
      status(dirty?ui.dirty:ui.ready,dirty?'dirty':'saved');$('recovery').hidden=!dirty;
    } catch(error){ internal=false;status(blocked?ui.conflict:ui.failed,'error');message(error.message);$('recovery').hidden=false; }
  })();
  await saving;saving=null;
  if(dirty&&!blocked&&sequence!==at)timer=setTimeout(()=>save(),1000);
  return !dirty;
}
function downloadBlob(blob,name) { const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000); }
async function init() {
  try {
    const response=await fetch(root.dataset.url,{cache:'no-store'});if(!response.ok)throw new Error(ui.loadFail);
    const state=await response.json();revision=state.revision;appliedRevision=state.applied_revision;
    for(const sheet of Object.values(state.data.sheets)) for(const [r,row] of Object.entries(sheet.cellData||{})) for(const [c,cell] of Object.entries(row)) {
      if(cell?.f && bareRange.test(cell.f)) { masked.set(key(sheet,r,c),cell.f);cell.f='=NA()'; }
    }
    const {univerAPI}=createUniver({locale:LocaleType.RU_RU,locales:{[LocaleType.RU_RU]:ru},presets:[UniverSheetsCorePreset({container:'univer-container',header:false,toolbar:false,contextMenu:false,formulaBar:false,footer:false,disableAutoFocus:true,formula:{initialFormulaComputing:0}})]});
    api=univerAPI;book=api.createWorkbook(state.data);
    // Keep the worksheet names intact and offer a compact, localized sheet selector.
    const select=document.createElement('select');select.id='wb-sheet';select.setAttribute('aria-label',ui.sheet);
    for(const ws of book.getSheets()){const option=document.createElement('option');option.value=ws.getSheetId();option.textContent=ws.getSheetName();select.append(option);}
    $('address-form').before(select);select.addEventListener('change',()=>{book.getSheetBySheetId(select.value).activate();syncBar();});
    const noStructure=[InsertRowCommand.id,RemoveRowCommand.id,InsertColCommand.id,RemoveColCommand.id,MoveRowsCommand.id,MoveColsCommand.id];
    api.addEvent(api.Event.BeforeCommandExecute,event=>{
      if(!ready || internal || event.options?.applyFormulaCalculationResult)return;
      if(noStructure.includes(event.id)){event.cancel=true;message(ui.structure);return;}
      if(event.id!==SetRangeValuesMutation.id)return;
      const ws=book.getSheetBySheetId(event.params.subUnitId);
      for(const [r,row] of Object.entries(event.params.cellValue || {})) for(const [c,value] of Object.entries(row || {})) {
        const contentChanged=value===null || ['f','v','p','si'].some(k=>Object.hasOwn(value,k));
        if(!contentChanged)continue;
        const existing=ws.getRange(+r,+c).getCellData();
        if(readonly || !mode() && (existing?.f || existing?.si || value?.f || value?.si || typeof value?.v==='string'&&value.v.startsWith('='))) {
          event.cancel=true;message(readonly?ui.readOnly:ui.locked);return;
        }
        if(value?.f && bareRange.test(value.f)){event.cancel=true;message(ui.legacyRange);return;}
      }
    });
    for(const event of ['BeforeSheetCreate','BeforeSheetDelete','BeforeSheetMove','BeforeSheetNameChange','BeforeSheetHideChange'])api.addEvent(api.Event[event],e=>{if(ready){e.cancel=true;message(ui.structure);}});
    api.addEvent(api.Event.BeforeSheetEditStart,e=>{const cell=e.worksheet.getRange(e.row,e.column).getCellData();if(readonly||!mode()&&(cell?.f||cell?.si)){e.cancel=true;message(readonly?ui.readOnly:ui.locked);}});
    api.addEvent(api.Event.SheetEditStarted,()=>editActive=true);
    api.addEvent(api.Event.SheetEditEnded,()=>{editActive=false;syncBar();});
    api.addEvent(api.Event.CommandExecuted,e=>{if(e.id===SetRangeValuesMutation.id && !e.options?.applyFormulaCalculationResult)markDirty();});
    api.addEvent(api.Event.SelectionChanged,()=>{syncBar();$('sheet').value=book.getActiveSheet().getSheetId();});
    api.addEvent(api.Event.SheetValueChanged,()=>{syncBar();});
    await api.getFormula().onCalculationResultApplied(20000);
    ready=true;$('loading').hidden=true;showErrors(state.errors);
    status(readonly?ui.readOnly:ui.ready);$('stage').textContent=readonly?ui.readOnly:revision===appliedRevision?ui.applied:ui.draft;
    for(const id of ['download','find-button','errors-toggle'])$(id).disabled=false;
    if(!readonly)for(const id of ['save','undo','redo','preview','add-row'])if($(id))$(id).disabled=false;
    syncBar();
    $('save').addEventListener('click',()=>save());
    $('formula-mode')?.addEventListener('change',()=>{syncBar();if(mode())message(ui.newFormulaMode);});
    $('undo').addEventListener('click',async()=>{internal=true;try{await api.undo();}finally{internal=false;}markDirty();});
    $('redo').addEventListener('click',async()=>{internal=true;try{await api.redo();}finally{internal=false;}markDirty();});
    $('preview')?.addEventListener('click',async()=>{if(await save())location.href=root.dataset.preview;});
    $('download').addEventListener('click',async()=>{if(await save())location.href=root.dataset.download+(readonly&&new URLSearchParams(root.dataset.url.split('?')[1]).has('version')?'?version='+new URLSearchParams(root.dataset.url.split('?')[1]).get('version'):'');});
    $('recovery').addEventListener('click',()=>{internal=true;try{downloadBlob(new Blob([JSON.stringify({revision,data:serialize()})],{type:'application/json'}),`metalflow-recovery-v${revision}.json`);}finally{internal=false;}});
    $('errors-toggle').addEventListener('click',()=>{$('errors').hidden=!$('errors').hidden;browserErrors();});$('errors-close').addEventListener('click',()=>$('errors').hidden=true);
    $('address-form').addEventListener('submit',e=>{e.preventDefault();const value=$('address').value.toUpperCase();if(!/^[A-Z]{1,2}[1-9]\d{0,4}$/.test(value))return;try{const ws=book.getActiveSheet(),range=ws.getRange(value);const pos=range.getRange();if(pos.startRow>=12000||pos.startColumn>=64)return;navigate(ws,range);$('address').blur();syncBar();}catch{message(ui.selectRow);}});
    $('cell-form').addEventListener('submit',e=>{e.preventDefault();if($('cell').disabled)return;const {ws,r,c}=active(),value=$('cell').value; if(value.startsWith('=')&&(!mode()||bareRange.test(value))){message(!mode()?ui.locked:ui.legacyRange);return;}masked.delete(key(ws.getSheet().getSnapshot(),r,c));ws.getRange(r,c).setValue(value);$('cell').blur();syncBar();});
    $('add-row')?.addEventListener('click',async()=>{
      const {ws,r}=active();if(r<3||r>=11998){message(ui.selectRow);return;}
      internal=true;
      try {
        const sheet=ws.getSheet().getSnapshot(),cols=sheet.columnCount,values={};
        const formulas=ws.getRange(r,0,1,cols).getFormulas()[0];
        for(let c=0;c<cols;c++) {
          const source=sheet.cellData?.[r]?.[c];values[c]={};
          if(source?.s)values[c].s=source.s;
          if(source?.f || formulas[c])values[c].f=api.getFormula().moveFormulaRefOffset(source?.f || formulas[c],0,1);
        }
        const inserted=await api.executeCommand(InsertRowCommand.id,{unitId:book.getId(),subUnitId:ws.getSheetId(),direction:api.Enum.Direction.DOWN,
          range:{startRow:r+1,endRow:r+1,startColumn:0,endColumn:cols-1},cellValue:{[r+1]:values}});
        if(!inserted)throw new Error(ui.failed);
        const target=ws.getRange(r+1,0,1,cols);
        target.setValues([Array.from({length:cols},(_,c)=>values[c])]);
        ws.setRowCustomMetadata(r+1,{rowId:crypto.randomUUID().replaceAll('-','')});
        navigate(ws,target);message(ui.rowAdded);
      } catch(error){message(error.message || ui.failed);} finally{internal=false;markDirty();}
    });
    let lastFind='',findIndex=-1;
    $('find-form').addEventListener('submit',e=>{
      e.preventDefault();const needle=$('find').value.trim().toLocaleLowerCase();if(!needle)return;
      const matches=[],data=book.save();
      for(const sheet of Object.values(data.sheets))for(const [r,row] of Object.entries(sheet.cellData||{}))for(const [c,cell] of Object.entries(row))if(cell&&String(cell.f||cell.v||cell.p?.body?.dataStream||'').toLocaleLowerCase().includes(needle))matches.push({sid:sheet.id,r:+r,c:+c});
      if(!matches.length){message(ui.notFound);return;}findIndex=lastFind===needle?(findIndex+1)%matches.length:0;lastFind=needle;const hit=matches[findIndex],ws=book.getSheetBySheetId(hit.sid);ws.activate();const range=ws.getRange(hit.r,hit.c);navigate(ws,range);$('sheet').value=hit.sid;syncBar();message(`${findIndex+1} / ${matches.length}`);
    });
    setInterval(()=>{if(ready&&!editActive){syncBar();}},1200);
    window.addEventListener('beforeunload',e=>{if(dirty||editActive){e.preventDefault();e.returnValue='';}});
    document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save();}});
  } catch(error){$('loading').replaceChildren();const text=document.createElement('strong');text.textContent=ui.loadFail;$('loading').append(text);status(ui.loadFail,'error');console.error(error);}
}
init();

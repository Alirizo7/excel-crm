import { createUniver, LocaleType, CellValueType } from '@univerjs/presets';
import { UniverSheetsCorePreset, SetRangeValuesMutation, InsertRowCommand, RemoveRowCommand,
  InsertColCommand, RemoveColCommand, MoveRowsCommand, MoveColsCommand, SheetPasteShortKeyCommand,
  SheetInterceptorService, AFTER_CELL_EDIT, SetRowDataMutation } from '@univerjs/preset-sheets-core';
import { parseInputNumber, normalizePlainPaste } from './workbook-input.js';
import { serializeWorkbook, insertRowFromTemplate } from './workbook-state.js';
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
let finishing = false, committingEdit = false, cellInputDirty = false, cellDraftTarget = null;
const masked = new Map();
const colName = c => { let s = ''; for (c++; c; c=Math.floor((c-1)/26)) s=String.fromCharCode(65+(c-1)%26)+s; return s; };
function message(text) { $('message').textContent=text; $('message').hidden=false; clearTimeout(popupTimer); popupTimer=setTimeout(()=>$('message').hidden=true,7000); }
function status(text, state='saved') { $('status').textContent=text; $('status').parentElement.dataset.state=state; }
function showSavedState() {
  const pending=dirty || revision!==appliedRevision;
  status(readonly?ui.readOnly:pending?ui.draft:ui.ready,pending?'dirty':'saved');
  $('stage').textContent=pending?ui.draft:ui.applied;
}
function mode() { return canFormulas && !!$('formula-mode')?.checked; }
function key(sheet,r,c) { return `${sheet.id}:${sheet.rowData?.[r]?.custom?.rowId || r}:${c}`; }
function active() { const ws=book.getActiveSheet(), a=ws.getSelection()?.getCurrentCell(); return {ws,r:a?.actualRow ?? 0,c:a?.actualColumn ?? 0}; }
function textCell(ws,r,c) { return ws.getSheet().getCellStyle(r,c)?.n?.pattern === '@'; }
function navigate(ws,range) {
  const row=range.getRow(), col=range.getColumn();
  if(ws.getSheet().getSnapshot().rowData?.[row]?.hd)ws.showRows(row,1);
  range.activate();ws.scrollToCell(row,col);
}
function originalFormula(sheet,r,c,cell) { return cell?.f === '=NA()' && masked.has(key(sheet,r,c)) ? masked.get(key(sheet,r,c)) : cell?.f; }
function serialize() {
  return serializeWorkbook(book,originalFormula);
}
function syncBar() {
  if(!ready || cellInputDirty || document.activeElement===$('cell') || document.activeElement===$('address')) return;
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
  $('errors-toggle').hidden=errors.length===0;
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
function markDirty() { if(!ready || internal || readonly)return; dirty=true;sequence++;status(ui.dirty,'dirty');clearTimeout(timer);timer=setTimeout(()=>save(),1800);syncBar(); }
async function save() {
  clearTimeout(timer);
  if(readonly || blocked || !ready)return !dirty;
  if(editActive) { timer=setTimeout(()=>save(),1000);return false; }
  if(saving){ await saving; if(dirty&&!blocked)return save(); return !dirty; }
  if(!dirty)return true;
  const at=sequence;
  saving=(async()=>{
    if(!finishing)status(ui.saving,'saving');
    try {
      internal=true; const data=serialize();internal=false;
      const response=await fetch(root.dataset.save,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({revision,data})});
      const result=await response.json();
      if(!response.ok){ if(response.status===409)blocked=true;throw new Error(result.error || ui.failed); }
      revision=result.revision;appliedRevision=result.applied_revision;$('revision').textContent=revision;
      dirty=sequence!==at;showErrors(result.errors);$('stage').textContent=revision===appliedRevision?ui.applied:ui.draft;
      if(!finishing)showSavedState();$('recovery').hidden=true;
    } catch(error){ internal=false;status(blocked?ui.conflict:ui.failed,'error');message(error.message);$('recovery').hidden=false; }
  })();
  await saving;saving=null;
  if(dirty&&!blocked&&sequence!==at)timer=setTimeout(()=>save(),1000);
  return !dirty;
}
function confirmRemovals(removals) {
  const dialog=$('removal-dialog'),list=$('removals');list.replaceChildren();
  for(const item of removals){const li=document.createElement('li');li.textContent=`${item.sheet} / ${item.row}`;list.append(li);}
  return new Promise(resolve=>{
    dialog.returnValue='cancel';
    $('removal-cancel').onclick=()=>dialog.close('cancel');
    $('removal-confirm').onclick=()=>dialog.close('confirm');
    dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});
    dialog.showModal();$('removal-cancel').focus();
  });
}
function showFeedback(result) {
  $('feedback').hidden=false;$('feedback-title').textContent=result.error || ui.finishError;
  $('feedback-issues').replaceChildren();
  for(const issue of result.issues || []){const li=document.createElement('li');li.textContent=issue;$('feedback-issues').append(li);}
  $('feedback-link').hidden=!result.details_url;
  if(result.details_url)$('feedback-link').href=result.details_url;
  status(ui.finishError,'error');
}
async function finish() {
  if(finishing || readonly || !ready || blocked)return;
  if(cellInputDirty)$('cell-form').requestSubmit();
  if(cellInputDirty)return;
  finishing=true;root.setAttribute('aria-busy','true');$('save').disabled=true;$('save').textContent=ui.finishing;
  $('feedback').hidden=true;
  try {
    if(editActive){
      committingEdit=true;
      try{if(!await book.endEditingAsync(true))return;}finally{committingEdit=false;}
      editActive=false;markDirty();
    }
    root.querySelectorAll('.wb-toolbar,.wb-formula-line,.wb-grid-wrap').forEach(el=>el.inert=true);
    if(!await save())return;
    status(ui.finishing,'saving');
    const send=async confirmation_token=>{
      const response=await fetch(root.dataset.finish,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({revision,confirmation_token})});
      if(response.redirected)throw new Error(ui.finishError);
      const result=await response.json();
      if(!response.ok){showFeedback(result);return null;}return result;
    };
    let result=await send();if(!result)return;
    if(result.confirmation_required){
      if(!await confirmRemovals(result.removals)){showSavedState();return;}
      result=await send(result.token);if(!result)return;
    }
    appliedRevision=result.applied_revision;showSavedState();message(ui.applied);
  }catch(error){showFeedback({error:error.message || ui.finishError});}
  finally{
    finishing=false;root.removeAttribute('aria-busy');$('save').disabled=false;$('save').textContent=ui.saveChanges;
    root.querySelectorAll('.wb-toolbar,.wb-formula-line,.wb-grid-wrap').forEach(el=>el.inert=false);
  }
}
function downloadBlob(blob,name) { const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000); }
async function init() {
  try {
    const response=await fetch(root.dataset.url,{cache:'no-store'});if(!response.ok)throw new Error(ui.loadFail);
    const state=await response.json();revision=state.revision;appliedRevision=state.applied_revision;
    for(const sheet of Object.values(state.data.sheets)) for(const [r,row] of Object.entries(sheet.cellData||{})) for(const [c,cell] of Object.entries(row)) {
      if(cell?.f && bareRange.test(cell.f)) { masked.set(key(sheet,r,c),cell.f);cell.f='=NA()'; }
    }
    const {univer,univerAPI}=createUniver({locale:LocaleType.RU_RU,locales:{[LocaleType.RU_RU]:ru},presets:[UniverSheetsCorePreset({container:'univer-container',header:false,toolbar:false,contextMenu:false,formulaBar:false,footer:false,disableAutoFocus:true,formula:{initialFormulaComputing:0}})]});
    api=univerAPI;book=api.createWorkbook(state.data);book.setNumfmtLocal('ru');
    // Normalize raw grid edits before Univer's US number-format interceptor:
    // otherwise 1,234 becomes 1234 before the value mutation can inspect it.
    const sheetInterceptors=univer.__getInjector().get(SheetInterceptorService);
    sheetInterceptors.writeCellInterceptor.intercept(AFTER_CELL_EDIT,{
      priority:100,
      handler:(value,context,next)=>{
        if(value && !value.f && !value.p && value.t!==CellValueType.FORCE_STRING && context.worksheet.getCellStyle(context.row,context.col)?.n?.pattern!=='@'){
          const number=parseInputNumber(value.v);
          if(number!==null){
            const percent=String(value.v).trim().endsWith('%');
            value={...value,v:percent?String(value.v).trim().replace(/[ \u00a0\u202f]/g,'').replace(',','.'):number};
            if(!percent)value.t=CellValueType.NUMBER;
          }
        }
        return next(value);
      }
    });
    // Keep the worksheet names intact and offer a compact, localized sheet selector.
    const select=document.createElement('select');select.id='wb-sheet';select.setAttribute('aria-label',ui.sheet);
    for(const ws of book.getSheets()){const option=document.createElement('option');option.value=ws.getSheetId();option.textContent=ws.getSheetName();select.append(option);}
    $('address-form').before(select);select.addEventListener('change',()=>{book.getSheetBySheetId(select.value).activate();syncBar();});
    const noStructure=[InsertRowCommand.id,RemoveRowCommand.id,InsertColCommand.id,RemoveColCommand.id,MoveRowsCommand.id,MoveColsCommand.id];
    api.addEvent(api.Event.BeforeCommandExecute,event=>{
      if(!ready || internal || event.options?.applyFormulaCalculationResult)return;
      if(noStructure.includes(event.id)){event.cancel=true;message(ui.structure);return;}
      if(event.id===SheetPasteShortKeyCommand.id && !event.params.htmlContent && event.params.textContent){
        const {ws,r,c}=active();
        event.params.textContent=normalizePlainPaste(event.params.textContent,(row,col)=>textCell(ws,r+row,c+col));
      }
      if(event.id!==SetRangeValuesMutation.id)return;
      if(finishing && !committingEdit){event.cancel=true;return;}
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
    showSavedState();
    for(const id of ['download','find-button','errors-toggle'])$(id).disabled=false;
    if(!readonly)for(const id of ['save','undo','redo','preview','add-row'])if($(id))$(id).disabled=false;
    syncBar();
    $('save')?.addEventListener('click',()=>finish());
    $('formula-mode')?.addEventListener('change',()=>{syncBar();if(mode())message(ui.newFormulaMode);});
    $('undo').addEventListener('click',()=>{internal=true;try{book.undo();}finally{internal=false;}markDirty();});
    $('redo').addEventListener('click',()=>{internal=true;try{book.redo();}finally{internal=false;}markDirty();});
    $('download').addEventListener('click',async()=>{if(cellInputDirty)$('cell-form').requestSubmit();if(!cellInputDirty && await save())location.href=root.dataset.download+(readonly&&new URLSearchParams(root.dataset.url.split('?')[1]).has('version')?'?version='+new URLSearchParams(root.dataset.url.split('?')[1]).get('version'):'');});
    $('recovery').addEventListener('click',()=>{internal=true;try{downloadBlob(new Blob([JSON.stringify({revision,data:serialize()})],{type:'application/json'}),`metalflow-recovery-v${revision}.json`);}finally{internal=false;}});
    $('errors-toggle').addEventListener('click',()=>{$('errors').hidden=!$('errors').hidden;browserErrors();});$('errors-close').addEventListener('click',()=>$('errors').hidden=true);
    $('address-form').addEventListener('submit',e=>{e.preventDefault();const value=$('address').value.toUpperCase();if(!/^[A-Z]{1,2}[1-9]\d{0,4}$/.test(value))return;try{const ws=book.getActiveSheet(),range=ws.getRange(value);const pos=range.getRange();if(pos.startRow>=12000||pos.startColumn>=64)return;navigate(ws,range);$('address').blur();syncBar();}catch{message(ui.selectRow);}});
    $('cell').addEventListener('input',()=>{cellDraftTarget ??= active();cellInputDirty=true;});
    $('cell').addEventListener('change',()=>{if(cellInputDirty)$('cell-form').requestSubmit();});
    $('cell-form').addEventListener('submit',e=>{
      e.preventDefault();if($('cell').disabled)return;
      const {ws,r,c}=cellDraftTarget || active(),value=$('cell').value;
      if(value.startsWith('=')&&(!mode()||bareRange.test(value))){message(!mode()?ui.locked:ui.legacyRange);return;}
      masked.delete(key(ws.getSheet().getSnapshot(),r,c));
      const range=ws.getRange(r,c);
      if(value==='')range.clearContent();
      else if(value.startsWith("'"))range.setValue({v:value.slice(1),t:CellValueType.FORCE_STRING,f:null,p:null});
      else if(textCell(ws,r,c))range.setValue({v:value,t:CellValueType.FORCE_STRING,f:null,p:null});
      else {
        const number=parseInputNumber(value);
        range.setValue(number===null?value:{v:number,t:CellValueType.NUMBER,f:null,p:null,
          ...(value.trim().endsWith('%')?{s:{n:{pattern:'0.00%'}}}:{})});
      }
      cellInputDirty=false;cellDraftTarget=null;$('cell').blur();syncBar();
    });
    $('add-row')?.addEventListener('click',async()=>{
      const {ws,r}=active();if(r<3||r>=11998){message(ui.selectRow);return;}
      internal=true;
      try {
        const target=await insertRowFromTemplate(api,book,ws,r,sheetInterceptors,
          {insert:InsertRowCommand.id,values:SetRangeValuesMutation.id,rows:SetRowDataMutation.id});
        if(!target)throw new Error(ui.failed);
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
    window.addEventListener('beforeunload',e=>{if(dirty||editActive||cellInputDirty||finishing){e.preventDefault();e.returnValue='';}});
    document.addEventListener('click',async e=>{
      const link=e.target.closest('a[href]');if(!link || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || link.target==='_blank')return;
      const url=new URL(link.href);if(url.origin!==location.origin || link.getAttribute('href').startsWith('#') || /\/(download|source)\/$/.test(url.pathname))return;
      if(finishing){e.preventDefault();return;}
      if(dirty || cellInputDirty){e.preventDefault();if(cellInputDirty)$('cell-form').requestSubmit();if(!cellInputDirty && await save())location.href=url.href;}
    });
    document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();finish();}});
  } catch(error){$('loading').replaceChildren();const text=document.createElement('strong');text.textContent=ui.loadFail;$('loading').append(text);status(ui.loadFail,'error');console.error(error);}
}
init();

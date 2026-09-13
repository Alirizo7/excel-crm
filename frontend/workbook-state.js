export function serializeWorkbook(book, originalFormula = (sheet,r,c,cell) => cell.f) {
  const data=book.save();
  for(const sid of data.sheetOrder){
    const sheet=data.sheets[sid], ws=book.getSheetBySheetId(sid);
    for(const [r,row] of Object.entries(sheet.cellData || {})){
      sheet.rowData ??= {}; sheet.rowData[r] ??= {}; sheet.rowData[r].custom ??= {};
      if(!sheet.rowData[r].custom.rowId){
        sheet.rowData[r].custom.rowId=crypto.randomUUID().replaceAll('-','');
        // Metadata must not add an undo action or clear redo during autosave.
        ws.getSheet().getRowManager().getRowOrCreate(+r);
        ws.setRowCustomMetadata(+r,sheet.rowData[r].custom);
      }
      for(const [c,cell] of Object.entries(row)){
        if(!cell)continue;
        if(cell.si){const f=ws.getRange(+r,+c).getFormulas()[0][0];if(f)cell.f=f;delete cell.si;}
        if(cell.f)cell.f=originalFormula(sheet,r,c,cell).replace(/^=\+/, '=');
      }
    }
  }
  return data;
}

export async function insertRowFromTemplate(api,book,ws,r,interceptors,commands){
  const sheet=ws.getSheet().getSnapshot(),cols=sheet.columnCount,values={};
  const formulas=ws.getRange(r,0,1,cols).getFormulas()[0];
  for(let c=0;c<cols;c++){
    const source=sheet.cellData?.[r]?.[c];values[c]={};
    if(source?.s)values[c].s=source.s;
    if(source?.f || formulas[c])values[c].f=api.getFormula().moveFormulaRefOffset(source?.f || formulas[c],0,1);
  }
  const target={unitId:book.getId(),subUnitId:ws.getSheetId()};
  const cellValue={[r+1]:values},rowId=crypto.randomUUID().replaceAll('-','');
  // Formula reference updates can clear the inserted cells. Fill the template
  // afterwards, within the insertion's own undo action, including its stable ID.
  const hook=interceptors.interceptAfterCommand({getMutations:({id,params})=>
    id===commands.insert && params.cellValue===cellValue ? {redos:[
      {id:commands.values,params:{...target,cellValue}},
      {id:commands.rows,params:{...target,rowData:{[r+1]:{custom:{rowId}}}}}
    ],undos:[]} : {redos:[],undos:[]}});
  try{
    const inserted=await api.executeCommand(commands.insert,{...target,direction:api.Enum.Direction.DOWN,
      range:{startRow:r+1,endRow:r+1,startColumn:0,endColumn:cols-1},cellValue});
    return inserted?ws.getRange(r+1,0,1,cols):null;
  }finally{hook.dispose();}
}

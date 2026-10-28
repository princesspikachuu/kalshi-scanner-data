const fields={pnl:'average_profit_loss_cents_per_contract',roi:'hypothetical_roi_percent',win:'win_rate_percent'};
export function tableModel(report,{loss=false,metric='pnl',minimum=1}={}){
 if(!Object.hasOwn(fields,metric)||!Number.isInteger(minimum)||minimum<1)throw Error('Invalid display choice');
 const cells=new Map(report.cells.map(cell=>[cell.hold.minutes_before_close+'|'+cell.hold.price_band_cents,cell]));
 return report.entry_minutes.map(minutes=>({minutes,cells:report.price_bands.map(band=>{
  const cell=cells.get(minutes+'|'+band);if(!cell)return {band,empty:true};
  const value=(loss?cell.loss_prevention:cell.hold)[fields[metric]];
  const n=cell.hold.sampled_markets,hidden=n<minimum;
  return {band,empty:false,n,hidden,value,label:loss?cell.loss_prevention.sell_label:null,
   text:hidden?'Below display minimum':Number.isFinite(value)?value.toFixed(2)+(metric==='pnl'?'¢':'%'):'—',
   tone:hidden?'small':metric==='win'?'neutral':value>0?'positive':value<0?'negative':'neutral',cell};
 })}));
}
export function renderTable(container,report,options,onSelect){
 const doc=container.ownerDocument;
 const el=(tag,text)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;return n};
 const table=el('table');table.className='heatmap';table.setAttribute('aria-label','Saved research by entry time and purchase price');
 const head=el('thead'),tr=el('tr');tr.append(el('th','Before close'));
 for(const band of report.price_bands)tr.append(el('th',band+'¢'));head.append(tr);table.append(head);
 const body=el('tbody');
 for(const row of tableModel(report,options)){
  const tr=el('tr'),th=el('th',row.minutes+' min');th.setAttribute('scope','row');tr.append(th);
  for(const model of row.cells){
   const td=el('td');
   if(model.empty){td.append(el('span','No observations'))}
   else{
    const button=el('button');button.type='button';button.className='heat '+model.tone;
    button.append(el('strong',model.text),el('small','n = '+model.n));
    if(model.label)button.append(el('small',model.label));
    button.addEventListener('click',()=>onSelect(model.cell,row.minutes,model.band));td.append(button);
   }tr.append(td);
  }body.append(tr);
 }table.append(body);container.replaceChildren(table);
}


export function reportCsv(report){
 const header=['report_id','asset','minutes_before_close','price_band_cents','policy','sampled_markets','sampled_days','wins','win_rate_percent','average_purchase_price_cents','average_profit_loss_cents_per_contract','hypothetical_roi_percent','threshold_cents','exit_coverage','early_exits','sell_label','collection_complete','reported_sections','total_sections','sampled_preview','sample_limit'];
 const rows=[header];
 for(const cell of report.cells)for(const policy of ['hold','loss_prevention']){
  const r=cell[policy];rows.push([report.id,r.asset,r.minutes_before_close,r.price_band_cents,policy,cell.hold.sampled_markets,cell.hold.sampled_days,r.wins,r.win_rate_percent,r.average_purchase_price_cents,r.average_profit_loss_cents_per_contract,r.hypothetical_roi_percent,r.threshold_cents??'',r.exit_coverage??'',r.early_exits??'',r.sell_label??'',report.collection_complete!==false,report.reported_sections??'',report.total_sections??'',report.sampled_preview===true,report.sample_limit??'']);
 }
 return rows.map(row=>row.map(value=>'"'+String(value).replaceAll('"','""')+'"').join(',')).join('\r\n')+'\r\n';
}

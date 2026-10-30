import {createResearchClient} from './research-client.mjs';
import {createCollectionClient} from './collection-client.mjs';

const minutes={btc:[15,10,5,3,1],eth:[15,10,5,3,1],crypto:[15,10,5,3,1],weather:[60,45,30,20,15,10,5,3,1],weather_daily:[360,180,120,60,30,15,5],sports:[360,180,120,60,30,15,5]};
const bands=['50-60','60-70','70-80','80-90','90-100'];
export const conditionKey=s=>[s.asset,s.min_price,s.max_price,s.min_minutes,s.max_minutes].join(':');

export function offeringRows(asset,report=null){
 if(!Object.hasOwn(minutes,asset))throw Error('Choose a market category.');
 const slots=report?.entry_minutes||minutes[asset],prices=report?.price_bands||bands;
 const lookup=new Map((report?.cells||[]).map(c=>[`${c.hold.minutes_before_close}:${c.hold.price_band_cents}`,c]));
 return slots.map(upper=>({minutes:upper,cells:prices.map(band=>{
  const [low,through]=band.split('-').map(Number),cell=lookup.get(`${upper}:${band}`);
  const available=!!cell?.hold?.sampled_markets;
  const square={asset,min_price:low,max_price:through-1,min_minutes:Math.max(0,...slots.filter(m=>m<upper)),max_minutes:upper,report_id:available?Number(report.id):null,expected_roi:null,loss_cents:null};
  return {band,square,cell:available?cell:null};
 })}));
}
export function toggleOffering(squares,square){
 const key=conditionKey(square),found=squares.findIndex(s=>conditionKey(s)===key);
 if(found>=0)return squares.filter((_,i)=>i!==found);
 if(squares.length>=45)throw Error('A bot can contain up to 45 conditions. Remove one before adding another.');
 return [...squares,square];
}

// One bounded cache per dialog. These are saved-result reads, never collection
// requests, archive downloads, provider requests or repeated polling.
export function createOfferingLoader({research=createResearchClient(),collection=createCollectionClient()}={}){
 const cache=new Map();
 return async function load(asset,{refresh=false}={}){
  if(!Object.hasOwn(minutes,asset))throw Error('Choose a market category.');
  if(refresh)cache.delete(asset);
  if(!cache.has(asset)){
   const pending=(async()=>{
    const category=await research.category(asset);
    if(category)return {report:category,basis:'All saved history'};
    const pages=await Promise.allSettled(['unfinished','finished'].map(group=>collection.list(asset,null,group,10)));
    if(pages.every(p=>p.status==='rejected'))throw pages[0].reason;
    const candidates=pages.filter(p=>p.status==='fulfilled').flatMap(p=>p.value.items).filter(c=>c.result_id||c.sample_result_id).sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
    if(!candidates.length)return {report:null,basis:'No saved statistics yet'};
    const item=candidates[0],sample=!item.result_id;
    const report=sample?await research.sampleResult(item.id,String(item.sample_result_id)):await research.result(item.id,String(item.result_id));
    return {report,basis:sample?'Saved sampled preview':'Latest saved collection'};
   })();
   cache.set(asset,pending);
   pending.catch(()=>{if(cache.get(asset)===pending)cache.delete(asset)});
  }
  return cache.get(asset);
 };
}

export function renderOfferings(container,asset,report,squares,onToggle,{loading=false}={}){
 const doc=container.ownerDocument,element=(tag,text)=>{const node=doc.createElement(tag);if(text!==undefined)node.textContent=text;return node};
 const rows=offeringRows(asset,report),selected=new Set(squares.map(conditionKey));
 const table=element('table');table.className='bot-offerings';table.setAttribute('aria-label','Select bot conditions by price and time before close');
 const head=element('thead'),heading=element('tr');heading.append(element('th','Before close'));
 for(const model of rows[0]?.cells||[])heading.append(element('th',`${model.square.min_price}–${model.square.max_price}¢`));head.append(heading);table.append(head);
 const body=element('tbody');
 for(const row of rows){
  const tr=element('tr'),th=element('th',`${row.minutes} min`);th.setAttribute('scope','row');tr.append(th);
  for(const model of row.cells){
   const td=element('td'),button=element('button'),square=model.square;
   const chosen=selected.has(conditionKey(square)),hold=model.cell?.hold,loss=model.cell?.loss_prevention;
   button.type='button';button.disabled=loading;button.className='bot-offering'+(chosen?' selected':'');
   button.setAttribute('aria-pressed',String(chosen));button.setAttribute('aria-label',`${square.min_price} to ${square.max_price} cents, ${square.min_minutes} to ${square.max_minutes} minutes before close, ${chosen?'selected':'not selected'}`);
   if(hold){
    const roi=hold.hypothetical_roi_percent;
    button.append(element('strong',`${roi.toFixed(2)}% ROI`),element('small',`${hold.win_rate_percent.toFixed(1)}% wins · n=${hold.sampled_markets}`),element('small',loss?.sell_label||'Sell: —'));
   }else button.append(element('strong','— ROI'),element('small','No saved observations'),element('small','Select as manual condition'));
   button.addEventListener('click',()=>onToggle(square));td.append(button);tr.append(td);
  }
  body.append(tr);
 }
 table.append(body);container.replaceChildren(table);
}

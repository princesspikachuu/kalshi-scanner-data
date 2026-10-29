import {paperCall} from './paper-client.mjs';
const $=id=>document.getElementById(id);let workspace,busy=false,requestKey=null;
const checked=id=>[...$(id).querySelectorAll('input:checked')].map(e=>e.value);
function options(id,items){const selected=new Set(checked(id));$(id).replaceChildren(...items.map(item=>{const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.value=item.id;input.checked=selected.has(String(item.id));const span=document.createElement('span');span.textContent=item.label;label.append(input,span);return label}));if(!items.length)$(id).textContent=id==='strategies'?'No table-based strategies saved. Choose New bet on the statistics table.':'No analyzed trade datasets yet. They will appear as analysis finishes.';}
function money(cents){return '$'+(cents/100).toFixed(2)}
async function load(){try{
 workspace=await paperCall('workspace');
 options('strategies',workspace.strategies.filter(s=>s.strategy.bid_offset==null).map(s=>({id:s.id,label:`${s.strategy.name} · ${s.asset} · saved yield ${s.strategy.statistical_yield_percent.toFixed(2)}% · n=${s.strategy.sampled_markets}`})));
 options('datasets',workspace.datasets.map(d=>({id:d.id,label:`${d.day} · ${d.asset} · ${d.markets} markets · version ${d.id}`})));
 $('results').replaceChildren(...workspace.runs.map(run=>{const card=document.createElement('article');card.className='run-card';const title=document.createElement('strong'),p=document.createElement('p'),note=document.createElement('p'),r=run.result;
 title.textContent=r?`${money(r.profit_loss_cents)} P/L · ${money(r.ending_cash_cents)} ending balance`:`Replay ${run.status}`;
 p.textContent=r?`${r.orders_placed??r.attempts} bids · ${r.filled_contracts??r.simulated_fills} filled contracts · ${r.expired_orders??r.no_fill_evidence} expired orders · ${r.priority_cancellations??0} priority cancellations · ${r.loss_prevention_sales??0} loss-prevention sales`:(run.error_code?'Replay could not finish. Choose fewer days and retry.':'Waiting for the paper processor.');
 note.className='small';note.textContent=r?`${r.fill_model}. ${r.assumptions??'Historical fill proxy; actual queue position is unknown.'}`:'';card.append(title,p,note);
 if(r?.order_preview?.length){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Order activity · first recorded events';details.append(summary);for(const event of r.order_preview){const line=document.createElement('p');line.className='small';line.textContent=`${new Date(event.time*1000).toLocaleString()} · ${event.ticker} · ${event.kind.replaceAll('_',' ')} · ${event.contracts} contracts${event.bid_cents!==undefined?' @ '+event.bid_cents+'¢':event.sale_cents!==undefined?' @ '+event.sale_cents+'¢':''}${event.reason?' · '+event.reason.replaceAll('_',' '):''}`;details.append(line)}card.append(details)}return card}));
 if(!busy)$('status').textContent='Paper workspace ready · live trading disabled';
 }catch(error){$('status').textContent=error.message}}
$('run').addEventListener('click',async()=>{
 if(busy)return;busy=true;$('run').disabled=true;
 try{const strategy_ids=checked('strategies'),dataset_ids=checked('datasets').map(Number);if(!strategy_ids.length||!dataset_ids.length)throw Error('Select at least one strategy and one saved day.');if(dataset_ids.length>12)throw Error('Select at most 12 saved days per replay.');
 requestKey??=crypto.randomUUID();await paperCall('replays',{strategy_ids,dataset_ids,starting_cash_cents:Math.round(Number($('cash').value)*100),fill_model:$('fillModel').value,request_key:requestKey});requestKey=null;
 $('status').textContent='Portfolio replay queued. Results update here.';await load();
 }catch(error){$('status').textContent=error.message}finally{busy=false;$('run').disabled=false}
});
for(const id of ['strategies','datasets','cash','fillModel'])$(id).addEventListener('change',()=>{requestKey=null});
void load();const refreshTimer=setInterval(load,15000);refreshTimer?.unref?.();

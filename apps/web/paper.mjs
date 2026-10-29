import {paperCall} from './paper-client.mjs';
import {appendActivity} from './paper-activity.mjs';
const setupCache=new Map(),openSetups=new Set();
const $=id=>document.getElementById(id);let workspace,busy=false,requestKey=null,pendingCancel=null;
function requestCancel(run){
 pendingCancel=run.id;
 $('cancelReplayName').textContent=run.name||run.strategy_names?.slice(0,3).join(' + ')||'Portfolio replay';
 $('confirmCancelReplay').disabled=false;
 $('cancelReplayDialog').showModal();
}
$('keepReplay').addEventListener('click',()=>{$('cancelReplayDialog').close();pendingCancel=null});
$('cancelReplayDialog').addEventListener('close',()=>{pendingCancel=null});
$('confirmCancelReplay').addEventListener('click',async()=>{
 if(!pendingCancel)return;
 const id=pendingCancel;
 $('confirmCancelReplay').disabled=true;
 try{
  await paperCall('replays/'+id+'/cancel',{});
  $('cancelReplayDialog').close();pendingCancel=null;
  await load();
 }catch(error){
  $('status').textContent=error.message;
  $('confirmCancelReplay').disabled=false;
 }
});
const checked=id=>[...$(id).querySelectorAll('input:checked')].map(e=>e.value);
function options(id,items){const selected=new Set(checked(id));$(id).replaceChildren(...items.map(item=>{const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.value=item.id;input.checked=selected.has(String(item.id));const span=document.createElement('span');span.textContent=item.label;label.append(input,span);return label}));if(!items.length)$(id).textContent=id==='strategies'?'No table-based strategies saved. Choose New bet on the statistics table.':'No analyzed trade datasets yet. They will appear as analysis finishes.';}
function money(cents){return '$'+(cents/100).toFixed(2)}
async function load(){try{
 workspace=await paperCall('workspace');
 options('strategies',workspace.strategies.filter(s=>s.strategy.bid_offset==null).map(s=>({id:s.id,label:`${s.strategy.name} · ${s.asset} · saved yield ${s.strategy.statistical_yield_percent.toFixed(2)}% · n=${s.strategy.sampled_markets}`})));
 options('datasets',workspace.datasets.map(d=>({id:d.id,label:`${d.day} · ${d.asset} · ${d.markets} markets · version ${d.id}`})));
 $('results').replaceChildren(...workspace.runs.map(run=>{const card=document.createElement('article');card.className='run-card';const title=document.createElement('strong'),p=document.createElement('p'),note=document.createElement('p'),r=run.result;
 title.textContent=(run.name||run.strategy_names?.slice(0,3).join(' + ')||'Portfolio replay')+' · '+(r?`${money(r.profit_loss_cents)} P/L · ${money(r.ending_cash_cents)} ending balance`:`Replay ${run.status}`);
 p.textContent=r?`${r.orders_placed??r.attempts} bids · ${r.filled_contracts??r.simulated_fills} filled contracts · ${r.expired_orders??r.no_fill_evidence} expired orders · ${r.priority_cancellations??0} priority cancellations · ${r.loss_prevention_sales??0} loss-prevention sales`:(run.status==='cancelled'?'Canceled by you. No further work will be published.':run.error_code?'Replay could not finish. Choose fewer days and retry.':'Waiting for the paper processor.');
 note.className='small';note.textContent=r?`${r.fill_model}. ${r.assumptions??'Historical fill proxy; actual queue position is unknown.'}`:'';card.append(title,p,note);
 appendActivity(card,run,document);
 const setup=document.createElement('details'),setupTitle=document.createElement('summary');setupTitle.textContent='View run setup';setup.append(setupTitle);
 setup.addEventListener('toggle',async()=>{if(!setup.open){openSetups.delete(run.id);return}openSetups.add(run.id);if(setup.dataset.loaded)return;setup.dataset.loaded='true';try{
 const saved=setupCache.get(run.id)??(await paperCall('replays/'+run.id)).run;setupCache.set(run.id,saved);const config=saved.configuration;
 const lines=[`Created ${new Date(saved.created_at).toLocaleString()} · starting balance ${money(config.starting_cash_cents??config.strategy?.starting_cash_cents??10000)} · fill model ${config.fill_model??'legacy conservative'}`,
 'Saved days: '+saved.source_days.map(d=>`${d.day} / ${d.asset} / version ${d.id}`).join('; '),
 ...(config.strategies??[config.strategy]).filter(Boolean).map(s=>`${s.name} · ${s.asset} · ask ${s.min_price}–${s.max_price}¢ · ${s.entry_minute_min??'?'}–${s.entry_minute_max??s.minutes?.join(',')} minutes before close · ${s.below_ask_cents??'?'}¢ below ask · maximum ${s.maximum_bid_cents==null?'none':s.maximum_bid_cents+'¢'} · ${s.contracts} contracts · ${s.balance_percent??10}% of balance · loss prevention ${s.loss_trigger_cents==null?'off':'sell at '+s.loss_trigger_cents+'¢ or lower'}`)];
 for(const text of lines){const line=document.createElement('p');line.textContent=text;setup.append(line)}
 }catch(error){setup.dataset.loaded='';const line=document.createElement('p');line.textContent=error.message;setup.append(line)}});if(openSetups.has(run.id))setup.open=true;card.append(setup);
 if(['queued','running'].includes(run.status)){
  const actions=document.createElement('div');actions.className='run-actions';
  const menu=document.createElement('details');menu.className='run-more';
  const menuTitle=document.createElement('summary');menuTitle.textContent='More actions';
  const cancel=document.createElement('button');cancel.type='button';cancel.className='danger';cancel.textContent='Cancel this run…';
  cancel.addEventListener('click',()=>requestCancel(run));
  menu.append(menuTitle,cancel);actions.append(menu);card.append(actions);
 }return card}));
 if(!busy)$('status').textContent='Paper workspace ready · live trading disabled';
 }catch(error){$('status').textContent=error.message}}
$('run').addEventListener('click',async()=>{
 if(busy)return;busy=true;$('run').disabled=true;
 try{const strategy_ids=checked('strategies'),dataset_ids=checked('datasets').map(Number);if(!strategy_ids.length||!dataset_ids.length)throw Error('Select at least one strategy and one saved day.');if(dataset_ids.length>12)throw Error('Select at most 12 saved days per replay.');
 requestKey??=crypto.randomUUID();const queued=await paperCall('replays',{name:$('runName').value.trim(),strategy_ids,dataset_ids,starting_cash_cents:Math.round(Number($('cash').value)*100),fill_model:$('fillModel').value,request_key:requestKey});requestKey=null;
 $('status').textContent=`Replay ${queued.id} queued. Follow its status and order activity below.`;await load();
 }catch(error){$('status').textContent=error.message}finally{busy=false;$('run').disabled=false}
});
for(const id of ['strategies','datasets','cash','fillModel','runName'])$(id).addEventListener('change',()=>{requestKey=null});
void load();const refreshTimer=setInterval(load,5000);refreshTimer?.unref?.();

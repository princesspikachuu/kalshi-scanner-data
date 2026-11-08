import {demoCall,escapeHTML as e,botSummaryPeriodMarkup,botSummaryPeriodPreferences} from './demo-client.mjs';
import {createAuthClient} from './auth-client.mjs';
import {dollars,pnlClass,accountMarkup,exposureMarkup,accountPnl,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,favoriteTimingMarkup,favoriteResearchMarkup,marketTypeGroups,marketTypeSummaryMarkup} from './shadow-view.mjs';
const $=id=>document.getElementById(id),periods=botSummaryPeriodPreferences(undefined,true);
let data,events=[],timer,busy=false,requestId=null,resetFolder=null,resetRequest=null;
let folderPeriod='all';try{folderPeriod=localStorage.getItem('moneytree-folder-period')||'all'}catch{}
if(!Object.hasOwn(folderPeriods,folderPeriod))folderPeriod='all';
let folderViews={open:[],periods:{}};try{folderViews=JSON.parse(localStorage.getItem('moneytree-folder-views')||'{}')}catch{}
let researchViews=[];try{researchViews=JSON.parse(localStorage.getItem('moneytree-research-views')||'[]')}catch{}
const openResearch=new Set(Array.isArray(researchViews)?researchViews.filter(k=>typeof k==='string'):[]);
const pendingFolders=new Set();
const openFolders=new Set(Array.isArray(folderViews?.open)?folderViews.open:[]);
const folderSummaryPeriods=Object.fromEntries(Object.entries(folderViews?.periods||{}).filter(([,period])=>Object.hasOwn(folderPeriods,period)));
function saveFolderViews(){try{localStorage.setItem('moneytree-folder-views',JSON.stringify({open:[...openFolders],periods:folderSummaryPeriods}))}catch{}}
let marketViews=[];try{marketViews=JSON.parse(localStorage.getItem('moneytree-market-views')||'[]')}catch{}
const openMarkets=new Set(Array.isArray(marketViews)?marketViews.filter(id=>typeof id==='string'):[]);
function saveMarketViews(){try{localStorage.setItem('moneytree-market-views',JSON.stringify([...openMarkets]))}catch{}}
let typeViews=[];try{typeViews=JSON.parse(localStorage.getItem('moneytree-market-type-views')||'[]')}catch{}
const openMarketTypes=new Set(Array.isArray(typeViews)?typeViews.filter(id=>typeof id==='string'):[]);
function saveMarketTypeViews(){try{localStorage.setItem('moneytree-market-type-views',JSON.stringify([...openMarketTypes]))}catch{}}
function marketTypeFolders(bots,status,folderId,search='',retired=false,allBots=bots){
 const fullGroups=new Map(marketTypeGroups(allBots).map(g=>[g.id,g]));
 const period=folderSummaryPeriods[folderId]||folderPeriod;
 return marketTypeGroups(bots).map(group=>{
  const key=folderId+'::'+(retired?'retired::':'')+group.id;
  const summary=fullGroups.get(group.id)||group;
  return `<details class="market-type-folder" data-market-type="${e(key)}" ${openMarketTypes.has(key)||search?'open':''}><summary>${marketTypeSummaryMarkup(summary,period,status.positions||[],search?group.bots.length:null)}</summary><div class="bot-list">${group.bots.map(b=>botCard(b,status)).join('')}</div></details>`;
 }).join('');
}
const note=value=>$('message').textContent=value;
function botCard(bot,status){
  const selected=periods[bot.id]||'all',metrics=(bot.financial_metrics||bot.metrics).all,ticker=status.selected?.[bot.series];
  const market=status.market_states?.[ticker],active=market&&market.close>Date.now()/1000;
  const positions=(status.positions||[]).filter(p=>p.bot_id?p.bot_id===bot.id:p.ticker.startsWith(bot.series+'-'));
  const orders=(status.orders||[]).filter(o=>o.bot_id?o.bot_id===bot.id:o.ticker.startsWith(bot.series+'-'));
  const accountTotal=accountPnl(bot.account,positions);
  const state=bot.desired==='paused'?'Paused':!data.connection_configured?'Connect data':bot.experiment?bot.experiment.message:ticker?active?market.entries_paused?'Entries paused · next cycle':!market.data_valid?'Data gap · entries blocked':'Active market':'Settlement pending':'Waiting for active market';
  const stats=[['Gross realized P/L · before fees',dollars(metrics.gross_profit)],['Fees paid',dollars(metrics.fees)],['Win rate',metrics.win_rate===null?'—':Number(metrics.win_rate).toFixed(1)+'%'],['Verified cycle reports',metrics.cycles],['Cycle reports with gaps',metrics.excluded_cycles]];
  return `<details class="bot-card market-card" data-market="${e(bot.id)}" ${openMarkets.has(bot.id)?'open':''}><summary class="bot-top"><div class="market-heading"><div class="bot-name">${e(bot.name)}</div><p class="small market-description">${e(bot.strategy==='sequential'?(bot.asset==='sports'?'Sequential complementary bids · throughout verified live games':'Sequential complementary bids · learned completion estimates'):bot.strategy==='complete_set'?'Taker complete sets · depth and fees checked':bot.strategy==='favorites'?(bot.asset==='sports'?'70–95¢ favorites · live game only · final 2 estimated hours':'70–95¢ favorites · maker entry · evidence-based exits'):'10¢ → 3¢ · recover cost at 40¢+ · final freeze')}</p></div><span class="badge ${bot.desired==='paused'?'paused':''}">${e(state)}</span><span class="market-disclosure" aria-hidden="true"></span>${botPnlMarkup(bot,selected,positions)}</summary><div class="market-card-body">${bot.experiment?`<div class="bot-stats"><div><span>Attempts</span><strong>${e(String(bot.experiment.attempts||0))}</strong></div><div><span>${bot.strategy==='favorites'?'Settled entries':'Completed'}</span><strong>${e(String(bot.experiment.completed||0))}</strong></div><div><span>Unmatched attempts</span><strong>${e(String(bot.experiment.unmatched||0))}</strong></div></div>${bot.experiment.decision?`<p class="small">Last bids: YES ${(Number(bot.experiment.decision.yes)*100).toFixed(0)}¢ / NO ${(Number(bot.experiment.decision.no)*100).toFixed(0)}¢ · ${bot.experiment.decision.mode==='paper_exploration'?'Exploration: probabilities not established':`Estimated completion: ${(100*bot.experiment.decision.estimate.completion_probability).toFixed(1)}%`} · ${bot.experiment.decision.estimate.samples} matching observations</p>`:''}`:''}${bot.experiment?.calibration?.length&&!bot.experiment?.entry_timing?.length?`<div class="table-scroll"><table><thead><tr><th>Favorite entry band</th><th>Settled contracts</th><th>Outcome win rate</th><th>Hold break-even after fees</th><th>Net P/L</th></tr></thead><tbody>${bot.experiment.calibration.map(r=>`<tr><td>${e(r.band)}</td><td>${e(r.contracts)}</td><td>${r.win_rate===null?'—':Number(r.win_rate).toFixed(1)+'%'}</td><td>${r.breakeven===null?'—':Number(r.breakeven).toFixed(1)+'%'}</td><td>${e(dollars(r.net))}</td></tr>`).join('')}</tbody></table></div>`:''}${bot.strategy==='favorites'?favoriteTimingMarkup(bot.experiment?.entry_timing):''}<p class="money-heading">Money currently committed · all versions</p>${exposureMarkup(bot.account,positions)}<p class="small">${data.version==='latest'?'Most recent version · v'+bot.revision:'Full shadow history'} · ${new Date(bot.changed_at*1000).toLocaleString()}</p><p class="money-heading">Trading statistics · full available period</p><p class="small">The P/L controls above change the profit window. These statistics follow the version filter and show the full available period.</p><div class="bot-stats">${stats.map(([label,value])=>`<div><span>${e(label)}</span><strong>${e(value)}</strong></div>`).join('')}</div>${metrics.excluded_cycles?`<p class="account-warning">Includes simulated trades from ${e(String(metrics.excluded_cycles))} cycle reports with gaps. These results are unverified.</p>`:""}${!bot.strategy||bot.strategy==='convexity'?executionMarkup(bot.execution):''}<p class="small">${e(ticker||bot.series)}${market&&!market.data_valid?' · Current cycle excluded after a data gap':''}</p><details class="advanced"><summary>${positions.length} position lots · ${orders.length} pending/resting orders</summary><div class="table-scroll"><table><thead><tr><th>Type</th><th>Side</th><th>Contracts</th><th>Cost / reserved</th><th>Value</th><th>State</th></tr></thead><tbody>${positions.map(p=>`<tr><td>Position${p.state==='pending'?' · awaiting settlement':''}</td><td>${e(p.side.toUpperCase())}</td><td>${e(p.quantity)}</td><td>${e(dollars(p.cost))}</td><td>${e(dollars(p.value))}</td><td>${p.is_armed?'Armed':'Not armed'} · Phase ${e(p.phase_origin)}${Number(p.recovery_cost)>0?` · Recovered ${e(dollars(p.recovery_proceeds))} / ${e(dollars(p.recovery_cost))}`:''}</td></tr>`).join('')}${orders.map(o=>`<tr><td>${e(o.action)} · ${o.maker?'Maker':'IOC'}</td><td>${e(o.side.toUpperCase())}</td><td>${e(o.quantity)}</td><td>${e(dollars(o.reserved))}</td><td>—</td><td>${e(o.status)} @ ${e((Number(o.price)*100).toFixed(2))}¢</td></tr>`).join('')}</tbody></table></div></details><div class="bot-footer">${bot.retired?'<p class="small">Retired · entries disabled · existing positions retain risk exits and settlement.</p>':`<button data-toggle="${e(bot.id)}">${bot.desired==='running'?'Pause':'Resume'}</button><label>Contracts / order<input data-size="${e(bot.id)}" type="number" min="1" max="10000" value="${bot.contracts}"></label><button class="secondary" data-save="${e(bot.id)}">Save new version</button>`}</div></div></details>`;

}
function draw(){
 const status=data.status||{},health=data.health||{};
 $('health').textContent=health.message||'Waiting for worker';
 $('accountSummary').innerHTML=data.folders?.length?folderOverviewMarkup(data.folders,folderPeriod)+sequentialComparisonMarkup(data.folders)+monitoringMarkup(status.monitoring):accountMarkup(data.accounting,Date.now()/1000,status.positions||[]);
 for(const b of document.querySelectorAll('[data-folder-period]'))b.onclick=()=>{folderPeriod=b.dataset.folderPeriod;for(const id of Object.keys(folderSummaryPeriods))delete folderSummaryPeriods[id];saveFolderViews();try{localStorage.setItem('moneytree-folder-period',folderPeriod)}catch{}draw()};
 $('connect').textContent=data.connection_configured?'Manage production data key':'Connect production Read key';
 const find=$('find').value.toLowerCase();
 const folders=data.folders?.length?data.folders:[{id:'convexity',name:'Convexity',description:'',accounting:data.accounting}];
 $('groups').innerHTML=folders.map(folder=>{
  const folderBots=data.bots.filter(b=>(b.folder_id||'convexity')===folder.id);
  const activeFolderBots=folderBots.filter(b=>!b.retired);
  const matching=folderBots.filter(b=>(b.name+' '+b.series).toLowerCase().includes(find));
  const bots=matching.filter(b=>!b.retired),retired=matching.filter(b=>b.retired);
  const money=folder.accounting,local=folder.id==='convexity'?status:{...status,positions:money?.positions||[],orders:money?.orders||[]};
  const running=activeFolderBots.filter(b=>b.desired==='running').length;
  return `<details class="strategy-folder panel" id="folder-${e(folder.id)}" ${openFolders.has(folder.id)?'open':''} data-folder="${e(folder.id)}"><summary>${folderCardSummaryMarkup(folder,folderSummaryPeriods[folder.id]||folderPeriod,{bots:activeFolderBots.length,running,pending:pendingFolders.has(folder.id),controls:!!data.folders?.length})}</summary><p>${e(folder.description)}</p>${data.folders?.length?`<div class="folder-actions"><button data-folder-pause="${e(folder.id)}" class="secondary">Pause folder</button><button data-folder-resume="${e(folder.id)}" class="secondary">Resume folder</button><button data-folder-reset="${e(folder.id)}" class="secondary">Reset funds</button></div>`:'<p class="small">Strategy folders are waiting for the paper worker upgrade. Existing bots retain their current state.</p>'}<p class="small">Separate virtual account · $1,000 starting balance · paper trades only</p>${money?accountMarkup(money,Date.now()/1000,money.positions||status.positions||[]):'<p>Waiting for the worker’s first account snapshot…</p>'}${folder.scanner?`<p class="small">Scanner: ${e(folder.scanner.state||'waiting')} · ${folder.scanner.groups||0} verified event groups · ${folder.scanner.subscribed_markets||0} markets</p>`:''}${folder.id==='favorites'?favoriteResearchMarkup(matching,openResearch):''}${marketTypeFolders(bots,local,folder.id,find,false,activeFolderBots)}${retired.length?`<details class="advanced"><summary>Retired 15-minute bots · ${retired.length} · history and remaining exits</summary>${marketTypeFolders(retired,local,folder.id,find,true,folderBots.filter(b=>b.retired))}</details>`:''}</details>`;
 }).join('');
 for(const detail of document.querySelectorAll('details[data-research]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false)return;const key=detail.dataset.research;if(detail.open)openResearch.add(key);else openResearch.delete(key);try{localStorage.setItem('moneytree-research-views',JSON.stringify([...openResearch]))}catch{}};
 for(const detail of document.querySelectorAll('details[data-market-type]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false||$('find').value.trim())return;const key=detail.dataset.marketType;if(detail.open)openMarketTypes.add(key);else openMarketTypes.delete(key);saveMarketTypeViews()};
 for(const detail of document.querySelectorAll('details[data-market]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false)return;const id=detail.dataset.market;if(detail.open)openMarkets.add(id);else openMarkets.delete(id);saveMarketViews()};
 for(const detail of document.querySelectorAll('details[data-folder]'))detail.ontoggle=()=>{if(detail.isConnected===false)return;const id=detail.dataset.folder;if(detail.open)openFolders.add(id);else openFolders.delete(id);saveFolderViews()};
 for(const b of document.querySelectorAll('[data-folder-summary-period]'))b.onclick=event=>{event.preventDefault();event.stopPropagation();folderSummaryPeriods[b.dataset.summaryFolder]=b.dataset.folderSummaryPeriod;saveFolderViews();draw()};
 for(const b of document.querySelectorAll('[data-folder-pause]')){b.disabled=pendingFolders.has(b.dataset.folderPause);b.onclick=event=>{event?.preventDefault();event?.stopPropagation();return folderControl(b.dataset.folderPause,'pause')}}
 for(const b of document.querySelectorAll('[data-folder-resume]')){b.disabled=pendingFolders.has(b.dataset.folderResume);b.onclick=event=>{event?.preventDefault();event?.stopPropagation();return folderControl(b.dataset.folderResume,'resume')}}
 for(const b of document.querySelectorAll('[data-folder-reset]'))b.onclick=()=>{
  resetFolder=b.dataset.folderReset;resetRequest=null;
  $('resetName').textContent=data.folders?.find(f=>f.id===resetFolder)?.name||resetFolder;
  $('resetDialog').showModal();
 };
 for(const button of document.querySelectorAll('[data-bot-summary]'))button.onclick=event=>{event.preventDefault();event.stopPropagation();periods[button.dataset.botSummary]=button.dataset.summaryPeriod;botSummaryPeriodPreferences(periods,true);draw()};
 for(const button of document.querySelectorAll('[data-toggle]'))button.onclick=()=>change(button.dataset.toggle,{desired:data.bots.find(b=>b.id===button.dataset.toggle).desired==='running'?'paused':'running'});
 for(const button of document.querySelectorAll('[data-save]'))button.onclick=()=>change(button.dataset.save,{contracts:Number([...document.querySelectorAll('[data-size]')].find(i=>i.dataset.size===button.dataset.save).value)});
 $('events').innerHTML='<table><thead><tr><th>Time</th><th>Strategy</th><th>Market</th><th>Event</th><th>Details</th></tr></thead><tbody>'+events.map(r=>`<tr><td>${e(new Date(r.time*1000).toLocaleString())}</td><td>${e(data.folders?.find(f=>f.id===(r.folder_id||'convexity'))?.name||'Convexity')}</td><td>${e(data.bots.find(b=>r.ticker?.startsWith(b.series+'-'))?.name||r.ticker||'Wallet')}</td><td>${e(r.event)}</td><td>${e([r.side,r.quantity,r.price?'$'+r.price:'',r.fee?'fee $'+r.fee:'',r.reason].filter(Boolean).join(' · '))}</td></tr>`).join('')+'</tbody></table>';
}
async function load(){
 if(busy)return;busy=true;clearTimeout(timer);
 try{
  const result=await demoCall('shadow/workspace?version='+($('latest').checked?'latest':'full'));
  if(!result.installed){$('health').textContent='Worker initializing';note('Shadow engine is initializing. Reload after the worker finishes its handover.');return}
  data=result;draw();
  try{const activity=await demoCall('shadow/events');events=Array.isArray(activity.items)?activity.items:[];draw()}catch{note('Balances and bots loaded. Activity is temporarily unavailable; retrying automatically.')}
 }catch(error){
  note(error.message);
  if(!data){$('health').textContent='Dashboard data unavailable';$('accountSummary').innerHTML='<p>Account data could not load. Retrying automatically. Use Reload data to try again.</p>'}
 }finally{busy=false;timer=setTimeout(load,10000)}
}
async function change(id,fields){try{const bot=data.bots.find(b=>b.id===id);await demoCall('shadow/bots/'+id,{revision:bot.revision,...fields});note('Saved. New entries follow the worker’s next verified update; existing risk management continues.');await load()}catch(error){note(error.message)}}
$('find').oninput=()=>{if(data)draw()};$('latest').onchange=load;$('reload').onclick=load;
for(const [id,action] of [['pauseAll','pause'],['resumeAll','resume']])$(id).onclick=async()=>{try{await demoCall('shadow/bulk',{action});await load()}catch(error){note(error.message)}};
$('funds').onsubmit=async event=>{event.preventDefault();try{requestId=requestId||crypto.randomUUID();await demoCall('shadow/funds',{amount_cents:Math.round(Number($('fundAmount').value)*100),request_id:requestId});requestId=null;note('Virtual refill queued. It appears when the paper worker applies it; no real money moves.');await load()}catch(error){note(error.message)}};
$('connect').onclick=()=>$('connectionDialog').showModal();
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>$(button.dataset.close).close();
$('paperKeyFile').onchange=async()=>{const file=$('paperKeyFile').files[0];if(!file)return;if(file.size>12000){$('connectionMessage').textContent='Key file must be at most 12 KB.';return}$('demoPem').value=await file.text()};
$('connectionForm').onsubmit=async event=>{event.preventDefault();$('saveConnection').disabled=true;try{await demoCall('paper-connection',{key_id:$('demoKey').value.trim(),private_key:$('demoPem').value.trim()});$('connectionDialog').close();note('Production Read key verified. The shadow worker will connect automatically.');await load()}catch(error){$('connectionMessage').textContent=error.message}finally{$('demoPem').value='';$('demoKey').value='';$('paperKeyFile').value='';$('saveConnection').disabled=false}};
$('csv').onclick=()=>{const cols=['time','folder_id','ticker','event','order_id','side','action','quantity','price','fee','slippage','reason','cash','details'];const quote=x=>'"'+String(x??'').replaceAll('"','""')+'"';const csv=[cols.join(','),...events.map(r=>cols.map(c=>quote(r[c])).join(','))].join('\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='money-tree-shadow-activity.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('signOut').onclick=async()=>{await createAuthClient().signOut();location.replace('/')};
load();

async function folderControl(folder_id,action){
 if(pendingFolders.has(folder_id))return;
 pendingFolders.add(folder_id);draw();
 try{await demoCall('shadow/bulk',{action,folder_id});note((data.folders?.find(f=>f.id===folder_id)?.name||folder_id)+(action==='pause'?': paused. The worker cancels pending buys and continues managing existing positions.':': resumed. New entries follow the worker’s next verified update.'));await load()}
 catch(error){note(error.message)}finally{pendingFolders.delete(folder_id);draw()}
}
$('confirmReset').onclick=async()=>{const b=$('confirmReset');b.disabled=true;try{
 resetRequest=resetRequest||crypto.randomUUID();await demoCall('shadow/folders/'+resetFolder+'/reset',{request_id:resetRequest});
 $('resetDialog').close();note('Reset queued. The worker will archive this session and start a fresh $1,000 account with zero P/L.');await load();
}catch(error){$('resetError').textContent=error.message}finally{b.disabled=false}};
$('sessionHistory').onclick=async()=>{try{const r=await demoCall('shadow/sessions');
 $('sessionList').innerHTML=r.items.length?r.items.map(item=>`<p>${e(data.folders?.find(f=>f.id===item.folder_id)?.name||item.folder_id)} · ${e(new Date(item.ended_at*1000).toLocaleString())} <button class="secondary" data-session="${e(item.key)}">Download session</button></p>`).join(''):'<p>No previous reset sessions.</p>';
 for(const b of document.querySelectorAll('[data-session]'))b.onclick=async()=>{try{const r=await demoCall('shadow/sessions/'+b.dataset.session),url=URL.createObjectURL(new Blob([JSON.stringify(r.session,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='money-tree-paper-session-'+b.dataset.session+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){note(error.message)}};
 $('sessionsDialog').showModal();
}catch(error){note(error.message)}};

import {scalperMarkup} from './scalper-view.mjs';
import {demoCall,escapeHTML as e,botSummaryPeriodMarkup,botSummaryPeriodPreferences} from './demo-client.mjs';
import {createAuthClient} from './auth-client.mjs';
import {dollars,pnlClass,accountMarkup,exposureMarkup,accountPnl,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,favoriteTimingMarkup,favoriteResearchMarkup,favoriteCategoryResearchMarkup,favoriteStatisticsMatrixMarkup,favoriteCollectorOverviewMarkup,favoriteProfitLegendMarkup,favoriteTableSettingsMarkup,favoriteWideOverviewMarkup,favoriteSingleOverviewMarkup,learningDiagnosticsMarkup,marketTypeGroups,marketTypeSummaryMarkup,botPnlDetailsMarkup} from './shadow-view.mjs';
const $=id=>document.getElementById(id),periods=botSummaryPeriodPreferences(undefined,true);
let loadError=null;
let lastRestartRefresh=0,restartRequestPending=false;
async function refreshWorkerRestarts(){
 if(restartRequestPending || (Date.now()-lastRestartRefresh<15000))return;
 restartRequestPending=true;
 try{
  const status=await demoCall('shadow/restarts');
  const count=$('workerRestartCount'),note=$('workerRestartNote'),box=$('workerRestarts');
  box.classList.remove('attention');
  if(!status.tracked){
   count.textContent='—';note.textContent='Tracking starts after the next worker startup';
  }else{
   const n=Number(status.restarts_24h);
   count.textContent=Number.isSafeInteger(n)&&n>=0?String(n):'—';
   box.classList.toggle('attention',n>0||status.lower_bound);
   note.textContent=status.lower_bound?'At least this many · unusually high restart volume'
    :status.full_window?'Rolling 24h · includes deployments':'Recording history · first 24h incomplete';
  }
  lastRestartRefresh=Date.now();
 }catch{
  $('workerRestartCount').textContent='—';
  $('workerRestartNote').textContent='Restart count unavailable';
  lastRestartRefresh=Date.now();
 }finally{restartRequestPending=false}
}
let data,events=[],timer,busy=false,resetFolder=null,resetRequest=null,refillFolder=null,refillRequest=null;
let favoriteTableMode='detailed';try{const saved=localStorage.getItem('moneytree-favorite-table-mode');if(['detailed','wide','single'].includes(saved))favoriteTableMode=saved}catch{}
let folderPeriod='all';try{folderPeriod=localStorage.getItem('moneytree-folder-period')||'all'}catch{}
if(!Object.hasOwn(folderPeriods,folderPeriod))folderPeriod='all';
let folderViews={open:[],periods:{}};try{folderViews=JSON.parse(localStorage.getItem('moneytree-folder-views')||'{}')}catch{}
let researchViews=[];try{researchViews=JSON.parse(localStorage.getItem('moneytree-research-views')||'[]')}catch{}
const openResearch=new Set(Array.isArray(researchViews)?researchViews.filter(k=>typeof k==='string'):[]);
let favoriteStars=[];try{favoriteStars=JSON.parse(localStorage.getItem('moneytree-favorites-starred-v1')||'[]')}catch{}
const starredBuckets=new Set(Array.isArray(favoriteStars)?favoriteStars.filter(key=>typeof key==='string'&&key.length<=350).slice(0,2000):[]);
function saveFavoriteStars(){try{localStorage.setItem('moneytree-favorites-starred-v1',JSON.stringify([...starredBuckets]))}catch{}}
const folderResearch=new Map(),folderResearchLoadedAt=new Map(),loadingFolderResearch=new Set(),folderResearchErrors=new Map();
function researchBot(bot){
 const folder=bot.folder_id||'convexity',extra=folderResearch.get(folder)?.[bot.id];
 return extra?{...bot,experiment:{...(bot.experiment||{}),...extra}}:bot;
}
async function loadFolderResearch(folder){
 if(!['favorites','favorites_statistics'].includes(folder)||loadingFolderResearch.has(folder))return;
 const loaded=folderResearchLoadedAt.get(folder)||0;if(Date.now()-loaded<30000)return;
 loadingFolderResearch.add(folder);
 try{
  const result=await demoCall('shadow/research-folder/'+folder);
  if(!result?.bots||typeof result.bots!=='object'||Array.isArray(result.bots))throw new Error('Invalid research response');
  folderResearch.set(folder,result.bots);
  folderResearchLoadedAt.set(folder,Date.now());
  folderResearchErrors.delete(folder);
  if(data)draw();
 }catch(error){folderResearchErrors.set(folder,error.message);note('Research detail unavailable: '+error.message);if(data)draw()}
 finally{loadingFolderResearch.delete(folder)}
}
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
function marketTypeFolders(bots,status,folderId,search='',retired=false,allBots=bots,timedSummary=null,wideSummary=null){
 const fullGroups=new Map(marketTypeGroups(allBots).map(g=>[g.id,g]));
 const period=folderSummaryPeriods[folderId]||folderPeriod;
 return marketTypeGroups(bots).map(group=>{
  const key=folderId+'::'+(retired?'retired::':'')+group.id;
  const summary=fullGroups.get(group.id)||group;
  return `<details class="market-type-folder" data-market-type="${e(key)}" ${openMarketTypes.has(key)||search?'open':''}><summary>${marketTypeSummaryMarkup(summary,period,status.positions||[],search?group.bots.length:null,status.orders||[],data.folders?.find(f=>f.id===folderId)?.filled_events_by_category?.[group.id])}</summary><div class="category-research">${folderId==='favorites'?'':group.bots.some(b=>['volatility_scalper','market_maker'].includes(b.strategy))?favoriteCategoryResearchMarkup({...summary,research_kind:'round_trips',bots:summary.bots.map(b=>({...b,experiment:{entry_timing:(b.experiment?.scalper?.cells||[]).filter(c=>c.dimensions?.price_tier&&c.dimensions.price_tier!=='unfilled').map(c=>({series:b.series,market_type:group.id,clock:'market_close',horizon:c.dimensions.horizon,price:Number(c.dimensions.price_tier.split('–')[0])/100,contracts:c.entry_quantity||0,closed:c.closed_quantity||0,resolved:c.closed_quantity||0,winners:c.winning_quantity||0,events:c.completed||0,event_wins:c.wins||0,cost:c.entry_cost||0,net:c.net,holding_seconds:c.holding_seconds}))}}))},openResearch):''}</div><div class="bot-list">${group.bots.map(b=>botCard(b,status)).join('')}</div></details>`;
 }).join('');
}
// Capture currently open second-level panels before polling replaces the DOM.
// This is ephemeral UI state: it never alters trading data or saved preferences.
function expandedDashboardPanels(){
  return new Set([...document.querySelectorAll('details[data-ui-panel]')]
    .filter(panel=>panel.open).map(panel=>panel.dataset.uiPanel));
}
function restoreDashboardPanels(expanded){
  for(const panel of document.querySelectorAll('details[data-ui-panel]'))
    if(expanded.has(panel.dataset.uiPanel))panel.open=true;
}
const note=value=>$('message').textContent=value;
const loadNote=value=>{loadError=value;note(value)};
// Activity is optional and collapsed by default; don't scan its history on
// each portfolio refresh while Favorites research is being inspected.
let lastActivityRefresh=0,activityRequestPending=false;
async function refreshRecentActivity(force=false){
 const detail=$('activity');
 if(!detail?.open||activityRequestPending||(!force&&Date.now()-lastActivityRefresh<60000))return;
 activityRequestPending=true;
 try{
  const response=await demoCall('shadow/events');
  events=Array.isArray(response.items)?response.items:[];
  lastActivityRefresh=Date.now();
  if(data)draw();
 }catch{
  lastActivityRefresh=Date.now();
  if(detail.open)note('Recent activity temporarily unavailable. Favorites and balances are still available.');
 }finally{activityRequestPending=false}
}
function botCard(bot,status){
  const selected=periods[bot.id]||'all',metrics=(bot.financial_metrics||bot.metrics).all,ticker=status.selected?.[bot.series];
  const market=status.market_states?.[ticker],active=market&&market.close>Date.now()/1000;
  const positions=(status.positions||[]).filter(p=>p.bot_id?p.bot_id===bot.id:p.ticker.startsWith(bot.series+'-'));
  const orders=(status.orders||[]).filter(o=>o.bot_id?o.bot_id===bot.id:o.ticker.startsWith(bot.series+'-'));
  const accountTotal=accountPnl(bot.account,positions);
  const state=bot.desired==='paused'?'Paused':!data.connection_configured?'Connect data':bot.experiment?bot.experiment.message:ticker?active?market.entries_paused?'Entries paused · next cycle':!market.data_valid?'Data gap · entries blocked':'Active market':'Settlement pending':'Waiting for active market';
  const briefState=bot.desired==='paused'?'Paused':!data.connection_configured?'Connect data':active&&market?.entries_paused?'Entries paused':active&&!market?.data_valid?'Data gap':'Running';
  const stats=[['Gross realized P/L · before fees',dollars(metrics.gross_profit)],['Fees paid',dollars(metrics.fees)],['Win rate',metrics.win_rate===null?'—':Number(metrics.win_rate).toFixed(1)+'%'],['Verified cycle reports',metrics.cycles],['Cycle reports with gaps',metrics.excluded_cycles]];
  return `<details class="bot-card market-card" data-market="${e(bot.id)}" ${openMarkets.has(bot.id)?'open':''}><summary class="bot-top"><div class="market-heading"><div class="bot-name">${e(bot.name)}</div></div><span class="badge ${bot.desired==='paused'?'paused':''}">${e(briefState)}</span><span class="market-disclosure" aria-hidden="true"></span>${botPnlMarkup(bot,selected,positions)}</summary><div class="market-card-body">${briefState!==state?`<details class="advanced market-status" data-ui-panel="market:${e(bot.id)}:status"><summary>Current market status</summary><p class="small">${e(state)}</p></details>`:''}<details class="advanced market-money" data-ui-panel="market:${e(bot.id)}:money"><summary>Profit & exposure</summary>${botPnlDetailsMarkup(bot,selected,positions)}</details>${bot.experiment?`<div class="bot-stats"><div><span>Attempts</span><strong>${e(String(bot.experiment.attempts||0))}</strong></div><div><span>${['favorites','favorites_statistics'].includes(bot.strategy)?'Settled entries':'Completed'}</span><strong>${e(String(bot.experiment.completed||0))}</strong></div><div><span>Unmatched attempts</span><strong>${e(String(bot.experiment.unmatched||0))}</strong></div></div>${bot.strategy==='favorites_statistics'&&bot.experiment.decision?`<p class="small">Last statistical decision · ${e(bot.experiment.decision.decision_type==='exploration'?'Learning probe':bot.experiment.decision.decision_type==='evidence'?'Evidence-backed':'No entry')} · ${e(bot.experiment.decision.reason||'Awaiting evidence')} · ${e(String(bot.experiment.decision.exact_samples??0))} exact-cell / ${e(String(bot.experiment.decision.samples??0))} pooled observed events · ${e(bot.experiment.decision.level||'No grouping yet')} ${bot.experiment.decision.expected_roi!=null?' · expected ROI '+e((100*Number(bot.experiment.decision.expected_roi)).toFixed(1))+'%':''}</p>`:bot.strategy==='sequential'&&bot.experiment.decision?`<p class="small">Last bids: YES ${(Number(bot.experiment.decision.yes)*100).toFixed(0)}¢ / NO ${(Number(bot.experiment.decision.no)*100).toFixed(0)}¢ · ${bot.experiment.decision.mode==='paper_exploration'?'Exploration: probabilities not established':bot.experiment.decision.estimate?.completion_probability!=null?`Estimated completion: ${(100*bot.experiment.decision.estimate.completion_probability).toFixed(1)}%`:'Estimate unavailable'} · ${e(String(bot.experiment.decision.estimate?.samples??0))} matching observations</p>`:''}`:''}${bot.experiment?.calibration?.length&&!bot.experiment?.entry_timing?.length?`<div class="table-scroll"><table><thead><tr><th>Favorite entry band</th><th>Settled contracts</th><th>Outcome win rate</th><th>Hold break-even after fees</th><th>Net P/L</th></tr></thead><tbody>${bot.experiment.calibration.map(r=>`<tr><td>${e(r.band)}</td><td>${e(r.contracts)}</td><td>${r.win_rate===null?'—':Number(r.win_rate).toFixed(1)+'%'}</td><td>${r.breakeven===null?'—':Number(r.breakeven).toFixed(1)+'%'}</td><td>${e(dollars(r.net))}</td></tr>`).join('')}</tbody></table></div>`:''}${['volatility_scalper','market_maker'].includes(bot.strategy)?scalperMarkup(bot.experiment?.scalper,bot.id,selected):''}${['favorites','favorites_statistics'].includes(bot.strategy)?favoriteTimingMarkup(bot.experiment?.entry_timing,favoriteTableMode==='wide'&&bot.folder_id==='favorites'?(data.folders?.find(f=>f.id==='favorites')?.collector_wide_summary?.by_bot?.[bot.id]?.rows||[]):null,{mode:bot.folder_id==='favorites'?favoriteTableMode:'detailed',single:data.folders?.find(f=>f.id==='favorites')?.collector_single_summary?.by_bot?.[bot.id],panelKey:'market:'+bot.id+':timing',starScope:'market:'+bot.id,starredBuckets}):''}<details class="advanced market-trading-stats" data-ui-panel="market:${e(bot.id)}:stats"><summary>Trading statistics</summary><div class="bot-stats">${stats.map(([label,value])=>`<div><span>${e(label)}</span><strong>${e(value)}</strong></div>`).join('')}</div></details>${metrics.excluded_cycles?`<p class="account-warning">${e(String(metrics.excluded_cycles))} unverified cycles</p>`:""}${(!bot.strategy||bot.strategy==='convexity')&&bot.execution?`<details class="advanced" data-ui-panel="market:${e(bot.id)}:execution"><summary>Execution details</summary>${executionMarkup(bot.execution)}</details>`:''}${market&&!market.data_valid?'<p class="account-warning">Current market data gap</p>':''}<details class="advanced" data-ui-panel="market:${e(bot.id)}:lots"><summary>${positions.length} position lots · ${orders.length} pending/resting orders</summary><div class="table-scroll"><table><thead><tr><th>Type</th><th>Side</th><th>Contracts</th><th>Cost / reserved</th><th>Value</th><th>State</th></tr></thead><tbody>${positions.map(p=>`<tr><td>Position${p.state==='pending'?' · awaiting settlement':''}</td><td>${e(p.side.toUpperCase())}</td><td>${e(p.quantity)}</td><td>${e(dollars(p.cost))}</td><td>${e(dollars(p.value))}</td><td>${p.is_armed?'Armed':'Not armed'} · Phase ${e(p.phase_origin)}${Number(p.recovery_cost)>0?` · Recovered ${e(dollars(p.recovery_proceeds))} / ${e(dollars(p.recovery_cost))}`:''}</td></tr>`).join('')}${orders.map(o=>`<tr><td>${e(o.action)} · ${o.maker?'Maker':'IOC'}</td><td>${e(o.side.toUpperCase())}</td><td>${e(o.quantity)}</td><td>${e(dollars(o.reserved))}</td><td>—</td><td>${e(o.status)} @ ${e((Number(o.price)*100).toFixed(2))}¢</td></tr>`).join('')}</tbody></table></div></details><div class="bot-footer">${bot.retired?'<p class="small">Retired · entries disabled · existing positions hold to settlement.</p>':`<button data-toggle="${e(bot.id)}">${bot.desired==='running'?'Pause':'Resume'}${bot.strategy==='market_maker'?' category':''}</button><label>Contracts / order<input data-size="${e(bot.id)}" type="number" min="1" max="10000" value="${bot.contracts}"></label><button class="secondary" data-save="${e(bot.id)}">Save new version</button>`}</div></div></details>`;

}

function makerDiscoveryMarkup(scanner){
 const ranked=scanner?.ranked||[];
 return `<details class="advanced maker-discovery" data-ui-panel="folder:market_maker:discovery"><summary>Market Maker discovery · ${e(scanner?.state||'Waiting for current worker measurements')}</summary><p class="small">${ranked.length} ranked candidates · ${scanner?.reads||0} shared-budget data reads. Candidates must pass category, actual executed-trade frequency, depth, economics and portfolio limits before orders can be submitted.</p><div class="comparison-grid">${ranked.map(row=>`<article class="comparison-card"><h3>${e(row.ticker)}</h3><p>${e(row.category)} · score ${Number.isFinite(Number(row.score))?Number(row.score).toFixed(4):'—'}</p><p class="small">${e((row.reason||'awaiting inspection').replaceAll('_',' '))}</p></article>`).join('')||'<p class="small">No inspected candidates yet. Discovery waits during processing backlog or read cooldown.</p>'}</div></details>`;
}

/*
 * Older paper workers omit the event counters (and sometimes event_ticker),
 * even though their current positions and working orders are already in the
 * account snapshots. Derive missing counters in the browser so the monitor
 * works before a backend redeploy. No market-data requests or DB scans.
 */
function eventIdFromExposure(row){
 const event=row?.event_ticker;
 if(typeof event==='string'&&event)return event;
 const ticker=row?.ticker;
 if(typeof ticker!=='string'||!ticker)return null;
 // Standard Kalshi market tickers append an outcome/strike to the event
 // ticker. With no such segment, retain the market ticker rather than
 // merging unrelated events in the same series.
 const first=ticker.indexOf('-'),last=ticker.lastIndexOf('-');
 return first>=0&&last>first?ticker.slice(0,last):ticker;
}
function hydrateEventCounts(payload){
 if(!payload||typeof payload!=='object')return payload;
 const newSets=()=>({bid:new Set(),active:new Set(),pending:new Set()});
 const fields=[['bid','unfilled_bid_events','unfilled_bids'],['active','active_events','active_cost'],['pending','pending_events','pending_cost']];
 function apply(account,sets){
  if(!account||typeof account!=='object')return;
  for(const [kind,key,amount] of fields){
   const value=account[key];
   if(Number.isSafeInteger(Number(value))&&value!=null&&Number(value)>=0)continue;
   // Missing details must never turn an existing dollar exposure into zero.
   if(sets[kind].size||Number(account[amount])===0&&account[amount]!=null)account[key]=sets[kind].size;
  }
 }
 function gather(positions,orders){
  const total=newSets(),byBot=new Map();
  const mark=(row,kind)=>{
   const id=eventIdFromExposure(row);if(!id)return;
   total[kind].add(id);
   if(typeof row.bot_id==='string'&&row.bot_id){
    let found=byBot.get(row.bot_id);
    if(!found){found=newSets();byBot.set(row.bot_id,found)}
    found[kind].add(id);
   }
  };
  for(const row of Array.isArray(positions)?positions:[]){
   if(row.state==='active'||row.state==='pending')mark(row,row.state);
  }
  for(const row of Array.isArray(orders)?orders:[]){
   if(row.action==='buy'&&(row.status==='pending'||row.status==='resting'))mark(row,'bid');
  }
  return {total,byBot};
 }
 const folderSets=new Map();
 for(const folder of Array.isArray(payload.folders)?payload.folders:[]){
  const account=folder.accounting;if(!account?.portfolio)continue;
  const legacy=folder.id==='convexity';
  const rows=gather(legacy?payload.status?.positions:account.positions,
                    legacy?payload.status?.orders:account.orders);
  apply(account.portfolio,rows.total);
  folderSets.set(folder.id,rows.byBot);
 }
 if(payload.accounting?.portfolio){
  const rows=gather(payload.status?.positions,payload.status?.orders);
  apply(payload.accounting.portfolio,rows.total);
  if(!folderSets.has('convexity'))folderSets.set('convexity',rows.byBot);
 }
 for(const bot of Array.isArray(payload.bots)?payload.bots:[]){
  if(bot.account)apply(bot.account,folderSets.get(bot.folder_id||'convexity')?.get(bot.id)||newSets());
 }
 return payload;
}

function draw(){
  const expandedPanels=expandedDashboardPanels();
 const status=data.status||{},health=data.health||{};
 $('health').textContent=(health.message||'Waiting for worker')+(data.historical_metrics_delayed?' · historical reports delayed':'');
 // At a glance describes strategies accepting new entries, not historical/paused portfolios.
 const activeOverview=(data.folders||[]).filter(folder=>(data.bots||[]).some(bot=>
  (bot.folder_id||'convexity')===folder.id&&bot.desired==='running'&&!bot.retired));
 $('accountSummary').innerHTML=data.folders?.length?folderOverviewMarkup(activeOverview,folderPeriod):accountMarkup(data.accounting,Date.now()/1000,status.positions||[]);
 $('diagnostics').innerHTML='<details class="panel compact-diagnostics" data-ui-panel="global:diagnostics"><summary>Strategy comparisons & monitoring</summary>'+sequentialComparisonMarkup(data.folders||[])+monitoringMarkup(status.monitoring)+'</details>';
 for(const b of document.querySelectorAll('[data-folder-period]'))b.onclick=()=>{folderPeriod=b.dataset.folderPeriod;for(const id of Object.keys(folderSummaryPeriods))delete folderSummaryPeriods[id];saveFolderViews();try{localStorage.setItem('moneytree-folder-period',folderPeriod)}catch{}draw()};
 $('connect').textContent=data.connection_configured?'Manage production data key':'Connect production Read key';
 const find=$('find').value.toLowerCase();
 // Keep paused strategy history accessible, but place it below strategies still running.
 const availableFolders=data.folders?.length?data.folders:[{id:'convexity',name:'Convexity',description:'',accounting:data.accounting}];
 const folders=[...availableFolders].sort((a,b)=>{
  const running=folder=>(data.bots||[]).some(bot=>(bot.folder_id||'convexity')===folder.id&&bot.desired==='running'&&!bot.retired);
  return Number(running(b))-Number(running(a));
 });
 $('groups').innerHTML=folders.map(folder=>{
  const folderBots=data.bots.filter(b=>(b.folder_id||'convexity')===folder.id).map(researchBot);
  const activeFolderBots=folderBots.filter(b=>!b.retired);
  const matching=folderBots.filter(b=>(b.name+' '+b.series).toLowerCase().includes(find));
  const bots=matching.filter(b=>!b.retired),retired=matching.filter(b=>b.retired);
  const money=folder.accounting,local=folder.id==='convexity'?status:{...status,positions:money?.positions||[],orders:money?.orders||[]};
  const running=activeFolderBots.filter(b=>b.desired==='running').length;
  // A collapsed folder does not need to build dozens of hidden, detailed bot cards.
  // On opening, the toggle handler redraws and restores every detailed card.
  const expandContent=openFolders.has(folder.id)||!!find||folderBots.length<=15;
  return `<details class="strategy-folder panel" id="folder-${e(folder.id)}" ${openFolders.has(folder.id)?'open':''} data-folder="${e(folder.id)}"><summary>${folderCardSummaryMarkup(folder,folderSummaryPeriods[folder.id]||folderPeriod,{bots:activeFolderBots.length,running,pending:pendingFolders.has(folder.id),controls:!!data.folders?.length})}</summary>${data.folders?.length?`<div class="folder-actions"><button data-folder-pause="${e(folder.id)}" class="secondary">Pause folder</button><button data-folder-resume="${e(folder.id)}" class="secondary">Resume folder</button>${folder.id==='volatility_scalper'?'<button data-volatility-family="pause" class="secondary">Pause all volatility</button><button data-volatility-family="resume" class="secondary">Resume all volatility</button>':''}<button data-folder-refill="${e(folder.id)}" class="secondary">Add funds</button><button data-folder-reset="${e(folder.id)}" class="secondary">Reset funds</button></div>`:'<p class="small">Strategy folders are waiting for the paper worker upgrade. Existing bots retain their current state.</p>'}<details class="advanced folder-account-breakdown" data-ui-panel="folder:${e(folder.id)}:account"><summary>Account breakdown</summary>${money?accountMarkup(money,Date.now()/1000,money.positions||status.positions||[]):'<p>Awaiting wallet snapshot</p>'}</details>${folder.id==='favorites_statistics'?'<details class="advanced folder-research" data-ui-panel="folder:'+e(folder.id)+':research"><summary>Statistics research</summary>'+favoriteStatisticsMatrixMarkup(folder.statistics,openResearch,folder.statistics_hold_summary,starredBuckets)+'</details>':''}${folder.id==='favorites'&&expandContent?'<details class="advanced folder-research" data-ui-panel="folder:'+e(folder.id)+':research"><summary>Favorites research · '+(favoriteTableMode==='wide'?'wide':favoriteTableMode==='single'?'single bucket':'detailed')+'</summary>'+favoriteProfitLegendMarkup(favoriteTableMode)+favoriteTableSettingsMarkup(favoriteTableMode)+(favoriteTableMode==='single'?favoriteSingleOverviewMarkup(folderBots,folder.collector_single_summary,openResearch,starredBuckets):favoriteTableMode==='wide'?favoriteWideOverviewMarkup(folderBots,folder.collector_wide_summary,openResearch,starredBuckets,{timed:folder.collector_timed_summary,single:folder.collector_single_summary}):favoriteCollectorOverviewMarkup(folderBots,openResearch,{loaded:folderResearchLoadedAt.has('favorites'),loading:loadingFolderResearch.has('favorites'),error:folderResearchErrors.get('favorites'),timedSummary:folder.collector_timed_summary,starredBuckets}))+'</details>':''}${folder.id==='convexity'?'<details class="advanced" data-ui-panel="folder:${e(folder.id)}:rules"><summary>Convexity strategy rules</summary><p class="small">10¢ maker bids, then 3¢ late bids; recovery targets at 40¢/50¢; freeze ordinary entries and exits in the final phase. Paused bots keep their history.</p></details>':''}<details class="advanced folder-diagnostics" data-ui-panel="folder:${e(folder.id)}:diagnostics"><summary>Strategy diagnostics</summary>${learningDiagnosticsMarkup(folder.learning)}${folder.strategy==='market_maker'?makerDiscoveryMarkup(folder.scanner):folder.scanner?`<p class="small">Scanner ${e(folder.scanner.state||'waiting')} · ${folder.scanner.subscribed_markets||0} markets</p>`:''}</details>${expandContent?marketTypeFolders(bots,local,folder.id,find,false,folder.id==='favorites'?folderBots:activeFolderBots,folder.collector_timed_summary,folder.collector_wide_summary):''}${retired.length&&expandContent?`<details class="advanced" data-ui-panel="folder:${e(folder.id)}:retired"><summary>Retired 15-minute bots · ${retired.length} · history and remaining exits</summary>${marketTypeFolders(retired,local,folder.id,find,true,folderBots.filter(b=>b.retired))}</details>`:''}</details>`;
 }).join('');
 for(const button of document.querySelectorAll('[data-favorite-table]'))button.onclick=()=>{favoriteTableMode=['detailed','wide','single'].includes(button.dataset.favoriteTable)?button.dataset.favoriteTable:'detailed';try{localStorage.setItem('moneytree-favorite-table-mode',favoriteTableMode)}catch{}draw()};
 for(const button of document.querySelectorAll('[data-favorite-star]'))button.onclick=event=>{
  event?.preventDefault?.();event?.stopPropagation?.();
  const key=button.dataset.favoriteStar;
  if(typeof key!=='string'||key.length>350)return;
  const marked=!starredBuckets.has(key);
  if(marked)starredBuckets.add(key);else starredBuckets.delete(key);
  saveFavoriteStars();
  button.textContent=marked?'★':'☆';
  button.classList?.toggle?.('is-starred',marked);
  button.setAttribute?.('aria-pressed',String(marked));
  button.setAttribute?.('aria-label',(marked?'Unstar ':'Star ')+(button.dataset.favoriteStarLabel||'research bucket'));
  button.title=marked?'Remove bucket star':'Star this bucket';
 };
 for(const detail of document.querySelectorAll('details[data-research]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false)return;const key=detail.dataset.research;if(detail.open)openResearch.add(key);else openResearch.delete(key);try{localStorage.setItem('moneytree-research-views',JSON.stringify([...openResearch]))}catch{}};
 for(const detail of document.querySelectorAll('details[data-market-type]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false||$('find').value.trim())return;const key=detail.dataset.marketType;if(detail.open)openMarketTypes.add(key);else openMarketTypes.delete(key);saveMarketTypeViews()};
 for(const detail of document.querySelectorAll('details[data-market]'))detail.ontoggle=event=>{if(event.target!==detail||detail.isConnected===false)return;const id=detail.dataset.market;if(detail.open)openMarkets.add(id);else openMarkets.delete(id);saveMarketViews()};
 for(const detail of document.querySelectorAll('details[data-folder]'))detail.ontoggle=()=>{if(detail.isConnected===false)return;const id=detail.dataset.folder;const changed=detail.open?!openFolders.has(id):openFolders.has(id);if(detail.open)openFolders.add(id);else openFolders.delete(id);saveFolderViews();if(changed){const opening=detail.open;draw();if(opening)void loadFolderResearch(id)}};
 for(const b of document.querySelectorAll('[data-folder-summary-period]'))b.onclick=event=>{event.preventDefault();event.stopPropagation();folderSummaryPeriods[b.dataset.summaryFolder]=b.dataset.folderSummaryPeriod;saveFolderViews();draw()};
 for(const b of document.querySelectorAll('[data-folder-pause]')){b.disabled=pendingFolders.has(b.dataset.folderPause);b.onclick=event=>{event?.preventDefault();event?.stopPropagation();return folderControl(b.dataset.folderPause,'pause')}}
 for(const b of document.querySelectorAll('[data-folder-resume]')){b.disabled=pendingFolders.has(b.dataset.folderResume);b.onclick=event=>{event?.preventDefault();event?.stopPropagation();return folderControl(b.dataset.folderResume,'resume')}}
 for(const b of document.querySelectorAll('[data-volatility-family]'))b.onclick=event=>{event.preventDefault();event.stopPropagation();return folderControl('volatility_all',b.dataset.volatilityFamily)}
 for(const b of document.querySelectorAll('[data-maker-market]'))b.onclick=async event=>{event.preventDefault();event.stopPropagation();try{const bot=data.bots.find(x=>x.id===b.dataset.makerMarket);await demoCall('shadow/bots/'+bot.id,{revision:bot.revision,market_ticker:b.dataset.ticker,market_desired:b.dataset.desired});await load()}catch(error){note(error.message)}};
 for(const b of document.querySelectorAll('[data-research-download]'))b.onclick=async()=>{try{const r=await demoCall('shadow/research/'+b.dataset.researchDownload),url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='money-tree-research-'+b.dataset.researchDownload+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){note(error.message)}};
 for(const b of document.querySelectorAll('[data-experiment-save]'))b.onclick=async()=>{try{const bot=data.bots.find(x=>x.id===b.dataset.experimentSave),config={};for(const input of document.querySelectorAll('[data-experiment-config]'))if(input.dataset.bot===bot.id)config[input.dataset.experimentConfig]=Number(input.value);await demoCall('shadow/bots/'+bot.id,{revision:bot.revision,config});note('Experimental parameters saved. Existing positions keep their entry configuration.');await load()}catch(error){note(error.message)}};
 for(const b of document.querySelectorAll('[data-folder-reset]'))b.onclick=()=>{
  resetFolder=b.dataset.folderReset;resetRequest=null;
  $('resetName').textContent=data.folders?.find(f=>f.id===resetFolder)?.name||resetFolder;
  $('resetDialog').showModal();
 };
 for(const button of document.querySelectorAll('[data-bot-summary]'))button.onclick=event=>{event.preventDefault();event.stopPropagation();periods[button.dataset.botSummary]=button.dataset.summaryPeriod;botSummaryPeriodPreferences(periods,true);draw()};
 for(const button of document.querySelectorAll('[data-toggle]'))button.onclick=()=>change(button.dataset.toggle,{desired:data.bots.find(b=>b.id===button.dataset.toggle).desired==='running'?'paused':'running'});
 for(const button of document.querySelectorAll('[data-save]'))button.onclick=()=>change(button.dataset.save,{contracts:Number([...document.querySelectorAll('[data-size]')].find(i=>i.dataset.size===button.dataset.save).value)});
 $('events').innerHTML='<table><thead><tr><th>Time</th><th>Strategy</th><th>Market</th><th>Event</th><th>Details</th></tr></thead><tbody>'+events.map(r=>`<tr><td>${e(new Date(r.time*1000).toLocaleString())}</td><td>${e(data.folders?.find(f=>f.id===(r.folder_id||'convexity'))?.name||'Convexity')}</td><td>${e(data.bots.find(b=>r.ticker?.startsWith(b.series+'-'))?.name||r.ticker||'Wallet')}</td><td>${e(r.event)}</td><td>${e([r.side,r.quantity,r.price?'$'+r.price:'',r.fee?'fee $'+r.fee:'',r.reason].filter(Boolean).join(' · '))}</td></tr>`).join('')+'</tbody></table>';
  restoreDashboardPanels(expandedPanels);
}
async function load(){
 void refreshWorkerRestarts();
 if(busy)return;busy=true;clearTimeout(timer);
 try{
  const result=await demoCall('shadow/workspace?version='+($('latest').checked?'latest':'full'));
  if(!result.installed){$('health').textContent='Worker initializing';loadNote('Shadow engine is initializing. Reload after the worker finishes its handover.');return}
  if(result.historical_metrics_delayed){
   loadNote('Current portfolio balances and Favorites research are available. Optional historical reports are delayed and will retry automatically.');
  }else{
   if(loadError&&$('message').textContent===loadError)note('');
   loadError=null;
  }
  data=hydrateEventCounts(result);draw();

  // The combined Favorites matrix must not depend on opening individual cards.
  void loadFolderResearch('favorites');
  for(const folder of openFolders)if(folder!=='favorites')void loadFolderResearch(folder);
  void refreshRecentActivity();
 }catch(error){
  loadNote(error.message);
  if(!data){
   // Legacy report aggregation can time out while the current wallet
   // checkpoint is perfectly healthy. Keep the money visible rather than
   // treating a delayed analytics query as missing portfolio data.
   let currentShown=false;
   try{
    const snapshot=await demoCall('shadow/portfolio-snapshot');
    if(snapshot.installed&&Array.isArray(snapshot.folders)&&snapshot.folders.length){
     $('health').textContent='Current balances available · historical analytics delayed';
     hydrateEventCounts(snapshot);
     $('accountSummary').innerHTML='<p class="small">Current paper account balances and positions are shown below. Historical research details are temporarily unavailable and will retry automatically.</p>'+folderOverviewMarkup(snapshot.folders,'all');
     $('groups').innerHTML='<p class="small">Detailed strategy tables are waiting for the historical reporting query. No balances or trade records have been reset.</p>';
     currentShown=true;
    }
   }catch{}
   if(!currentShown){
    $('health').textContent='Dashboard data unavailable';
    $('accountSummary').innerHTML='<p>Account data could not load. Retrying automatically. Use Reload data to try again.</p>';
   }
  }
 }finally{busy=false;timer=setTimeout(load,10000)}
}
async function change(id,fields){try{const bot=data.bots.find(b=>b.id===id);await demoCall('shadow/bots/'+id,{revision:bot.revision,...fields});note('Saved. New entries follow the worker’s next verified update; existing risk management continues.');await load()}catch(error){note(error.message)}}
$('find').oninput=()=>{if(data)draw()};$('latest').onchange=load;$('reload').onclick=load;
$('activity').ontoggle=()=>{if($('activity').open)return refreshRecentActivity(true)};
for(const [id,action] of [['pauseAll','pause'],['resumeAll','resume']])$(id).onclick=async()=>{try{await demoCall('shadow/bulk',{action});await load()}catch(error){note(error.message)}};
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
 try{await demoCall('shadow/bulk',{action,folder_id});const label=folder_id==='volatility_all'?'All volatility variants':(data.folders?.find(f=>f.id===folder_id)?.name||folder_id);note(label+(action==='pause'?': paused. The worker cancels pending buys and continues managing existing positions.':': resumed. New entries follow the worker’s next verified update.'));await load()}
 catch(error){note(error.message)}finally{pendingFolders.delete(folder_id);draw()}
}
// Folder cards are regenerated by draw() and by async research refreshes.
// A stable delegated capture handler survives those redraws and stops clicks
// from toggling a parent <details> instead of opening the refill dialog.
document.addEventListener('click',event=>{
 const button=event.target?.closest?.('[data-folder-refill]');
 if(!button)return;
 event.preventDefault();event.stopPropagation();
 try{
  refillFolder=button.dataset.folderRefill;
  refillRequest=null;
  const dialog=$('refillDialog');
  if(!dialog)throw Error('Refill form unavailable. Reload this page.');
  $('refillError').textContent='';
  $('refillName').textContent=data?.folders?.find(f=>f.id===refillFolder)?.name||refillFolder;
  if(!dialog.open)dialog.showModal();
 }catch(error){
  note('Could not open Add funds: '+error.message);
 }
},true);
$('refillForm').onsubmit=async event=>{
 event.preventDefault();
 const button=$('confirmRefill');button.disabled=true;
 try{
  const amount=Number($('refillAmount').value);
  const cents=Math.round(amount*100);
  if(!Number.isFinite(amount)||!Number.isSafeInteger(cents)||cents<1||cents>100000000)throw Error('Enter an amount from $0.01 to $1,000,000.');
  refillRequest=refillRequest||crypto.randomUUID();
  const folder=refillFolder;
  await demoCall('shadow/funds',{amount_cents:cents,folder_id:folder,request_id:refillRequest});
  refillRequest=null;
  $('refillDialog').close();
  note('Virtual refill queued for '+(data.folders?.find(f=>f.id===folder)?.name||folder)+'. Existing trades and P/L remain intact; the worker will apply the deposit shortly.');
  await load();
 }catch(error){
  // Never retry as an unscoped refill: the legacy endpoint would deposit
  // into Convexity rather than the selected strategy account.
  $('refillError').textContent=/^Invalid request$|^Invalid sign-in request$/i.test(error.message)
   ?'This server does not accept strategy-specific refills yet. No funds were added. The Render paper API needs the updated folder-refill endpoint; do not use the top Convexity refill as a workaround.'
   :error.message;
 }finally{button.disabled=false}
};
$('confirmReset').onclick=async()=>{const b=$('confirmReset');b.disabled=true;try{
 resetRequest=resetRequest||crypto.randomUUID();await demoCall('shadow/folders/'+resetFolder+'/reset',{request_id:resetRequest});
 $('resetDialog').close();note('Reset queued. The worker will archive this session and start a fresh $1,000 account with zero P/L.');await load();
}catch(error){$('resetError').textContent=error.message}finally{b.disabled=false}};
$('sessionHistory').onclick=async()=>{try{const r=await demoCall('shadow/sessions');
 $('sessionList').innerHTML=r.items.length?r.items.map(item=>`<p>${e(data.folders?.find(f=>f.id===item.folder_id)?.name||item.folder_id)} · ${e(new Date(item.ended_at*1000).toLocaleString())} <button class="secondary" data-session="${e(item.key)}">Download session</button></p>`).join(''):'<p>No previous reset sessions.</p>';
 for(const b of document.querySelectorAll('[data-session]'))b.onclick=async()=>{try{const r=await demoCall('shadow/sessions/'+b.dataset.session),url=URL.createObjectURL(new Blob([JSON.stringify(r.session,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='money-tree-paper-session-'+b.dataset.session+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){note(error.message)}};
 $('sessionsDialog').showModal();
}catch(error){note(error.message)}};

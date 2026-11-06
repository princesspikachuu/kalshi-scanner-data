import './order-detail.mjs';
import {createAuthClient} from './auth-client.mjs';
import {demoCall,escapeHTML as e,money,tradingNoticesMarkup,loadDemoSnapshots,botGroup,ordersForView,nextMarketBoundary,botExposure,botExposureMarkup,attentionInfo,attentionMarkup,resetMarkup,squarePerformanceMarkup,latestTransactionsMarkup,analysisVersionMarkup,analysisVersionPreference,botSummaryPeriodMarkup,botSummaryPeriodPreferences} from './demo-client.mjs';
import {openBotBuilder,duplicateBotConfig,restoreBotDraft,clearBotDraft,categories} from './bot-builder.mjs';
const $=id=>document.getElementById(id);let workspace,orders=[],period=localStorage.getItem('money-period')||'24H',busy=false,delay=15000,timer,draftChecked=false;
if(!['1H','6H','24H','7D','30D'].includes(period))period='24H';
let analysisVersion=analysisVersionPreference(),refreshRequested=false;
let summaryPeriods=botSummaryPeriodPreferences();
const performance=new Map(),exposureOpen=new Set();
const transactions=new Map();let boundaryTimer,haveOrders=false,lastLoadFailed=false;
const exposureOptions=()=>({health:workspace.health,view:$('marketView').value});
const setMessage=text=>$('message').textContent=text;
function group(bot){return botGroup(bot,workspace.health,orders)}
function draw(){
 clearTimeout(boundaryTimer);
 const boundary=nextMarketBoundary(orders,workspace.health);
 if(boundary)boundaryTimer=setTimeout(()=>{if(workspace)draw()},Math.min(2147483647,Math.max(1,boundary*1000-Date.now())));
 for(const id of exposureOpen)if(!workspace.bots.some(b=>b.key===id))exposureOpen.delete(id);
 for(const id of performance.keys())if(!workspace.bots.some(b=>b.key===id))performance.delete(id);
 for(const id of transactions.keys())if(!workspace.bots.some(b=>b.key===id))transactions.delete(id);
 $('versionOnly').checked=analysisVersion==='latest';
 $('resetStatus').innerHTML=resetMarkup(workspace.reset);
 const resetting=$('confirmReset').disabled||workspace.reset_mode!=='archive_copy';
 $('resetDemo').disabled=Boolean(resetting);$('resumeAll').disabled=false;

 $('paperMode').textContent=workspace.engine?.source==='production_paper'?'Production market data · Simulated orders and funds. Fills use later trades, shared volume and conservative queue estimates. Feed gaps pause fills. Additional modeled request latency: 250 ms. Starting bankroll '+money(workspace.engine.starting_cents)+'.':'Preparing the production-data paper engine. Figures below still belong to the previous Kalshi Demo until the transition completes.';
 const account=workspace.account;$('accountValue').textContent=money(account?.equity_cents);$('cash').textContent=money(account?.cash_cents);$('positions').textContent=money(account?.position_value_cents);$('accountChange').textContent=money(workspace.account_change_cents);$('fundsBalance').textContent=money(account?.cash_cents);
 $('accountTime').textContent=account?`Verified ${new Date(account.at*1000).toLocaleString()}`:'Connect production Read data to start the paper ledger.';
 const feed=workspace.health.stream||{},waiting=(workspace.health.blocked_markets||[]).filter(t=>!workspace.health.historical_markets?.includes(t)&&!workspace.health.syncing_markets?.includes(t)).length;
 const healthLabels={ready:'Trading worker connected',syncing:'Checking a recent order',attention:'Trading needs attention',reconnecting:'Reconnecting prices',reconciling:'Verifying orders and positions',waiting:'Waiting for worker',connection_required:'Connect production Read data',resetting:'Reset in progress'};
 $('health').textContent=(healthLabels[workspace.health.state]||'Checking trading status')+(waiting?` · ${waiting} markets waiting`:'')+(feed.outage_seconds>0?' · Prices reconnecting':'');$('health').className='health-pill '+workspace.health.state;
 $('connect').textContent=workspace.connection_configured?'Manage connection':'Connect account';
 const alerts=[...workspace.alerts];if(workspace.health.state==='connection_required')alerts.unshift({key:'connection',message:workspace.health.message,critical:false});
 const noticesOpen=$('alerts').querySelector?.('details')?.open||false;
 $('alerts').innerHTML=tradingNoticesMarkup(alerts,workspace.health,noticesOpen);
 const find=$('find').value.toLowerCase(),filter=$('filter').value;
 const bots=workspace.bots.filter(b=>b.config.name.toLowerCase().includes(find)&&(filter==='all'||filter==='archived'?filter==='all'||b.archived:!b.archived));
 const open=new Map([...$('groups').querySelectorAll('details[data-group]')].map(d=>[d.dataset.group,d.open]));
 $('groups').innerHTML=['Needs attention','Running','Paused'].map(name=>{const items=bots.filter(b=>group(b)===name);return `<details class="bot-group" data-group="${name}" ${open.get(name)??name!=='Paused'?'open':''}><summary>${name}<span class="count">${items.length}</span></summary><div class="bot-list">${items.length?items.map(card).join(''):`<div class="empty">${name==='Paused'?'No paused bots':name==='Running'?'Your running bots will appear here.':'Nothing needs your attention.'}</div>`}</div></details>`}).join('');
 if(!workspace.bots.length)$('groups').insertAdjacentHTML('afterbegin','<div class="empty"><strong>Your first bot starts with a condition.</strong>Choose price and time squares in Research, or add them in New bot. They share one configuration and account.</div>');
 for(const detail of document.querySelectorAll('[data-exposure]'))detail.ontoggle=()=>{const id=detail.dataset.exposure;if(detail.open){exposureOpen.add(id);detail.querySelector('[data-exposure-content]').innerHTML=exposureMarkup(orders.filter(o=>o.bot===id),id)}else{exposureOpen.delete(id);detail.querySelector('[data-exposure-content]').replaceChildren()}};
 for(const detail of document.querySelectorAll('[data-performance]')){
  detail.ontoggle=()=>{const state=performance.get(detail.dataset.performance)||{},wasOpen=state.open;state.open=detail.open;performance.set(detail.dataset.performance,state);if(detail.open&&!wasOpen)loadPerformance(detail.dataset.performance)};
  const id=detail.dataset.performance;
  if(detail.open&&!performance.get(id)?.data&&!performance.get(id)?.pending)loadPerformance(id,true);
  detail.querySelector('form').onsubmit=event=>{event.preventDefault();loadPerformance(id,true)};
  for(const input of detail.querySelectorAll('[data-performance-filter]'))input.onchange=()=>{
   const state=performance.get(id)||{};state.filters={...state.filters,[input.dataset.performanceFilter]:input.value};
   if(input.dataset.performanceFilter==='period'&&input.value!=='all'){
    state.filters.start='';state.filters.end='';for(const date of detail.querySelectorAll('input[type=date]'))date.value='';
   }else if(['start','end'].includes(input.dataset.performanceFilter)&&input.value){state.filters.period='all';detail.querySelector('[data-performance-filter=period]').value='all'}
   performance.set(id,state);
  };
 }
 for(const detail of document.querySelectorAll('[data-transactions]')){
  const id=detail.dataset.transactions;
  detail.ontoggle=()=>{const state=transactions.get(id)||{},wasOpen=state.open;state.open=detail.open;transactions.set(id,state);if(detail.open&&!wasOpen)loadTransactions(id)};
  detail.querySelector('button').onclick=()=>loadTransactions(id,true);
  if(detail.open)loadTransactions(id);
 }
 for(const button of document.querySelectorAll('[data-bot-summary]'))button.onclick=()=>{
  summaryPeriods[button.dataset.botSummary]=button.dataset.summaryPeriod;botSummaryPeriodPreferences(summaryPeriods);draw();
 };
 for(const button of document.querySelectorAll('[data-action]'))button.onclick=()=>control(button.dataset.bot,button.dataset.action,button);
 for(const button of document.querySelectorAll('[data-manage]'))button.onclick=()=>openBotBuilder({bot:workspace.bots.find(b=>b.key===button.dataset.manage),onSave:load});
 for(const button of document.querySelectorAll('[data-duplicate]'))button.onclick=()=>openBotBuilder({initialConfig:duplicateBotConfig(workspace.bots.find(b=>b.key===button.dataset.duplicate)),onSave:load});
 for(const button of document.querySelectorAll('[data-attention-action]'))button.onclick=async()=>{
  const action=button.dataset.attentionAction;
  if(action==='connection'){$('connectionDialog').showModal();return}
  if(action==='funds'){$('fundsDialog').showModal();return}
  button.disabled=true;try{await demoCall('refresh',{});setMessage('Verification requested. The worker will refresh exchange orders and positions.');await load()}catch(error){setMessage(error.message)}finally{button.disabled=false}
 };
 for(const button of document.querySelectorAll('[data-period]'))button.setAttribute('aria-pressed',String(button.dataset.period===period));
}
function attentionPanel(bot){return attentionMarkup(attentionInfo(bot,workspace.health,orders),{botId:bot.key})}
function card(bot){const summaryPeriod=summaryPeriods[bot.key]||'all',summary=workspace.summary_metrics?.[bot.key]?.[summaryPeriod],summaryPnl=workspace.summary_metrics?summary?.realized_cents??0:null;const own=orders.filter(o=>o.bot===bot.key),visible=ordersForView(own,workspace.health,$('marketView').value),name=group(bot),exposure=visible.filter(o=>o.kind==='entry').reduce((sum,o)=>sum+(o.remaining+Math.max(0,o.filled-(o.sold||0)))*o.price,0);return `<article class="bot-card"><div class="bot-top"><div><div class="bot-name">${e(bot.config.name)}</div><span class="small">${bot.config.strategy==='buy_low_sell_high'?'Buy '+bot.config.cycle_buy_cents+'¢'+(bot.config.cycle_exit_mode==='late_threshold'?' · hold / late exit below '+bot.config.late_exit_threshold_cents+'¢':' / sell '+bot.config.cycle_sell_cents+'¢'):bot.config.squares.length+' conditions'} · ${[...new Set(bot.config.squares.map(s=>s.asset))].map(asset=>e(categories[asset]||asset)).join(', ')}</span></div><span class="badge ${name==='Paused'?'paused':name==='Needs attention'?'attention':''}">${e(bot.archived?'Archived':name)}</span></div>${analysisVersionMarkup(bot.analysis_version_info,analysisVersion,true)}${botSummaryPeriodMarkup(bot.key,summaryPeriod)}<div class="bot-stats"><div><span>${$('marketView').value==='pending'?'Pending commitment':'Active commitment'}</span><strong>${haveOrders?money(exposure):'—'}</strong></div><div><span>${$('marketView').value==='pending'?'Pending buy records':'Buy orders'}</span><strong>${haveOrders?botExposure(own,exposureOptions()).buys.length:'—'}</strong></div><div><span>Net realized · ${summaryPeriod==='all'?'Lifetime':summaryPeriod}${analysisVersion==='latest'?' · latest version':''}</span><strong>${money(summaryPnl)}</strong></div><div><span>Account limit</span><strong>${bot.config.bot_percent}%</strong></div></div>${bot.config.squares.some(s=>s.asset==='sports')?'<p class="small">Sports entry windows use Kalshi’s estimated finish. Existing positions stay protected until the market actually closes.</p>':''}${name==='Needs attention'?attentionPanel(bot):''}<div class="bot-footer"><span class="small">${e(bot.desired==='running'?(workspace.health.state==='reconnecting'?'Reconnecting price stream · entries resume after fresh verified prices':name==='Running'?exposureSummary(own):workspace.health.message):'New entries paused · protective exits continue')}</span><div class="row"><button data-bot="${bot.key}" data-action="${bot.desired==='running'?'pause':'resume'}">${bot.desired==='running'?'Pause':'Resume'}</button><button class="secondary" data-manage="${bot.key}">Manage</button><button class="secondary" data-duplicate="${bot.key}">Duplicate</button></div></div>${exposurePanel(bot,own)}${performancePanel(bot)}${transactionsPanel(bot)}</article>`}
function exposureMarkup(own,id){return haveOrders?botExposureMarkup(own,id,exposureOptions()):'<p class="message" role="status">Orders and positions have not loaded. Retrying; this does not mean there are no positions.</p>'}
function exposureSummary(own){if(!haveOrders)return 'Orders and positions temporarily unavailable · retrying';const {positions,buys,sells}=botExposure(own,exposureOptions());return `${$('marketView').value==='pending'?'Pending resolution':'Active markets'} · ${buys.length} buy orders · ${positions.length} held positions · ${sells.length} sell orders`}
function exposurePanel(bot,own){const {positions,buys,sells}=botExposure(own,exposureOptions()),open=exposureOpen.has(bot.key);return `<details class="advanced" data-exposure="${e(bot.key)}" ${open?'open':''}><summary>${!haveOrders?'Orders and positions · unavailable':`${$('marketView').value==='pending'?'Pending':'Active markets'} · ${positions.length} positions · ${buys.length} buys · ${sells.length} sells`}</summary><div data-exposure-content>${open?exposureMarkup(own,bot.key):''}</div></details>`}
function performancePanel(bot){
 const state=performance.get(bot.key),f=state?.filters||{};
 const timeGroup=bot.config.strategy==='buy_low_sell_high'?'time_price':'time';
 const options=[['square','Square'],[timeGroup,'Time remaining at entry'],['hour','Local hour of entry']].map(([value,label])=>`<option value="${value}" ${(f.group||(bot.config.strategy==='buy_low_sell_high'?'time_price':'square'))===value?'selected':''}>${label}</option>`).join('');
 return `<details class="advanced" data-performance="${e(bot.key)}" ${state?.open?'open':''}><summary>Performance by square or time</summary><form class="row" data-performance-filters><label>Group by<select data-performance-filter="group">${options}</select></label><label>Entries from<select data-performance-filter="period">${[['all','Lifetime / custom dates'],['1H','Last hour'],['6H','Last 6 hours'],['24H','Last day'],['7D','Last week'],['30D','Last month (30 days)']].map(([value,label])=>`<option value="${value}" ${(f.period||'all')===value?'selected':''}>${label}</option>`).join('')}</select></label><label>From<input type="date" data-performance-filter="start" value="${e(f.start||'')}"></label><label>Through<input type="date" data-performance-filter="end" value="${e(f.end||'')}"></label><label>Timezone<select data-performance-filter="timezone"><option value="America/Los_Angeles" ${(f.timezone||'America/Los_Angeles')==='America/Los_Angeles'?'selected':''}>Pacific time</option><option value="UTC" ${f.timezone==='UTC'?'selected':''}>UTC</option></select></label><button class="secondary" type="submit" ${state?.pending?'disabled':''}>Apply / refresh statistics</button></form><div data-performance-content>${state?.data?squarePerformanceMarkup(state.data):'<p class="small">Expand to load saved statistics. Dates filter when entries were submitted.</p>'}</div></details>`
}
async function loadPerformance(id,force=false){
 const state=performance.get(id)||{};performance.set(id,state);
 if(state.pending||(!force&&state.data&&Date.now()-state.loaded<60000))return;
 state.pending=true;
 const content=()=>[...document.querySelectorAll('[data-performance]')].find(d=>d.dataset.performance===id);
 if(content())content().querySelector('button').disabled=true;
 const requestedVersion=analysisVersion,requestedRevision=workspace.bots.find(b=>b.key===id)?.revision;
 const query=new URLSearchParams({bot:id,version:requestedVersion,group:workspace.bots.find(b=>b.key===id)?.config.strategy==='buy_low_sell_high'?'time_price':'square',...state.filters});
 try{const data=await demoCall('performance?'+query);if(requestedVersion!==analysisVersion||requestedVersion==='latest'&&requestedRevision!==workspace.bots.find(b=>b.key===id)?.revision)return;state.data=data;state.loaded=Date.now();if(content())content().querySelector('[data-performance-content]').innerHTML=squarePerformanceMarkup(state.data)}
 catch(error){if(content())content().querySelector('[data-performance-content]').textContent=error.message}
 finally{state.pending=false;if(content())content().querySelector('button').disabled=false;if(requestedVersion!==analysisVersion||requestedVersion==='latest'&&requestedRevision!==workspace.bots.find(b=>b.key===id)?.revision)loadPerformance(id,true)}
}
function transactionsPanel(bot){const state=transactions.get(bot.key);return `<details class="advanced" data-transactions="${e(bot.key)}" ${state?.open?'open':''}><summary>Latest transactions</summary><div data-transactions-content>${state?.data?latestTransactionsMarkup(state.data,bot.key):'<p class="small">Expand to load this bot’s latest transactions.</p>'}</div><button class="secondary" type="button" ${state?.pending?'disabled':''}>Refresh transactions</button></details>`}
async function loadTransactions(id,force=false){
 const state=transactions.get(id)||{};transactions.set(id,state);
 if(state.pending||(!force&&state.data&&Date.now()-state.loaded<60000))return;
 state.pending=true;
 const content=()=>[...document.querySelectorAll('[data-transactions]')].find(d=>d.dataset.transactions===id);
 if(content())content().querySelector('button').disabled=true;
 const requestedVersion=analysisVersion,requestedRevision=workspace.bots.find(b=>b.key===id)?.revision;
 try{const data=await demoCall('activity?'+new URLSearchParams({bot:id,kind:'transactions',version:requestedVersion}));if(requestedVersion!==analysisVersion||requestedVersion==='latest'&&requestedRevision!==workspace.bots.find(b=>b.key===id)?.revision)return;state.data=data;state.loaded=Date.now();state.data.loadedAt=state.loaded;if(content())content().querySelector('[data-transactions-content]').innerHTML=latestTransactionsMarkup(state.data,id)}
 catch(error){if(content())content().querySelector('[data-transactions-content]').textContent=error.message}
 finally{state.pending=false;if(content())content().querySelector('button').disabled=false;if(requestedVersion!==analysisVersion||requestedVersion==='latest'&&requestedRevision!==workspace.bots.find(b=>b.key===id)?.revision)loadTransactions(id,true)}
}
async function control(id,action,button){const bot=workspace.bots.find(b=>b.key===id);button.disabled=true;try{await demoCall(`bots/${id}/control`,{action,revision:bot.revision});setMessage(action==='pause'?'Pause requested. Open bids will be canceled; filled entries remain protected.':'Resume requested. Entries wait for verified exchange state.');await load()}catch(error){setMessage(error.message)}finally{button.disabled=false}}
async function load(){
 if(busy){refreshRequested=true;return}busy=true;
 const requestedVersion=analysisVersion;
 try{
  const result=await loadDemoSnapshots(demoCall,period,requestedVersion);
  if(requestedVersion!==analysisVersion){refreshRequested=true;return}
  if(result.workspace){
   if(analysisVersion==='latest')for(const bot of result.workspace.bots){
    if(workspace?.bots.find(b=>b.key===bot.key)?.revision!==bot.revision){
     for(const state of [performance.get(bot.key),transactions.get(bot.key)])if(state){state.data=null;state.loaded=0}
    }
   }
   workspace=result.workspace;
  }
  if(result.orders){orders=result.orders.items;haveOrders=true}
  if(workspace){
   draw();
   if(!draftChecked){draftChecked=true;restoreBotDraft({bots:workspace.bots,onSave:load})}
  }else $('groups').innerHTML='<div class="empty">Bot data could not be loaded. Your saved bots have not been removed. Retrying automatically; use Reload data to try now.</div>';
  if(result.errors.length){
   setMessage(result.errors.join(' · ')+(workspace?' · Showing the latest data that loaded successfully.':''));lastLoadFailed=true;delay=30000;
  }else{if(lastLoadFailed)setMessage('');lastLoadFailed=false;delay=15000}
  if(workspace&&$('equityDetails').open)await chart();
 }catch(error){setMessage('Dashboard could not finish loading: '+error.message);lastLoadFailed=true;delay=30000}
 finally{busy=false;clearTimeout(timer);if(!document.hidden)timer=setTimeout(load,refreshRequested?0:delay);refreshRequested=false}
}
async function chart(){try{const data=await demoCall('chart?period='+period);const points=data.points;if(points.length<2){$('equityChart').innerHTML='<p class="small">Account history appears after two verified snapshots, taken 15 minutes apart.</p>';$('accountChange').textContent='—';return}const values=points.map(p=>p.value),low=Math.min(...values),range=Math.max(100,Math.max(...values)-low),path=points.map((p,i)=>`${i?'L':'M'} ${10+i*780/(points.length-1)} ${175-(p.value-low)*150/range}`).join(' ');$('equityChart').innerHTML=`<svg class="chart" viewBox="0 0 800 190" role="img" aria-label="Verified Demo account value over ${period}"><line x1="0" y1="175" x2="800" y2="175"/><path d="${path}"/></svg>`;$('accountChange').textContent=money(values.at(-1)-values[0])}catch(error){setMessage(error.message)}}
let resetRequestId;
const resetConfirmed=()=>$('resetPhrase').value==='RESET BOTS'&&$('resetAcknowledge').checked;
const refreshResetConfirmation=()=>$('confirmReset').disabled=!resetConfirmed();
$('resetPhrase').oninput=refreshResetConfirmation;
$('resetAcknowledge').onchange=refreshResetConfirmation;
$('resetDialog').addEventListener('close',()=>{$('resetPhrase').value='';$('resetAcknowledge').checked=false;$('confirmReset').disabled=true});
$('resetDemo').onclick=()=>{
 resetRequestId=crypto.randomUUID();$('resetMessage').textContent='';
 $('resetPhrase').value='';$('resetAcknowledge').checked=false;$('confirmReset').disabled=true;
 $('resetTargetCount').textContent=workspace.bots.filter(b=>!b.archived).length+' current';
 $('resetDialog').showModal();
};
$('resetForm').onsubmit=async event=>{
 event.preventDefault();if(!resetConfirmed())return;
 $('confirmReset').disabled=true;
 try{await demoCall('reset',{request_id:resetRequestId,confirmation:'RESET BOTS'});$('resetDialog').close();setMessage('Bots archived and fresh paused copies created. Use Undo reset if unintended.');await load()}
 catch(error){$('resetMessage').textContent=error.message}finally{$('confirmReset').disabled=!resetConfirmed();$('resetDemo').disabled=workspace.reset_mode!=='archive_copy'}
};
$('resetStatus').addEventListener('click',async event=>{
 if(event.target.id!=='undoLatestReset')return;
 const id=workspace.reset?.request_id;
 if(!id)return;
 event.target.disabled=true;
 try{
  const result=await demoCall('reset/undo',{request_id:id});
  setMessage('Original bots restored ('+result.restored+'). Exchange orders and positions were not changed.');
  await load();
 }catch(error){setMessage(error.message);event.target.disabled=false}
});
$('newBot').onclick=()=>openBotBuilder({onSave:load});$('find').oninput=draw;$('filter').onchange=draw;
$('funds').onclick=()=>$('fundsDialog').showModal();$('connect').onclick=()=>$('connectionDialog').showModal();
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>$(button.dataset.close).close();
for(const id of ['refreshBalance','fundsRefresh'])$(id).onclick=async()=>{try{await demoCall('refresh',{});setMessage('Paper balance refresh requested. No real account balance is used.');await load()}catch(error){setMessage(error.message)}};
$('equityDetails').ontoggle=()=>{if($('equityDetails').open)chart()};
$('versionOnly').onchange=async()=>{
 analysisVersion=$('versionOnly').checked?'latest':'full';analysisVersionPreference(analysisVersion);
 for(const state of [...performance.values(),...transactions.values()]){state.data=null;state.loaded=0}
 if(workspace){workspace.metrics={};workspace.summary_metrics=null;draw()}
 await load();
};
for(const button of document.querySelectorAll('[data-period]'))button.onclick=()=>{period=button.dataset.period;localStorage.setItem('money-period',period);load()};
for(const [id,action] of [['pauseAll','pause'],['resumeAll','resume']])$(id).onclick=async()=>{const items=workspace.bots.filter(b=>!b.archived&&(action==='pause'?b.desired==='running':b.desired!=='running'));if(!items.length||!confirm(`${action==='pause'?'Pause':'Resume'} all ${items.length} bots? ${action==='pause'?'Unfilled entries will be canceled. Protective exits continue.':'Entries resume only after verified recovery.'}`))return;$(id).disabled=true;try{await demoCall('bulk',{action,bots:items.map(b=>({id:b.key,revision:b.revision}))});await load()}catch(error){setMessage(error.message)}finally{$(id).disabled=false}};
$('paperKeyFile').onchange=async()=>{const file=$('paperKeyFile').files[0];if(!file)return;if(file.size>12000){$('connectionMessage').textContent='Key file must be at most 12 KB.';return}$('demoPem').value=await file.text()};
$('connectionForm').onsubmit=async event=>{event.preventDefault();$('saveConnection').disabled=true;try{await demoCall('paper-connection',{key_id:$('demoKey').value.trim(),private_key:$('demoPem').value.trim()});$('demoPem').value='';$('demoKey').value='';$('connectionDialog').close();setMessage('Production Read connection saved. Paper simulation will start after the feed is verified.');await load()}catch(error){$('connectionMessage').textContent=error.message}finally{$('demoPem').value='';$('paperKeyFile').value='';$('saveConnection').disabled=false}};
$('virtualFundsForm').onsubmit=async event=>{event.preventDefault();event.submitter.disabled=true;try{await demoCall('virtual-funds',{amount_cents:Math.round(Number($('virtualAmount').value)*100)});$('fundsDialog').close();await load();setMessage('Virtual funds added. No real money moved.')}catch(error){$('virtualFundsMessage').textContent=error.message}finally{event.submitter.disabled=false}};
let legacyBefore=null;
$('legacyLoad').onclick=async()=>{const button=$('legacyLoad');button.disabled=true;try{const result=await demoCall('legacy'+(legacyBefore?'?before='+encodeURIComponent(legacyBefore):''));if(!legacyBefore)$('legacyRecords').innerHTML='<table><thead><tr><th>Time</th><th>Previous record</th><th>Details</th></tr></thead><tbody></tbody></table>';$('legacyRecords').querySelector('tbody').insertAdjacentHTML('beforeend',result.items.map(r=>`<tr><td>${e(new Date(r.created_at).toLocaleString())}</td><td>${e(r.record_type)} · ${e(r.parameters.config?.name||r.parameters.kind||r.progress.kind||'Record')}</td><td>${e(r.parameters.ticker||'')} ${e(r.progress.message||r.parameters.summary||r.progress.status||'')}${Number.isFinite(r.progress.realized_cents)?' · '+money(r.progress.realized_cents):''}</td></tr>`).join(''));legacyBefore=result.next_before;button.textContent=legacyBefore?'Load older records':'All previous records loaded';button.disabled=!legacyBefore}catch(error){setMessage(error.message);button.disabled=false}};
$('reloadData').onclick=()=>load();
$('marketView').onchange=()=>{if(workspace)draw()};
$('signOut').onclick=async()=>{clearBotDraft();await createAuthClient().signOut();location.replace('/')};
document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)load()});
load();

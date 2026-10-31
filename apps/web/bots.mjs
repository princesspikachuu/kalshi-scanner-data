import {createAuthClient} from './auth-client.mjs';
import {demoCall,escapeHTML as e,money,attentionInfo,attentionMarkup,resetMarkup,squarePerformanceMarkup} from './demo-client.mjs';
import {openBotBuilder,duplicateBotConfig,restoreBotDraft,clearBotDraft} from './bot-builder.mjs';
const $=id=>document.getElementById(id);let workspace,orders=[],period=localStorage.getItem('money-period')||'24H',busy=false,delay=15000,timer,draftChecked=false;
if(!['24H','7D','30D'].includes(period))period='24H';
const performance=new Map();
const setMessage=text=>$('message').textContent=text;
function group(bot){if(bot.desired!=='running')return 'Paused';if(workspace.health.bots?.[bot.key]?.exit_waiting||workspace.health.state!=='ready'||workspace.health.blocked_markets?.some(t=>orders.some(o=>o.bot===bot.key&&o.ticker===t)))return 'Needs attention';return 'Running'}
function draw(){
 for(const id of performance.keys())if(!workspace.bots.some(b=>b.key===id))performance.delete(id);
 $('resetStatus').innerHTML=resetMarkup(workspace.reset);
 const resetting=$('confirmReset').disabled||workspace.reset_mode!=='archive_copy';
 $('resetDemo').disabled=Boolean(resetting);$('resumeAll').disabled=false;

 const account=workspace.account;$('accountValue').textContent=money(account?.equity_cents);$('cash').textContent=money(account?.cash_cents);$('positions').textContent=money(account?.position_value_cents);$('accountChange').textContent=money(workspace.account_change_cents);$('fundsBalance').textContent=money(account?.cash_cents);
 $('accountTime').textContent=account?`Verified ${new Date(account.at*1000).toLocaleString()}`:'Connect your Demo account to load its actual balance.';
 $('health').textContent=workspace.health.message;$('health').className='health-pill '+workspace.health.state;
 $('connect').textContent=workspace.connection_configured?'Manage connection':'Connect account';
 const alerts=[...workspace.alerts];if(workspace.health.state==='connection_required')alerts.unshift({key:'connection',message:workspace.health.message,critical:false});
 $('alerts').innerHTML=alerts.map(a=>`<div class="alert ${a.critical?'critical':''}"><span>${e(a.message)}</span><a href="/activity#settings">Review</a></div>`).join('');
 const find=$('find').value.toLowerCase(),filter=$('filter').value;
 const bots=workspace.bots.filter(b=>b.config.name.toLowerCase().includes(find)&&(filter==='all'||filter==='archived'?filter==='all'||b.archived:!b.archived));
 const open=new Map([...$('groups').querySelectorAll('details[data-group]')].map(d=>[d.dataset.group,d.open]));
 $('groups').innerHTML=['Needs attention','Running','Paused'].map(name=>{const items=bots.filter(b=>group(b)===name);return `<details class="bot-group" data-group="${name}" ${open.get(name)??name!=='Paused'?'open':''}><summary>${name}<span class="count">${items.length}</span></summary><div class="bot-list">${items.length?items.map(card).join(''):`<div class="empty">${name==='Paused'?'No paused bots':name==='Running'?'Your running bots will appear here.':'Nothing needs your attention.'}</div>`}</div></details>`}).join('');
 if(!workspace.bots.length)$('groups').insertAdjacentHTML('afterbegin','<div class="empty"><strong>Your first bot starts with a condition.</strong>Choose price and time squares in Research, or add them in New bot. They share one configuration and account.</div>');
 for(const detail of document.querySelectorAll('[data-performance]')){
  detail.ontoggle=()=>{const state=performance.get(detail.dataset.performance)||{},wasOpen=state.open;state.open=detail.open;performance.set(detail.dataset.performance,state);if(detail.open&&!wasOpen)loadPerformance(detail.dataset.performance)};
  detail.querySelector('button').onclick=()=>loadPerformance(detail.dataset.performance,true);
 }
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
function card(bot){const own=orders.filter(o=>o.bot===bot.key),name=group(bot),exposure=own.filter(o=>o.kind==='entry').reduce((sum,o)=>sum+(o.remaining+Math.max(0,o.filled-(o.sold||0)))*o.price,0);return `<article class="bot-card"><div class="bot-top"><div><div class="bot-name">${e(bot.config.name)}</div><span class="small">${bot.config.squares.length} conditions · ${[...new Set(bot.config.squares.map(s=>s.asset))].map(e).join(', ')} · v${bot.revision}</span></div><span class="badge ${name==='Paused'?'paused':name==='Needs attention'?'attention':''}">${e(bot.archived?'Archived':name)}</span></div><div class="bot-stats"><div><span>Allocated exposure</span><strong>${money(exposure)}</strong></div><div><span>Resting bids</span><strong>${own.filter(o=>o.kind==='entry'&&o.remaining>0).length}</strong></div><div><span>Net realized · ${period}</span><strong>${money(workspace.metrics[bot.key]?.realized_cents??null)}</strong></div><div><span>Account limit</span><strong>${bot.config.bot_percent}%</strong></div></div>${name==='Needs attention'?attentionPanel(bot):''}<div class="bot-footer"><span class="small">${e(bot.desired==='running'?(name==='Running'?(workspace.health.bots?.[bot.key]?.message||'Watching for qualifying conditions'):workspace.health.message):'New entries paused · protective exits continue')}</span><div class="row"><button data-bot="${bot.key}" data-action="${bot.desired==='running'?'pause':'resume'}">${bot.desired==='running'?'Pause':'Resume'}</button><button class="secondary" data-manage="${bot.key}">Manage</button><button class="secondary" data-duplicate="${bot.key}">Duplicate</button></div></div>${performancePanel(bot)}</article>`}
function performancePanel(bot){const state=performance.get(bot.key);return `<details class="advanced" data-performance="${e(bot.key)}" ${state?.open?'open':''}><summary>Performance by square · lifetime</summary><div data-performance-content>${state?.data?squarePerformanceMarkup(state.data):'<p class="small">Expand to load saved square statistics.</p>'}</div><button class="secondary" type="button" ${state?.pending?'disabled':''}>Refresh square statistics</button></details>`}
async function loadPerformance(id,force=false){
 const state=performance.get(id)||{};performance.set(id,state);
 if(state.pending||(!force&&state.data&&Date.now()-state.loaded<60000))return;
 state.pending=true;
 const content=()=>[...document.querySelectorAll('[data-performance]')].find(d=>d.dataset.performance===id);
 if(content())content().querySelector('button').disabled=true;
 try{state.data=await demoCall('performance?bot='+encodeURIComponent(id));state.loaded=Date.now();if(content())content().querySelector('[data-performance-content]').innerHTML=squarePerformanceMarkup(state.data)}
 catch(error){if(content())content().querySelector('[data-performance-content]').textContent=error.message}
 finally{state.pending=false;if(content())content().querySelector('button').disabled=false}
}
async function control(id,action,button){const bot=workspace.bots.find(b=>b.key===id);button.disabled=true;try{await demoCall(`bots/${id}/control`,{action,revision:bot.revision});setMessage(action==='pause'?'Pause requested. Open bids will be canceled; filled entries remain protected.':'Resume requested. Entries wait for verified exchange state.');await load()}catch(error){setMessage(error.message)}finally{button.disabled=false}}
async function load(){if(busy)return;busy=true;try{[workspace,{items:orders}]=await Promise.all([demoCall('workspace?period='+period),demoCall('orders')]);draw();if(!draftChecked){draftChecked=true;restoreBotDraft({bots:workspace.bots,onSave:load})}delay=15000;if($('equityDetails').open)await chart()}catch(error){setMessage(error.message);delay=Math.min(120000,delay*2)}finally{busy=false;clearTimeout(timer);if(!document.hidden)timer=setTimeout(load,delay)}}
async function chart(){try{const data=await demoCall('chart?period='+period);const points=data.points;if(points.length<2){$('equityChart').innerHTML='<p class="small">Account history appears after two verified snapshots, taken 15 minutes apart.</p>';$('accountChange').textContent='—';return}const values=points.map(p=>p.value),low=Math.min(...values),range=Math.max(100,Math.max(...values)-low),path=points.map((p,i)=>`${i?'L':'M'} ${10+i*780/(points.length-1)} ${175-(p.value-low)*150/range}`).join(' ');$('equityChart').innerHTML=`<svg class="chart" viewBox="0 0 800 190" role="img" aria-label="Verified Demo account value over ${period}"><line x1="0" y1="175" x2="800" y2="175"/><path d="${path}"/></svg>`;$('accountChange').textContent=money(values.at(-1)-values[0])}catch(error){setMessage(error.message)}}
let resetRequestId;
$('resetDemo').onclick=()=>{resetRequestId=crypto.randomUUID();$('resetMessage').textContent='';$('resetDialog').showModal()};
$('resetForm').onsubmit=async event=>{
 event.preventDefault();$('confirmReset').disabled=true;
 try{await demoCall('reset',{request_id:resetRequestId});$('resetDialog').close();setMessage('Bots archived and fresh paused copies created. You can resume them now.');await load()}
 catch(error){$('resetMessage').textContent=error.message}finally{$('confirmReset').disabled=false;$('resetDemo').disabled=workspace.reset_mode!=='archive_copy'}
};
$('newBot').onclick=()=>openBotBuilder({onSave:load});$('find').oninput=draw;$('filter').onchange=draw;
$('copyDemoCard').onclick=async()=>{try{await navigator.clipboard.writeText('4000056655665556');$('copyCardStatus').textContent='Test card number copied.'}catch{$('copyCardStatus').textContent='Copy this number: 4000 0566 5566 5556'}};
$('funds').onclick=()=>$('fundsDialog').showModal();$('connect').onclick=()=>$('connectionDialog').showModal();
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>$(button.dataset.close).close();
for(const id of ['refreshBalance','fundsRefresh'])$(id).onclick=async()=>{try{await demoCall('refresh',{});setMessage('Balance refresh requested. The worker will verify it with Kalshi Demo.');await load()}catch(error){setMessage(error.message)}};
$('equityDetails').ontoggle=()=>{if($('equityDetails').open)chart()};
for(const button of document.querySelectorAll('[data-period]'))button.onclick=()=>{period=button.dataset.period;localStorage.setItem('money-period',period);load()};
for(const [id,action] of [['pauseAll','pause'],['resumeAll','resume']])$(id).onclick=async()=>{const items=workspace.bots.filter(b=>!b.archived&&(action==='pause'?b.desired==='running':b.desired!=='running'));if(!items.length||!confirm(`${action==='pause'?'Pause':'Resume'} all ${items.length} bots? ${action==='pause'?'Unfilled entries will be canceled. Protective exits continue.':'Entries resume only after verified recovery.'}`))return;$(id).disabled=true;try{await demoCall('bulk',{action,bots:items.map(b=>({id:b.key,revision:b.revision}))});await load()}catch(error){setMessage(error.message)}finally{$(id).disabled=false}};
$('connectionForm').onsubmit=async event=>{event.preventDefault();$('saveConnection').disabled=true;try{await demoCall('connection',{key_id:$('demoKey').value.trim(),private_key:$('demoPem').value.trim()});$('demoPem').value='';$('demoKey').value='';$('connectionDialog').close();setMessage('Connection saved. Waiting for exchange verification.');await load()}catch(error){$('connectionMessage').textContent=error.message}finally{$('saveConnection').disabled=false}};
$('signOut').onclick=async()=>{clearBotDraft();await createAuthClient().signOut();location.replace('/')};
document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)load()});
load();

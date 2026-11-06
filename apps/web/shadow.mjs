import {demoCall,escapeHTML as e,botSummaryPeriodMarkup,botSummaryPeriodPreferences} from './demo-client.mjs';
import {createAuthClient} from './auth-client.mjs';
const $=id=>document.getElementById(id),periods=botSummaryPeriodPreferences();
const dollars=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
let data,events=[],timer,busy=false,requestId=null;
const note=value=>$('message').textContent=value;
function draw(){
 const status=data.status||{},health=data.health||{};
 $('health').textContent=health.message||'Waiting for worker';
 $('cash').textContent=dollars(status.virtual_cash);$('available').textContent=dollars(status.available_cash);
 $('equity').textContent=dollars(status.equity??status.virtual_cash);$('positions').textContent=status.open_contracts||'0';
 $('connect').textContent=data.connection_configured?'Manage production data key':'Connect production Read key';
 const find=$('find').value.toLowerCase();
 $('groups').innerHTML='<div class="bot-list">'+data.bots.filter(b=>(b.name+' '+b.series).toLowerCase().includes(find)).map(bot=>{
  const selected=periods[bot.id]||'all',metrics=bot.metrics[selected],ticker=status.selected?.[bot.series];
  const market=status.market_states?.[ticker],active=market&&market.close>Date.now()/1000;
  const positions=(status.positions||[]).filter(p=>p.ticker.startsWith(bot.series+'-'));
  const orders=(status.orders||[]).filter(o=>o.ticker.startsWith(bot.series+'-'));
  const state=bot.desired==='paused'?'Paused':!data.connection_configured?'Connect data':ticker?active?'Active market':'Settlement pending':'Waiting for active market';
  const stats=[['Net realized PnL',dollars(metrics.net_realized_pnl)],['Gross profit',dollars(metrics.gross_profit)],['Fees paid',dollars(metrics.fees)],['Win rate',metrics.win_rate===null?'—':Number(metrics.win_rate).toFixed(1)+'%'],['Reported cycles',metrics.cycles],['Data-gap cycles',metrics.excluded_cycles]];
  return `<article class="bot-card"><div class="bot-top"><div><div class="bot-name">${e(bot.name)}</div><p class="small">10¢ → 3¢ · conditional IOC exit · final freeze</p></div><span class="badge ${bot.desired==='paused'?'paused':''}">${e(state)}</span></div><p class="small">${data.version==='latest'?'Most recent version · v'+bot.revision:'Full shadow history'} · ${new Date(bot.changed_at*1000).toLocaleString()}</p>${botSummaryPeriodMarkup(bot.id,selected)}<div class="bot-stats">${stats.map(([label,value])=>`<div><span>${e(label)}</span><strong>${e(value)}</strong></div>`).join('')}</div><p class="small">${e(ticker||bot.series)}${market&&!market.data_valid?' · Current cycle excluded after a data gap':''}</p><details class="advanced"><summary>${positions.length} position lots · ${orders.length} pending/resting orders</summary><div class="table-scroll"><table><thead><tr><th>Type</th><th>Side</th><th>Contracts</th><th>State</th></tr></thead><tbody>${positions.map(p=>`<tr><td>Position${active?'':' · pending'}</td><td>${e(p.side.toUpperCase())}</td><td>${e(p.quantity)}</td><td>${p.is_armed?'Armed':'Not armed'} · Phase ${e(p.phase_origin)}</td></tr>`).join('')}${orders.map(o=>`<tr><td>${e(o.action)} · ${o.maker?'Maker':'IOC'}</td><td>${e(o.side.toUpperCase())}</td><td>${e(o.quantity)}</td><td>${e(o.status)} @ ${e((Number(o.price)*100).toFixed(2))}¢</td></tr>`).join('')}</tbody></table></div></details><div class="bot-footer"><button data-toggle="${e(bot.id)}">${bot.desired==='running'?'Pause':'Resume'}</button><label>Contracts / order<input data-size="${e(bot.id)}" type="number" min="1" max="10000" value="${bot.contracts}"></label><button class="secondary" data-save="${e(bot.id)}">Save new version</button></div></article>`;
 }).join('')+'</div>';
 for(const button of document.querySelectorAll('[data-bot-summary]'))button.onclick=()=>{periods[button.dataset.botSummary]=button.dataset.summaryPeriod;botSummaryPeriodPreferences(periods);draw()};
 for(const button of document.querySelectorAll('[data-toggle]'))button.onclick=()=>change(button.dataset.toggle,{desired:data.bots.find(b=>b.id===button.dataset.toggle).desired==='running'?'paused':'running'});
 for(const button of document.querySelectorAll('[data-save]'))button.onclick=()=>change(button.dataset.save,{contracts:Number([...document.querySelectorAll('[data-size]')].find(i=>i.dataset.size===button.dataset.save).value)});
 $('events').innerHTML='<table><thead><tr><th>Time</th><th>Market</th><th>Event</th><th>Details</th></tr></thead><tbody>'+events.map(r=>`<tr><td>${e(new Date(r.time*1000).toLocaleString())}</td><td>${e(data.bots.find(b=>r.ticker?.startsWith(b.series+'-'))?.name||r.ticker||'Wallet')}</td><td>${e(r.event)}</td><td>${e([r.side,r.quantity,r.price?'$'+r.price:'',r.fee?'fee $'+r.fee:'',r.reason].filter(Boolean).join(' · '))}</td></tr>`).join('')+'</tbody></table>';
}
async function load(){
 if(busy)return;busy=true;clearTimeout(timer);
 try{const result=await demoCall('shadow/workspace?version='+($('latest').checked?'latest':'full'));if(!result.installed){note('Shadow engine is initializing. Reload after the worker finishes its handover.');return}data=result;try{events=(await demoCall('shadow/events')).items}catch{}draw()}
 catch(error){note(error.message)}finally{busy=false;timer=setTimeout(load,10000)}
}
async function change(id,fields){try{const bot=data.bots.find(b=>b.id===id);await demoCall('shadow/bots/'+id,{revision:bot.revision,...fields});note('Saved. New entries follow the worker’s next verified update; existing risk management continues.');await load()}catch(error){note(error.message)}}
$('find').oninput=()=>{if(data)draw()};$('latest').onchange=load;$('reload').onclick=load;
for(const [id,action] of [['pauseAll','pause'],['resumeAll','resume']])$(id).onclick=async()=>{try{await demoCall('shadow/bulk',{action});await load()}catch(error){note(error.message)}};
$('funds').onsubmit=async event=>{event.preventDefault();try{requestId=requestId||crypto.randomUUID();await demoCall('shadow/funds',{amount_cents:Math.round(Number($('fundAmount').value)*100),request_id:requestId});requestId=null;note('Virtual refill queued. It appears when the paper worker applies it; no real money moves.');await load()}catch(error){note(error.message)}};
$('connect').onclick=()=>$('connectionDialog').showModal();
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>$(button.dataset.close).close();
$('paperKeyFile').onchange=async()=>{const file=$('paperKeyFile').files[0];if(!file)return;if(file.size>12000){$('connectionMessage').textContent='Key file must be at most 12 KB.';return}$('demoPem').value=await file.text()};
$('connectionForm').onsubmit=async event=>{event.preventDefault();$('saveConnection').disabled=true;try{await demoCall('paper-connection',{key_id:$('demoKey').value.trim(),private_key:$('demoPem').value.trim()});$('connectionDialog').close();note('Production Read key verified. The shadow worker will connect automatically.');await load()}catch(error){$('connectionMessage').textContent=error.message}finally{$('demoPem').value='';$('demoKey').value='';$('paperKeyFile').value='';$('saveConnection').disabled=false}};
$('csv').onclick=()=>{const cols=['time','ticker','event','order_id','side','action','quantity','price','fee','slippage','reason','cash'];const quote=x=>'"'+String(x??'').replaceAll('"','""')+'"';const csv=[cols.join(','),...events.map(r=>cols.map(c=>quote(r[c])).join(','))].join('\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='money-tree-shadow-activity.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('signOut').onclick=async()=>{await createAuthClient().signOut();location.replace('/')};
load();

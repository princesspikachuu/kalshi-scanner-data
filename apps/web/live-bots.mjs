import {createAuthClient} from './auth-client.mjs';
import {money,escapeHTML as e} from './demo-client.mjs';
import {liveCall,liveBotCard} from './live-client.mjs';
import {installOnboarding} from './live-onboarding.mjs';
const $=id=>document.getElementById(id);let workspace,selected,busy=false,preflightToken=null;
const onboarding=installOnboarding({call:liveCall,reload:()=>load()});
function draw(){
 onboarding.render(workspace);
 const budget=workspace.budget,bots=workspace.bots,query=$('findLive').value.toLowerCase();
 $('trialValue').textContent=budget?money(budget.trial_cap_cents):'Not set';
 $('portfolioShare').textContent=budget?.portfolio_reference_cents?`${(budget.trial_cap_cents/budget.portfolio_reference_cents*100).toFixed(3)}%`:'Enter portfolio value to compare';
 const mode=workspace.worker_mode?.mode||'demo',running=bots.filter(b=>b.desired==='running').length;
 $('liveHealth').textContent=mode==='demo'?`${bots.length} LIVE copies · paused for setup`:mode==='draining_demo'?'Demo paused · finishing handover':`LIVE worker · ${workspace.health?.state||'waiting'}`;
 $('liveConnectionState').textContent=workspace.connection_configured?`Connected · subaccount ${workspace.connection.subaccount}`:'Not connected';
 $('lossLimit').textContent=budget?`Loss cutoff: ${money(budget.loss_limit_cents??Math.floor(budget.trial_cap_cents/2))} (50%)`:'Loss cutoff: $25.00 (50%)';
 $('workerMode').textContent=`Worker mode: ${mode}. ${workspace.worker_mode?.message||'Demo continues until you manually start the LIVE check.'}`;
 if(!$('pilotBot').options.length){$('pilotBot').innerHTML=bots.map(b=>`<option value="${e(b.key)}">${e(b.config.name)}</option>`).join('');const btc=bots.find(b=>b.config.squares.some(s=>s.asset==='btc'));if(btc)$('pilotBot').value=btc.key}
 const orders=workspace.orders||[];
 $('liveEvidence').textContent=workspace.pilot_result?.message||workspace.health?.message||'No live orders yet.';
 $('liveOrders').innerHTML=orders.length?`<table><thead><tr><th>Market</th><th>Order</th><th>Status</th><th>Filled</th><th>Price</th></tr></thead><tbody>${orders.map(o=>`<tr><td>${e(o.ticker)}</td><td>${o.kind==='entry'?'BUY':'SELL'} · ${e(o.side)}</td><td>${e(o.status)}</td><td>${e(o.filled||0)} / ${e(o.quantity)}</td><td>${e(o.price)}¢</td></tr>`).join('')}</tbody></table>`:'';
 $('startPilot').disabled=!preflightToken||$('pilotConfirmation').value!=='START ONE LIVE CONTRACT'||mode!=='demo';
 $('pausedCount').textContent=`${bots.length-running} paused · ${running} pilot running`;
 $('liveBots').innerHTML=bots.filter(b=>b.config.name.toLowerCase().includes(query)).map(liveBotCard).join('')||'<div class="empty">No live bots found.</div>';
 const sum=bots.reduce((n,b)=>n+b.config.bot_percent,0);
 $('allocationSummary').textContent=budget?`Copied bot allocation ceilings total ${sum.toFixed(1)}% of the trial amount. Per-bid contract counts round down at the configured buy price. Each bid also remains subject to market and bot limits. The initial execution check overrides quantity to exactly one contract and keeps every other bot paused.`:'Choose your trial amount to see dollar limits and contract counts for each bot.';
}
async function load(){workspace=await liveCall('workspace');if(workspace.budget){$('trialAmount').value=(workspace.budget.trial_cap_cents/100).toFixed(2);$('portfolioAmount').value=workspace.budget.portfolio_reference_cents?(workspace.budget.portfolio_reference_cents/100).toFixed(2):''}draw()}
$('reloadLive').addEventListener('click',()=>load().catch(e=>$('liveMessage').textContent=e.message));
$('findLive').addEventListener('input',()=>{if(workspace)draw()});
$('trialForm').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;const button=event.submitter;button.disabled=true;try{await liveCall('budget',{trial_cap_cents:Math.round(Number($('trialAmount').value)*100),portfolio_reference_cents:$('portfolioAmount').value?Math.round(Number($('portfolioAmount').value)*100):null});await load();$('liveMessage').textContent='Trial plan saved. All live bots remain paused.'}catch(e){$('liveMessage').textContent=e.message}finally{busy=false;button.disabled=false}});
$('liveBots').addEventListener('click',event=>{const button=event.target.closest('[data-sizing]');if(!button)return;selected=workspace.bots.find(b=>b.key===button.dataset.sizing);if(!selected)return;$('sizingName').textContent=selected.config.name;for(const [id,key] of [['liveBidPercent','bid_percent'],['liveMarketPercent','market_percent'],['liveBotPercent','bot_percent']])$(id).value=selected.config[key];$('sizingMessage').textContent='';$('sizingDialog').showModal()});
$('closeSizing').addEventListener('click',()=>$('sizingDialog').close());
$('sizingForm').addEventListener('submit',async event=>{event.preventDefault();if(busy||!selected)return;busy=true;event.submitter.disabled=true;try{await liveCall('bots/'+selected.key+'/sizing',{expected_settings_revision:selected.settings_revision,bid_percent:Number($('liveBidPercent').value),market_percent:Number($('liveMarketPercent').value),bot_percent:Number($('liveBotPercent').value)});$('sizingDialog').close();await load();$('liveMessage').textContent='LIVE allocation saved. Bot remains paused.'}catch(e){$('sizingMessage').textContent=e.message}finally{busy=false;event.submitter.disabled=false}});
const auth=createAuthClient();try{if(!await auth.current()){location.replace('/')}else{await load()}}catch(e){$('liveMessage').textContent=e.message}

$('liveKeyFile').addEventListener('change',async()=>{const file=$('liveKeyFile').files[0];if(!file)return;if(file.size>12000){$('connectionMessage').textContent='Key file must be at most 12 KB.';return}$('livePrivateKey').value=await file.text()});
$('liveConnectionForm').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;event.submitter.disabled=true;try{await liveCall('connection',{key_id:$('liveKeyId').value.trim(),private_key:$('livePrivateKey').value,subaccount:Number($('liveSubaccount').value)});preflightToken=null;await load();$('connectionMessage').textContent='Restricted live connection verified and encrypted. No orders placed.'}catch(error){$('connectionMessage').textContent=error.message}finally{$('livePrivateKey').value='';$('liveKeyFile').value='';busy=false;event.submitter.disabled=false}});
$('pilotBot').addEventListener('change',()=>{preflightToken=null;$('startPilot').disabled=true;$('pilotMessage').textContent='Check readiness for the selected bot.'});
$('pilotConfirmation').addEventListener('input',()=>{$('startPilot').disabled=!preflightToken||$('pilotConfirmation').value!=='START ONE LIVE CONTRACT'||workspace?.worker_mode?.mode!=='demo'});
$('verifyPilot').addEventListener('click',async()=>{if(busy)return;busy=true;preflightToken=null;$('startPilot').disabled=true;try{const bot=workspace.bots.find(b=>b.key===$('pilotBot').value);if(!bot)throw Error('Select a bot first');const result=await liveCall('preflight',{bot:bot.key,expected_settings_revision:bot.settings_revision});preflightToken=result.token;$('pilotMessage').textContent=result.message;$('pilotConfirmation').dispatchEvent(new Event('input'))}catch(error){$('pilotMessage').textContent=error.message}finally{busy=false}});
$('startPilot').addEventListener('click',async()=>{if(busy||!preflightToken)return;busy=true;$('startPilot').disabled=true;try{const bot=workspace.bots.find(b=>b.key===$('pilotBot').value);const result=await liveCall('pilot',{bot:bot.key,expected_settings_revision:bot.settings_revision,token:preflightToken,confirmation:$('pilotConfirmation').value});preflightToken=null;$('pilotConfirmation').value='';await load();$('pilotMessage').textContent=result.message}catch(error){$('pilotMessage').textContent=error.message}finally{busy=false}});
for(const [id,path] of [['pauseLive','pause'],['returnDemo','return-demo']])$(id).addEventListener('click',async()=>{if(busy)return;busy=true;try{const result=await liveCall(path,{});preflightToken=null;await load();$('pilotMessage').textContent=result.message||'Worker returned to Demo. Resume Demo bots explicitly when ready.'}catch(error){$('pilotMessage').textContent=error.message}finally{busy=false}});
setInterval(()=>{if(!busy&&!document.hidden&&workspace?.worker_mode?.mode!=='demo')load().catch(error=>$('liveMessage').textContent=error.message)},10000);

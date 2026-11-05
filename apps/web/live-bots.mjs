import {createAuthClient} from './auth-client.mjs';
import {money} from './demo-client.mjs';
import {liveCall,liveBotCard} from './live-client.mjs';
const $=id=>document.getElementById(id);let workspace,selected,busy=false;
function draw(){
 const budget=workspace.budget,bots=workspace.bots,query=$('findLive').value.toLowerCase();
 $('trialValue').textContent=budget?money(budget.trial_cap_cents):'Not set';
 $('portfolioShare').textContent=budget?.portfolio_reference_cents?`${(budget.trial_cap_cents/budget.portfolio_reference_cents*100).toFixed(3)}%`:'Enter portfolio value to compare';
 $('liveHealth').textContent=`${bots.length} LIVE bots · all paused · trading disabled`;
 $('pausedCount').textContent=`${bots.length} paused`;
 $('liveBots').innerHTML=bots.filter(b=>b.config.name.toLowerCase().includes(query)).map(liveBotCard).join('')||'<div class="empty">No live bots found.</div>';
 const sum=bots.reduce((n,b)=>n+b.config.bot_percent,0);
 $('allocationSummary').textContent=budget?`Copied bot allocation ceilings total ${sum.toFixed(1)}% of the trial amount. Per-bid contract counts round down at the configured buy price. Each bid also remains subject to market and bot limits. These are planning figures; real trading is disabled.`:'Choose your trial amount to see dollar limits and contract counts for each bot.';
}
async function load(){workspace=await liveCall('workspace');if(workspace.budget){$('trialAmount').value=(workspace.budget.trial_cap_cents/100).toFixed(2);$('portfolioAmount').value=workspace.budget.portfolio_reference_cents?(workspace.budget.portfolio_reference_cents/100).toFixed(2):''}draw()}
$('reloadLive').addEventListener('click',()=>load().catch(e=>$('liveMessage').textContent=e.message));
$('findLive').addEventListener('input',()=>{if(workspace)draw()});
$('trialForm').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;const button=event.submitter;button.disabled=true;try{await liveCall('budget',{trial_cap_cents:Math.round(Number($('trialAmount').value)*100),portfolio_reference_cents:$('portfolioAmount').value?Math.round(Number($('portfolioAmount').value)*100):null});await load();$('liveMessage').textContent='Trial plan saved. All live bots remain paused.'}catch(e){$('liveMessage').textContent=e.message}finally{busy=false;button.disabled=false}});
$('liveBots').addEventListener('click',event=>{const button=event.target.closest('[data-sizing]');if(!button)return;selected=workspace.bots.find(b=>b.key===button.dataset.sizing);if(!selected)return;$('sizingName').textContent=selected.config.name;for(const [id,key] of [['liveBidPercent','bid_percent'],['liveMarketPercent','market_percent'],['liveBotPercent','bot_percent']])$(id).value=selected.config[key];$('sizingMessage').textContent='';$('sizingDialog').showModal()});
$('closeSizing').addEventListener('click',()=>$('sizingDialog').close());
$('sizingForm').addEventListener('submit',async event=>{event.preventDefault();if(busy||!selected)return;busy=true;event.submitter.disabled=true;try{await liveCall('bots/'+selected.key+'/sizing',{expected_settings_revision:selected.settings_revision,bid_percent:Number($('liveBidPercent').value),market_percent:Number($('liveMarketPercent').value),bot_percent:Number($('liveBotPercent').value)});$('sizingDialog').close();await load();$('liveMessage').textContent='LIVE allocation saved. Bot remains paused.'}catch(e){$('sizingMessage').textContent=e.message}finally{busy=false;event.submitter.disabled=false}});
const auth=createAuthClient();try{if(!await auth.current()){location.replace('/')}else{await load()}}catch(e){$('liveMessage').textContent=e.message}

import {money,escapeHTML as e} from './demo-client.mjs';
export const confirmations={upgrade:'REQUEST ADVANCED ACCESS',create:'CREATE ISOLATED ACCOUNT',prepare:'PREPARE UP TO $50',fund:'FUND ISOLATED ACCOUNT $50',connect:'CREATE RESTRICTED KEY'};
export function setupSteps(s){
 if(!s||s.connected)return [];
 const available=!!s.can_write&&!s.busy;
 return [
 {action:'upgrade',title:'Request Advanced API access',description:'Ask Kalshi to upgrade your API access. No trade will be placed to qualify. If your account is ineligible, contact Kalshi before continuing.',enabled:available&&!s.eligible},
 {action:'create',title:'Create isolated account',description:'Create a new numbered Kalshi subaccount for this trial. No money moves in this step.',enabled:available&&s.eligible&&s.market_running&&s.subaccount==null},
 {action:'prepare',title:`Prepare ${money(s.prepare_cents||0)} for this market`,description:`Move ${money(s.prepare_cents||0)} between your primary Predictions balances so this market can use it. This does not fund the isolated account yet.`,enabled:available&&s.eligible&&!!s.subaccount&&s.account_cents===0&&s.prepare_cents>0&&s.source_index!=null},
 {action:'fund',title:'Fund isolated account · exactly $50',description:`Move exactly $50 from your primary Kalshi Predictions balance to isolated subaccount ${s.subaccount??'—'}. No money leaves Kalshi. This setup never sends a second $50.`,enabled:available&&s.eligible&&!!s.subaccount&&s.account_cents===0&&s.primary_market_cents>=5000},
 {action:'connect',title:'Create and save restricted trading key',description:`Create a Read and Trade key restricted to subaccount ${s.subaccount??'—'}. Encrypt and save only that restricted key. Your temporary setup key will not be saved. No trading starts.`,enabled:available&&s.eligible&&!!s.subaccount&&s.account_cents===5000&&s.market_cents===5000}
 ];
}
export function installOnboarding({call,reload}){
 const $=id=>document.getElementById(id);let state=null,busy=false,chosen=null;
 function clear(){for(const id of ['setupKeyId','setupPrivateKey','setupKeyFile'])$(id).value=''}
 function draw(){
  $('setupCredentials').hidden=!!state?.connected;
  $('setupCheck').disabled=busy;$('setupCheck').textContent=state?'Refresh checks · no changes':'Check account · no changes';
  $('setupBot').disabled=!!state;
  $('setupProgress').innerHTML=state?.connected?'<p><strong>Connected. All LIVE bots remain paused.</strong> Revoke your temporary setup key in <a href="https://kalshi.com/account/profile" target="_blank" rel="noopener noreferrer">Kalshi Profile Settings</a>. Use the separate one-contract readiness check below when you are ready.</p>':state?`<p>API access: <strong>${e(state.tier)}</strong> · Isolated account: <strong>${e(state.subaccount??'Not created')}</strong> · Trial cash: <strong>${state.account_cents==null?'Not funded':money(state.account_cents)}</strong></p>${!state.market_running?'<p>Waiting for an active market. Refresh checks when markets resume.</p>':''}${state.busy?'<p role="status">A previous '+e(state.busy)+' request needs verification. Refresh checks; do not repeat the action in Kalshi. If it cannot be verified, contact support before proceeding.</p>':''}${setupSteps(state).map(step=>`<p><button class="secondary" data-setup-action="${step.action}" ${busy||!step.enabled?'disabled':''}>${e(step.title)}</button></p>`).join('')}`:'';
 }
 async function request(action){
  if(busy)return;busy=true;draw();$('setupMessage').textContent='Checking with Kalshi…';
  try{
   const result=await call('onboarding',{action,key_id:$('setupKeyId').value.trim(),private_key:$('setupPrivateKey').value,bot:$('setupBot').value,draft:state?.id||null,confirmation:action==='check'?'':$('setupConfirmation').value});
   state=result.onboarding;$('setupMessage').textContent=state.message||'Setup checked.';
   if(state.connected)clear();await reload();
  }catch(error){$('setupMessage').textContent=error.message;try{await reload()}catch{}}
  finally{busy=false;$('setupConfirmation').value='';draw()}
 }
 $('setupKeyFile').addEventListener('change',async()=>{const file=$('setupKeyFile').files[0];if(!file)return;if(file.size>12000){$('setupMessage').textContent='Key file must be at most 12 KB.';return}$('setupPrivateKey').value=await file.text()});
 $('setupForget').addEventListener('click',()=>{clear();$('setupMessage').textContent='Temporary key cleared from this page. Saved setup progress is retained.'});
 $('setupCheckForm').addEventListener('submit',event=>{event.preventDefault();request('check')});
 $('setupProgress').addEventListener('click',event=>{
  const button=event.target.closest('[data-setup-action]');if(!button||busy)return;
  chosen=setupSteps(state).find(s=>s.action===button.dataset.setupAction&&s.enabled);if(!chosen)return;
  if(!$('setupKeyId').value.trim()||!$('setupPrivateKey').value){$('setupMessage').textContent='Enter the original temporary key, then refresh checks first.';return}
  $('setupActionTitle').textContent=chosen.title;$('setupActionDescription').textContent=chosen.description;$('setupConfirmLabel').textContent='Type '+confirmations[chosen.action]+' to confirm';$('setupConfirmation').value='';$('setupSubmit').disabled=true;$('setupDialog').showModal();
 });
 $('setupConfirmation').addEventListener('input',()=>{$('setupSubmit').disabled=!chosen||$('setupConfirmation').value!==confirmations[chosen.action]});
 $('setupClose').addEventListener('click',()=>{$('setupDialog').close();$('setupConfirmation').value=''});
 $('setupActionForm').addEventListener('submit',async event=>{event.preventDefault();if(!chosen||$('setupConfirmation').value!==confirmations[chosen.action])return;$('setupDialog').close();await request(chosen.action)});
 return {render(workspace){state=workspace.onboarding||null;const bots=workspace.bots||[];if(!$('setupBot').options.length){$('setupBot').innerHTML=bots.map(b=>`<option value="${e(b.key)}">${e(b.config.name)}</option>`).join('');const btc=bots.find(b=>b.config.squares.some(s=>s.asset==='btc'));if(btc)$('setupBot').value=btc.key}if(state?.bot)$('setupBot').value=state.bot;if(state?.connected)clear();draw()}};
}

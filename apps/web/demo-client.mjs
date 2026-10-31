import {cookieValue} from './auth-client.mjs';
export const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100);
export async function demoCall(path,body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 const headers={accept:'application/json'};if(body!==undefined){headers['content-type']='application/json';headers['x-csrf-token']=cookieValue(document.cookie,'__Host-pocket_csrf')||''}
 try{
  const response=await fetch('/api/demo/'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal:controller.signal});
  if(response.status===401){location.replace('/');throw Error('Sign in to continue')}
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(typeof detail==='string'?detail:response.status===429?'Please wait before trying again.':'Unable to complete the request.')}
  const data=await response.json();if(data.contract!=='demo-v1')throw Error('Unexpected workspace response');return data;
 }finally{clearTimeout(timer)}
}

export function attentionInfo(bot,health,orders=[],now=Date.now()/1000){
 const blockedExit=health.bots?.[bot.key];
 if(blockedExit?.exit_waiting)return {reason:blockedExit.message,action:'The downward-only limit is retained. The app retries when it can rest maker-only; review Activity for the position.',control:'activity',phase:'Protective exit',markets:[],lastVerified:health.reconciled_at,lastSeen:health.at};
 const markets=(health.blocked_markets||[]).filter(t=>orders.some(o=>o.bot===bot.key&&o.ticker===t));
 const base={markets,lastVerified:health.reconciled_at,lastSeen:health.at,control:'retry'};
 if(markets.length)return {...base,reason:'These markets have manual or unreconciled exposure.',action:'Review their orders and positions in Activity. New entries wait in affected markets while unrelated trading continues.',control:'activity',phase:'Ownership reconciliation'};
 if(health.state==='connection_required')return {...base,reason:'A verified Kalshi Demo connection is required.',action:'Connect your Demo API key and private key. The worker will verify the account before trading.',control:'connection',phase:'Account connection'};
 if(!health.at||now-health.at>90)return {...base,reason:'The trading worker has stopped checking in.',action:'New entries wait for worker recovery and order verification. Request verification or inspect Activity for the last successful check.',phase:'Worker recovery'};
 const issue=health.issue;
 if(issue)return {...base,reason:issue.summary,action:issue.action,control:issue.control,code:issue.code,httpStatus:issue.http_status,phase:({'controls':'Bot controls','discovery':'Market discovery','stream':'Market-price connection','reconciliation':'Order reconciliation','trade':'Order submission'})[issue.phase]||'Trading recovery',markets:issue.market?[issue.market]:[],orderId:issue.order_id};
 return {...base,reason:health.message||'The exchange account is being verified.',action:'The worker checks orders and positions before allowing new entries. Request verification or review Activity for the latest evidence.',phase:'Account verification'};
}
export function attentionMarkup(info,{botId=''}={}){
 const e=escapeHTML,params=new URLSearchParams({bot:botId});if(info.markets?.length===1)params.set('ticker',info.markets[0]);
 const controls={retry:'Retry verification',connection:'Manage connection',funds:'Review demo funds'};
 const verified=Number.isFinite(info.lastVerified)&&info.lastVerified>0?new Date(info.lastVerified*1000).toLocaleString():'No successful verification yet';
 return `<section class="bot-attention" aria-label="Why this bot needs attention"><strong>${e(info.reason)}</strong><p>${e(info.action)}</p><p class="small">${e(info.phase)}${info.markets?.length?' · '+info.markets.map(e).join(', '):' · Account-wide verification'}<br>Last successful check: ${e(verified)}${info.orderId?'<br>Order: '+e(info.orderId):''}</p>${info.code?`<details><summary class="small">Diagnostic code</summary><span class="small">${e(info.code)}${info.httpStatus?' · HTTP '+e(info.httpStatus):''}</span></details>`:''}<div class="row">${controls[info.control]?`<button type="button" class="secondary" data-attention-action="${info.control}">${controls[info.control]}</button>`:''}<a class="button secondary" href="/activity?${e(params)}">View relevant activity</a></div></section>`;
}
export function exitEvidence(item){
 const d=item.details||{},q=d.quote||{},lines=[];
 if(item.kind!=='exit_trigger')return lines;
 if(Number.isFinite(d.threshold))lines.push(`Exit trigger: ${d.reference==='ask'?'ASK':'BID (previous rule)'} at or below ${d.threshold}¢`);
 if(Number.isFinite(q.bid)&&Number.isFinite(q.ask)&&['yes','no'].includes(d.side)){
  const bid=d.side==='yes'?q.bid:100-q.ask,ask=d.side==='yes'?q.ask:100-q.bid;
  lines.push(`Observed ${d.side.toUpperCase()} bid ${bid}¢ / ask ${ask}¢`);
 }
 if(q.source==='orderbook')lines.push(`Source: sequenced order book · sequence ${q.seq} · exchange clock ${q.clock}`);
 if(Number.isFinite(d.previous_ask))lines.push(`Previous ASK ${d.previous_ask}¢${Number.isFinite(d.observation_gap_seconds)?' · '+d.observation_gap_seconds+'s between observations':''}`);
 return lines;
}

export function resetMarkup(reset){
 if(!reset)return '';
 const e=escapeHTML,active=reset.state!=='complete',funding=reset.state==='awaiting_funds';
 return `<section class="panel" role="status"><h2>${active?'Demo reset in progress':'Demo reset verified'}</h2><p>${e(reset.message)}</p><p class="small">Open orders: ${e(reset.open_orders??'Checking')} · Held markets: ${e(reset.held_markets??'Checking')}${reset.cash_cents!=null?' · Verified cash: '+money(reset.cash_cents):''}</p>${reset.target_balance_cents!=null?`<p>Target: <strong>${money(reset.target_balance_cents)}</strong>${funding&&reset.deposit_needed_cents>0?' · Add '+money(reset.deposit_needed_cents)+' in mock funds':''}</p>`:''}${funding?'<button type="button" class="secondary" id="resetFunding">Add remaining demo funds</button>':''}${reset.market?'<p class="small">Waiting on market: '+e(reset.market)+'</p>':''}<p class="small">Old history is retained. Fresh bots stay paused.</p></section>`;
}

export function squarePerformanceMarkup(data){
 const e=escapeHTML;
 const rows=data.items.map(r=>{const s=r.condition,label=s?`${s.asset} · ${s.min_price}–${s.max_price}¢ · >${s.min_minutes}–${s.max_minutes} min`:'Legacy square · condition unavailable';
 return `<tr><td>${e(label)}<br><span class="small">v${e(r.revision??'?')} · square ${e(Number.isInteger(r.square)?r.square+1:'?')}</span></td><td>${e(r.orders)}</td><td>${e(r.filled_orders)} / ${e(r.contracts)}<br><span class="small">${r.orders?(100*r.filled_orders/r.orders).toFixed(1)+'%':'—'} filled</span></td><td>${e(r.resting_contracts)} / ${e(r.held_contracts)}</td><td>${e(r.scored)}<br><span class="small">${r.scored?(100*r.wins/r.scored).toFixed(1)+'% positive':'—'}</span></td><td>${money(r.recorded_pnl_cents)}</td></tr>`}).join('');
 const resets=data.items.reduce((n,r)=>n+r.unscored_resets,0);
 return `<p class="small">Lifetime · saved ${e(new Date(data.at*1000).toLocaleTimeString())}. Each revision keeps its original squares. Entry attempts include rejected and unfilled orders; fill rate counts attempts with any fill. Quantities are contracts.</p><div class="scroll" tabindex="0" role="region" aria-label="Performance by square"><table class="activity-table"><thead><tr><th>Square</th><th>Entry attempts</th><th>Filled orders / contracts</th><th>Resting / held</th><th>Closed / estimated win rate</th><th>Estimated net P&amp;L</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No saved squares or trading history.</td></tr>'}</tbody></table></div><p class="small">P&amp;L uses recorded limit prices less recorded fees, and may differ from actual execution proceeds. Positive closed entry lots count as wins; open lots and reset closures without assigned P&amp;L are excluded.${resets?' Unscored reset closures: '+e(resets)+'.':''}${data.limited?' History exceeds the display limit; this view is partial.':''}</p>`;
}

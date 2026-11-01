import {cookieValue} from './auth-client.mjs';
export const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100);
export function demoError(detail,status){
 if(typeof detail==='string')return detail;
 if(status===422&&Array.isArray(detail)){
  const labels={bid_percent:'Per-bid percentage',market_percent:'Per-market percentage',bot_percent:'Bot allocation',maximum_cents:'Maximum bid',minimum_cents:'Minimum bid',loss_prevention_cents:'Square loss prevention',loss_cents:'Loss threshold',name:'Bot name'};
  const errors=detail.slice(0,3).map(error=>{const loc=Array.isArray(error.loc)?error.loc:[],field=loc.at(-1),square=loc.indexOf('squares');return `${square>=0&&Number.isInteger(loc[square+1])?'Square '+(loc[square+1]+1)+' · ':''}${labels[field]||'Bot settings'}: ${typeof error.msg==='string'?error.msg.replace(/^Value error, /,'').slice(0,200):'Check this value.'}`});
  if(errors.length)return errors.join(' ');
 }
 return status===429?'Please wait before trying again.':'Unable to complete the request.';
}
export async function demoCall(path,body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 const headers={accept:'application/json'};if(body!==undefined){headers['content-type']='application/json';headers['x-csrf-token']=cookieValue(document.cookie,'__Host-pocket_csrf')||''}
 try{
  const response=await fetch('/api/demo/'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal:controller.signal});
  if(response.status===401){location.replace('/');throw Error('Sign in to continue')}
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(demoError(detail,response.status))}
  const data=await response.json();if(data.contract!=='demo-v1')throw Error('Unexpected workspace response');return data;
 }finally{clearTimeout(timer)}
}

export function botGroup(bot,health,orders=[],now=Date.now()/1000){
 if(bot.desired!=='running')return 'Paused';
 const recent=health.at>0&&now-health.at<=90;
 const routine=health.state==='syncing'&&health.sync_pending&&health.reconciled_at>0&&now-health.reconciled_at<=45&&!health.issue;
 if(!recent||(!routine&&health.state!=='ready')||health.issue||health.blocked_markets?.some(t=>orders.some(o=>o.bot===bot.key&&o.ticker===t)))return 'Needs attention';
 return 'Running';
}
export function botExposure(orders=[]){
 const positions=new Map();
 for(const order of orders){
  const held=Math.max(0,(order.filled||0)-(order.sold||0));
  if(order.kind!=='entry'||!held)continue;
  const key=JSON.stringify([order.ticker,order.side]),position=positions.get(key)||{ticker:order.ticker,side:order.side,quantity:0,cost:0};
  position.quantity+=held;position.cost+=held*order.price;positions.set(key,position);
 }
 return {positions:[...positions.values()].map(p=>({...p,price:p.cost/p.quantity})),waiting:orders.filter(o=>(o.remaining||0)>0||['intent','uncertain','cancel_pending'].includes(o.status))};
}
export function botExposureMarkup(orders=[],botId=''){
 const {positions,waiting}=botExposure(orders),e=escapeHTML;
 const market=ticker=>`<a href="/activity?${e(new URLSearchParams({bot:botId,ticker}))}">${e(ticker)}</a>`;
 const qty=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(n);
 const price=n=>Number.isFinite(n)?qty(n)+'¢':'—';
 const table=(head,rows)=>`<div class="scroll"><table class="activity-table"><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 return `<h3>Open positions · ${positions.length}</h3>${positions.length?table(['Market','Outcome','Contracts','Average entry limit'],positions.map(p=>`<tr><td>${market(p.ticker)}</td><td>${e(p.side?.toUpperCase())}</td><td>${qty(p.quantity)}</td><td>${price(p.price)}</td></tr>`)):'<p class="small">No open positions.</p>'}<h3>Waiting orders · ${waiting.length}</h3>${waiting.length?table(['Market','Order','Outcome','Remaining','Limit','Status'],waiting.map(o=>`<tr><td>${market(o.ticker)}</td><td>${o.kind==='entry'?'Entry bid':o.exit_role==='profit'?'Profit sell':'Protective exit'}</td><td>${e(o.side?.toUpperCase())}</td><td>${['intent','uncertain','cancel_pending'].includes(o.status)?'Unconfirmed':qty(o.remaining)}</td><td>${price(o.price)}</td><td>${e(o.status)}</td></tr>`)):'<p class="small">No waiting orders.</p>'}<p class="small">Uses the latest saved exchange check. Entry limits can differ from actual execution prices. Partially filled bids appear in both sections.</p>`;
}
export function attentionInfo(bot,health,orders=[],now=Date.now()/1000){
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
 return `<section class="panel" role="status"><h2>Bot reset</h2><p>${reset.state==='complete'?'Existing bots are archived and fresh paused copies are ready to resume.':'The previous reset is being updated. No target balance is required to resume bots.'}</p><p class="small">Historical trades stay with their original bots. Existing positions remain tracked and protected. Funding is optional.</p></section>`;
}

export function squarePerformanceMarkup(data){
 const e=escapeHTML;
 const rows=data.items.map(r=>{const s=r.condition,label=s?`${s.asset} · ${s.min_price}–${s.max_price}¢ · >${s.min_minutes}–${s.max_minutes} min`:'Legacy square · condition unavailable';
 return `<tr><td>${e(label)}<br><span class="small">v${e(r.revision??'?')} · square ${e(Number.isInteger(r.square)?r.square+1:'?')}</span></td><td>${e(r.orders)}</td><td>${e(r.filled_orders)} / ${e(r.contracts)}<br><span class="small">${r.orders?(100*r.filled_orders/r.orders).toFixed(1)+'%':'—'} filled</span></td><td>${e(r.resting_contracts)} / ${e(r.held_contracts)}</td><td>${e(r.scored)}<br><span class="small">${r.scored?(100*r.wins/r.scored).toFixed(1)+'% positive':'—'}</span></td><td>${money(r.recorded_pnl_cents)}</td></tr>`}).join('');
 const resets=data.items.reduce((n,r)=>n+r.unscored_resets,0);
 return `<p class="small">Lifetime · saved ${e(new Date(data.at*1000).toLocaleTimeString())}. Each revision keeps its original squares. Entry attempts include rejected and unfilled orders; fill rate counts attempts with any fill. Quantities are contracts.</p><div class="scroll" tabindex="0" role="region" aria-label="Performance by square"><table class="activity-table"><thead><tr><th>Square</th><th>Entry attempts</th><th>Filled orders / contracts</th><th>Resting / held</th><th>Closed / estimated win rate</th><th>Estimated net P&amp;L</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No saved squares or trading history.</td></tr>'}</tbody></table></div><p class="small">P&amp;L uses recorded limit prices less recorded fees, and may differ from actual execution proceeds. Positive closed entry lots count as wins; open lots and reset closures without assigned P&amp;L are excluded.${resets?' Unscored reset closures: '+e(resets)+'.':''}${data.limited?' History exceeds the display limit; this view is partial.':''}</p>`;
}

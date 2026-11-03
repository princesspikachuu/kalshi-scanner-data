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
 const shortFeedReconnect=health.state==='reconnecting'&&health.stream?.outage_seconds<=10&&health.reconciled_at>0&&now-health.reconciled_at<=45&&!health.issue;
 if(!recent||(!routine&&!shortFeedReconnect&&health.state!=='ready')||health.issue||health.blocked_markets?.some(t=>!health.historical_markets?.includes(t)&&!health.syncing_markets?.includes(t)&&orders.some(o=>o.bot===bot.key&&o.ticker===t)))return 'Needs attention';
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
export function orderDetailButton(identifier,label='Follow order'){
 return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(identifier||'')?`<button class="secondary" type="button" data-order-detail="${escapeHTML(identifier)}">${escapeHTML(label)}</button>`:'';
}
export function marketLink(ticker,quote={}){
 if(typeof ticker!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/.test(ticker))return escapeHTML(ticker||'—');
 const event=quote?.event_ticker||ticker.split('-').slice(0,-1).join('-');
 if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/.test(event))return escapeHTML(ticker);
 const href='https://demo.kalshi.co/markets/kx/m/'+encodeURIComponent(event.toLowerCase());
 return `<a href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer" title="Open related market in Kalshi Demo">${escapeHTML(ticker)} ↗</a>`;
}
export function transactionBadge(item){
 const d=item.details||{};let label='',style='';
 if(item.kind==='settlement'){
  const result=d.settlement_winning_side||d.quote?.result;
  const outcome=['yes','no'].includes(result)&&['yes','no'].includes(d.side)?(result===d.side?'win':'loss'):null;
  label=outcome==='win'?'✓ WIN · SETTLED':outcome==='loss'?'✕ LOSS · SETTLED':'SETTLED · OUTCOME UNAVAILABLE';style=outcome||'neutral';
 }else if(['fill','fill_recovered'].includes(item.kind)){
  label=d.order_kind==='entry'?'BUY FILL · ENTRY':d.order_kind==='exit'?'SELL FILL · EXIT':'FILL · TYPE UNAVAILABLE';style=d.order_kind==='entry'?'entry':d.order_kind==='exit'?'exit':'neutral';
 }else if(['order','order_intent','order_rejected','order_uncertain','cancel'].includes(item.kind)&&['entry','exit'].includes(d.order_kind)){
  label=d.order_kind==='entry'?'BUY · ENTRY':'SELL · EXIT';style=d.order_kind;
 }
 return label?`<span class="trade-badge ${style}">${escapeHTML(label)}</span>`:'';
}
export function botExposureMarkup(orders=[],botId=''){
 const {positions,waiting}=botExposure(orders),e=escapeHTML;
 const market=ticker=>`<a href="/activity?${e(new URLSearchParams({bot:botId,ticker}))}">${e(ticker)}</a>`;
 const qty=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(n);
 const price=n=>Number.isFinite(n)?qty(n)+'¢':'—';
 const table=(head,rows)=>`<div class="scroll"><table class="activity-table"><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
 return `<h3>Open positions · ${positions.length}</h3>${positions.length?table(['Market','Outcome','Contracts','Average entry limit'],positions.map(p=>`<tr><td>${market(p.ticker)}</td><td>${e(p.side?.toUpperCase())}</td><td>${qty(p.quantity)}</td><td>${price(p.price)}</td></tr>`)):'<p class="small">No open positions.</p>'}<h3>Waiting orders · ${waiting.length}</h3>${waiting.length?table(['Market','Order','Outcome','Remaining','Limit','Status'],waiting.map(o=>`<tr><td>${market(o.ticker)}</td><td>${orderDetailButton(o.client_id,o.kind==='entry'?'Buy → linked sells':o.exit_role==='profit'?'Profit sell → buy':'Protective sell → buy')||escapeHTML(o.kind==='entry'?'Entry bid':o.exit_role==='profit'?'Profit sell':'Protective exit')}</td><td>${e(o.side?.toUpperCase())}</td><td>${['intent','uncertain','cancel_pending'].includes(o.status)?'Unconfirmed':qty(o.remaining)}</td><td>${price(o.price)}</td><td>${e(o.status)}</td></tr>`)):'<p class="small">No waiting orders.</p>'}<p class="small">Uses the latest saved exchange check. Entry limits can differ from actual execution prices. Partially filled bids appear in both sections.</p>`;
}
export function historicalExposureMarkup(bot,health,orders=[]){
 if(!bot)return '';
 const tickers=(health.historical_markets||[]).filter(t=>orders.some(o=>o.bot===bot.key&&o.ticker===t));
 if(!tickers.length)return '';
 const e=escapeHTML,qty=n=>Number.isFinite(n)?String(n):'Unknown';
 return `<section class="panel"><h3>Ended markets awaiting exchange confirmation</h3><p class="small">These markets have ended and have no live or uncertain orders. Their records remain saved while Demo settlement or historical positions are verified. They do not require action and do not block other markets.</p>${tickers.map(t=>{const d=health.ownership_details?.[t]||{};return `<p class="small"><strong>${e(t)}</strong><br>${d.reason==='market_unavailable'?'Demo no longer returns this ticker.':'Waiting for settlement or historical position confirmation.'} Saved net contracts: ${e(qty(d.expected_contracts))} · Exchange net contracts: ${e(qty(d.exchange_contracts))} · Market status: ${e(d.market_state||'Unavailable')}</p>`}).join('')}</section>`;
}
export function attentionInfo(bot,health,orders=[],now=Date.now()/1000){
 const markets=(health.blocked_markets||[]).filter(t=>!health.historical_markets?.includes(t)&&!health.syncing_markets?.includes(t)&&orders.some(o=>o.bot===bot.key&&o.ticker===t));
 const base={markets,lastVerified:health.reconciled_at,lastSeen:health.at,control:'retry'};
 if(markets.length){
  const details=Object.fromEntries(markets.map(t=>[t,health.ownership_details?.[t]||{}]));
  const manual=markets.some(t=>details[t].unowned_order_count>0),uncertain=markets.some(t=>details[t].unconfirmed_order_count>0);
  return {...base,details,
   reason:manual?'Unowned exchange orders need verification.':uncertain?'Some orders have not been confirmed by Kalshi.':'Saved bot positions differ from the exchange position.',
   action:'This market is temporarily blocked until its combined YES/NO position is verified. Other markets continue trading. Expand the market details to see every involved bot and order.',control:'activity',phase:'Market ownership reconciliation'};
 }
 if(health.state==='connection_required')return {...base,reason:'A verified Kalshi Demo connection is required.',action:'Connect your Demo API key and private key. The worker will verify the account before trading.',control:'connection',phase:'Account connection'};
 if(!health.at||now-health.at>90)return {...base,reason:'The trading worker has stopped checking in.',action:'New entries wait for worker recovery and order verification. Request verification or inspect Activity for the last successful check.',phase:'Worker recovery'};
 const issue=health.issue;
 if(issue)return {...base,reason:issue.summary,action:issue.action,control:issue.control,code:issue.code,httpStatus:issue.http_status,phase:({'controls':'Bot controls','discovery':'Market discovery','stream':'Market-price connection','reconciliation':'Order reconciliation','trade':'Order submission'})[issue.phase]||'Trading recovery',markets:issue.market?[issue.market]:[],orderId:issue.order_id};
 return {...base,reason:health.message||'The exchange account is being verified.',action:'The worker checks orders and positions before allowing new entries. Request verification or review Activity for the latest evidence.',phase:'Account verification'};
}
export function attentionMarkup(info,{botId=''}={}){
 const e=escapeHTML,params=new URLSearchParams({bot:botId});
 const table=(head,rows)=>`<div class="scroll"><table class="activity-table"><thead><tr>${head.map(h=>`<th>${e(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;if(info.markets?.length===1)params.set('ticker',info.markets[0]);
 const controls={retry:'Retry verification',connection:'Manage connection',funds:'Review demo funds'};
 const verified=Number.isFinite(info.lastVerified)&&info.lastVerified>0?new Date(info.lastVerified*1000).toLocaleString():'No successful verification yet';
 const diagnostics=(info.markets||[]).slice(0,8).map(t=>{
  const d=info.details?.[t];if(!d)return '';
  const bots=d.bots||[],rows=d.orders||[],missing=d.unowned_orders||[];
  const quantity=x=>Number.isFinite(Number(x))?String(x):'Unknown';
  const status=d.syncing?'Synchronizing recent order update':d.reason==='unowned_resting_order'?'Unowned resting order':d.reason==='order_verification'?'Order confirmation pending':'Position mismatch';
  const botRows=bots.map(b=>`<tr><td>${e(b.name||b.id)}</td><td>${e(quantity(b.held_yes))}</td><td>${e(quantity(b.held_no))}</td><td>${e(quantity(b.net_contracts))}</td></tr>`);
  const orderRows=rows.map(o=>`<tr><td>${e(o.bot_name||o.bot_id||'Unknown')}</td><td>${e(o.kind==='exit'?(o.exit_role==='profit'?'Profit sell':'Protective sell'):'Buy')} ${e((o.side||'').toUpperCase())}</td><td>${e(o.status||'Unknown')}</td><td>${e(quantity(o.filled))} filled / ${e(quantity(o.remaining))} waiting</td><td><code>${e(o.client_id||o.exchange_id||'Unknown')}</code>${o.parent?`<small>Linked buy: <code>${e(o.parent)}</code></small>`:''}</td></tr>`);
  const manualRows=missing.map(o=>`<li>Unowned exchange order <code>${e(o.exchange_id||o.client_id||'Unknown')}</code> · ${e(o.status||'resting')}</li>`).join('');
  return `<section class="panel"><strong>${e(t)}</strong> · ${e(status)}<p class="small">Saved bot net: ${e(quantity(d.expected_contracts))} YES contracts · Kalshi account net: ${e(quantity(d.exchange_contracts))} YES contracts · Duration: ${e(quantity(d.blocked_seconds))} seconds. Multiple bots may contribute to the same account position; this list does not establish which order caused the mismatch.</p>
  ${botRows.length?`<h4>Participating bots</h4>${table(['Bot','Held YES','Held NO','Net YES'],botRows)}`:''}
  ${orderRows.length?`<h4>Involved orders (${e(d.order_count||rows.length)})</h4>${table(['Bot','Action','Status','Contracts','Order ID'],orderRows)}`:''}
  ${d.truncated_orders?`<p class="small">And ${e(d.truncated_orders)} more orders. See Activity for the complete history.</p>`:''}
  ${manualRows?`<h4>Unowned exchange orders</h4><ul>${manualRows}</ul>`:''}
  </section>`;
 }).join('');
 const marketDetails=diagnostics?`<details><summary>View participating bots, contracts and order IDs</summary>${diagnostics}${(info.markets||[]).length>8?`<p class="small">Plus ${e(info.markets.length-8)} other affected markets; open Activity for the rest.</p>`:''}</details>`:'';
 return `<section class="bot-attention" aria-label="Why this bot needs attention"><strong>${e(info.reason)}</strong><p>${e(info.action)}</p><p class="small">${e(info.phase)}${info.markets?.length?' · '+info.markets.map(e).join(', '):' · Account-wide verification'}<br>Last exchange check: ${e(verified)}${info.orderId?'<br>Order: '+e(info.orderId):''}</p>${marketDetails}${info.code?`<details><summary class="small">Diagnostic code</summary><span class="small">${e(info.code)}${info.httpStatus?' · HTTP '+e(info.httpStatus):''}</span></details>`:''}<div class="row">${controls[info.control]?`<button type="button" class="secondary" data-attention-action="${info.control}">${controls[info.control]}</button>`:''}<a class="button secondary" href="/activity?${e(params)}">View relevant activity</a></div></section>`;
}
export function exitEvidence(item){
 const d=item.details||{},q=d.quote||{},lines=[];
 if(item.kind!=='exit_trigger')return lines;
 if(Number.isFinite(d.threshold))lines.push(`Exit trigger: ${d.reference==='ask'?'ASK':'BID (previous rule)'} at or below ${d.threshold}¢`);
 if(Number.isFinite(d.minutes_remaining))lines.push(`Protection time: ${Math.round(d.minutes_remaining*100)/100} minutes remaining · current market time`);
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
 if(reset.state==='undone')return `<section class="panel" role="status"><h2>Bot reset undone</h2><p>Original bots restored; unused fresh copies removed. Existing exchange orders and positions were not modified.</p></section>`;
 const complete=reset.state==='complete';
 const canUndo=complete&&Number.isFinite(reset.completed_at)&&Date.now()/1000-reset.completed_at<5400;
 return `<section class="panel" role="status"><h2>Bot reset</h2><p>${complete?'Original bots archived and fresh paused copies created.':'Previous reset is being updated. No target balance is required to resume bots.'}</p><p class="small">Historical trades and existing exchange positions remain tracked.</p>${canUndo?'<button type="button" class="secondary" id="undoLatestReset">Undo this reset</button><p class="small">Only unused reset copies can be removed. Undo never reverses exchange fills.</p>':''}</section>`;
}

export function squarePerformanceMarkup(data){
 const e=escapeHTML,group=data.group||'square',heading={square:'Square',remaining:'Time remaining at entry',time:'Time remaining at entry',time_price:'Time remaining at entry',hour:'Local hour of entry'}[group]||'Square';
 const rows=data.items.map(r=>{const s=r.condition,label=r.label||(s?`${s.asset} · ${s.min_price}–${s.max_price}¢ · >${s.min_minutes}–${s.max_minutes} min`:'Legacy square · condition unavailable');
 return `<tr><td>${e(label)}${group==='square'?`<br><span class="small">v${e(r.revision??'?')} · square ${e(Number.isInteger(r.square)?r.square+1:'?')}</span>`:''}</td><td>${e(r.orders)}</td><td>${e(r.filled_orders)} / ${e(r.contracts)}<br><span class="small">${r.orders?(100*r.filled_orders/r.orders).toFixed(1)+'%':'—'} filled</span></td><td>${e(r.resting_contracts)} / ${e(r.held_contracts)}</td><td>${e(r.scored)}<br><span class="small">${r.scored?(100*r.wins/r.scored).toFixed(1)+'% positive':'—'}</span></td><td>${money(r.recorded_pnl_cents)}</td></tr>`}).join('');
 const resets=data.items.reduce((n,r)=>n+r.unscored_resets,0);
 return `<p class="small">${e(data.start||data.end?`${data.start||'Earliest'} through ${data.end||'latest'}`:data.period||'Lifetime')} · ${e(data.timezone||'America/Los_Angeles')} · saved ${e(new Date(data.at*1000).toLocaleTimeString())}. ${group==='square'?'Each revision keeps its original squares.':'Entries are grouped by submission time across revisions. Date filters use entry submission dates; P&L follows those entry lots.'} Entry attempts include rejected and unfilled orders; fill rate counts attempts with any fill. Quantities are contracts.</p>${group==='time_price'?timePriceGridMarkup(data):group==='square'?squareGridMarkup(data):`<div class="scroll" tabindex="0" role="region" aria-label="Performance by ${e(heading.toLowerCase())}"><table class="activity-table"><thead><tr><th>${e(heading)}</th><th>Entry attempts</th><th>Filled orders / contracts</th><th>Resting / held</th><th>Closed / estimated win rate</th><th>Estimated net P&amp;L</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No saved entries for these filters.</td></tr>'}</tbody></table></div>`}<p class="small">P&amp;L uses recorded limit prices less recorded fees, and may differ from actual execution proceeds. Positive closed entry lots count as wins; open lots and reset closures without assigned P&amp;L are excluded.${resets?' Unscored reset closures: '+e(resets)+'.':''}${['remaining','time'].includes(group)?' Older low/high orders without their original market clock appear as time remaining unavailable.':''}${data.limited?' History exceeds the display limit; this view is partial.':''}</p>`;
}

export function latestTransactionsMarkup(data,botId){
 const e=escapeHTML,labels={order_intent:'Order prepared',order:'Order accepted',order_rejected:'Order rejected',order_uncertain:'Awaiting exchange confirmation',fill:'Fill confirmed',fill_recovered:'Fill recovered',cancel:'Cancellation',settlement:'Settlement',realized:'Position closed',position_offset:'Offsetting fills reconciled'};
 const rows=data.items.slice(0,10).map(item=>{
  const d=item.details||{},clock=new Date(item.time),when=Number.isFinite(clock.getTime())?clock.toLocaleString():'Time unavailable';
  const evidence=[d.order_kind==='entry'?'Buy':d.order_kind==='exit'?'Sell':null,d.side?.toUpperCase(),Number.isFinite(d.price)?`${d.price}¢ limit`:null,Number.isFinite(d.quantity)?`${d.quantity} contracts`:null].filter(Boolean).join(' · ');
  return `<tr><td>${e(when)}</td><td>${transactionBadge(item)}<br><strong>${e(labels[item.kind]||item.kind)}</strong><br>${orderDetailButton(d.client_id,d.order_kind==='entry'?'Buy → linked sells':'Follow order')}<br>${e(evidence)}<br><span class="small">${e(item.message||item.summary)}</span>${item.archived?'<br><span class="small">Archived details · restore in Activity</span>':''}</td><td>${marketLink(item.ticker,d.quote)}${Number.isFinite(d.filled)?`<br><span class="small">Filled so far: ${e(d.filled)} contracts</span>`:''}${Number.isFinite(d.realized_cents)?`<br><span class="small">Estimated net ${money(d.realized_cents)}</span>`:''}${d.exchange_id?`<br><span class="small">Order ${e(d.exchange_id)}</span>`:''}</td></tr>`;
 }).join('');
 return `<p class="small">Latest 10 saved transaction events · ${e(new Date(data.loadedAt||Date.now()).toLocaleTimeString())}. Prepared or rejected orders are shown separately from confirmed fills.</p><div class="scroll" tabindex="0" role="region" aria-label="Latest bot transactions"><table class="activity-table"><thead><tr><th>Time</th><th>Transaction</th><th>Market / evidence</th></tr></thead><tbody>${rows||'<tr><td colspan="3">No saved transactions for this bot yet.</td></tr>'}</tbody></table></div><a class="button secondary" href="/activity?bot=${e(encodeURIComponent(botId))}">View all bot activity</a>`;
}

export function squareGridMarkup(data){
 const groups=new Map(),legacy=[];
 for(const row of data.items){
  if(!row.condition){legacy.push(row);continue}
  const key=JSON.stringify([row.revision,row.condition.asset]);
  if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);
 }
 const cell=r=>performanceCell(r);
 let html='<p class="small">Estimated net P&amp;L by price column and time-remaining row, matching the bot setup grid. Each asset and revision stays separate. Blank cells were not configured.</p>';
 for(const rows of groups.values()){
  const price=new Map(),time=new Map(),cells=new Map();
  for(const r of rows){
   const s=r.condition,p=JSON.stringify([s.min_price,s.max_price]),t=JSON.stringify([s.min_minutes,s.max_minutes]);
   price.set(p,[s.min_price,s.max_price]);time.set(t,[s.min_minutes,s.max_minutes]);
   const key=JSON.stringify([p,t]);if(!cells.has(key))cells.set(key,[]);cells.get(key).push(r);
  }
  const columns=[...price].sort((a,b)=>a[1][0]-b[1][0]||a[1][1]-b[1][1]),windows=[...time].sort((a,b)=>b[1][1]-a[1][1]||b[1][0]-a[1][0]);
  html+=`<h4>${escapeHTML(rows[0].condition.asset)} · v${escapeHTML(rows[0].revision??'?')}</h4><div class="bot-table-scroll" tabindex="0" role="region" aria-label="Square performance grid"><table class="bot-offerings performance-grid"><thead><tr><th>Time left</th>${columns.map(([key,[min,max]])=>`<th>${escapeHTML(min)}–${escapeHTML(max)}¢</th>`).join('')}</tr></thead><tbody>${windows.map(([t,[min,max]])=>`<tr><th>&gt;${escapeHTML(min)}–${escapeHTML(max)} min</th>${columns.map(([p])=>{const variants=cells.get(JSON.stringify([p,t]));return `<td>${variants?variants.map(cell).join(''):'<span class="small">—</span>'}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>`;
 }
 if(legacy.length)html+='<h4>Historical squares with unavailable conditions</h4>'+legacy.map(cell).join('');
 return html+(data.items.length?'':'<p class="small">No saved squares or trading history.</p>');
}

export function timePriceGridMarkup(data){
 const bounds=[...(data.time_bounds||[1,3,5,10,15])].sort((a,b)=>a-b);
 const prices=[...new Set([...data.items.map(r=>r.entry_price),...(Number.isFinite(data.default_entry_price)?[data.default_entry_price]:[])])].sort((a,b)=>a===null?1:b===null?-1:a-b);
 if(!prices.length)prices.push(null);
 const windows=[...bounds].reverse();for(const r of data.items)if(!windows.includes(r.bucket))windows.push(r.bucket);
 const empty={orders:0,filled_orders:0,scored:0,wins:0,resting_contracts:0,held_contracts:0,recorded_pnl_cents:null};
 const label=upper=>upper===null?'Time unavailable':upper===0?'At / after close':upper===1441?'Over 1 day':`>${Math.max(0,...bounds.filter(b=>b<upper))}–${upper} min`;
 return `<p class="small">Time remaining when each low buy was submitted, grouped by its actual entry limit. Empty bands stay visible; older buys without a verified market clock appear separately.</p><div class="bot-table-scroll" tabindex="0" role="region" aria-label="Low high performance by time and entry price"><table class="bot-offerings performance-grid"><thead><tr><th>Time left</th>${prices.map(p=>`<th>${p===null?'Unknown limit':escapeHTML(p)+'¢ entry limit'}</th>`).join('')}</tr></thead><tbody>${windows.map(window=>`<tr><th>${escapeHTML(label(window))}</th>${prices.map(price=>{const row=data.items.find(r=>r.bucket===window&&r.entry_price===price);return `<td>${performanceCell(row||empty,false)}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function performanceCell(r,showSquare=true){return `<div class="performance-cell ${r.recorded_pnl_cents>0?'gain':r.recorded_pnl_cents<0?'loss':''}"><strong>${money(r.recorded_pnl_cents)}</strong><small>${r.orders?`${escapeHTML(r.filled_orders)} / ${escapeHTML(r.orders)} entries · ${(100*r.filled_orders/r.orders).toFixed(1)}% filled`:'No entries'}</small><small>${escapeHTML(r.scored)} closed · ${r.scored?(100*r.wins/r.scored).toFixed(1)+'% positive':'—'}</small><small>${escapeHTML(r.resting_contracts)} resting / ${escapeHTML(r.held_contracts)} held</small>${showSquare?`<small>v${escapeHTML(r.revision??'?')} · square ${escapeHTML(Number.isInteger(r.square)?r.square+1:'?')}</small>`:''}</div>`;}

import {escapeHTML as e,money,marketLink,orderDetailButton} from './demo-client.mjs';
export function matchesActivity(item,{bot='',ticker='',kinds=[]}={}){
 return (!bot||item.bot===bot)&&(!ticker||item.ticker===ticker)&&(!kinds.length||kinds.includes(item.kind));
}
export function matchingOrders(orders,{bot='',ticker='',kinds=[]}={}){
 return orders.filter(o=>(!bot||o.bot===bot)&&(!ticker||o.ticker===ticker)&&(!kinds.length||kinds.some(k=>
  k==='order'&&Boolean(o.exchange_id)||k==='fill'&&o.filled>0||k==='cancel'&&o.status==='cancel_pending'||
  k==='exit_trigger'&&(o.kind==='exit'&&o.exit_role!=='profit'||o.kind==='entry'&&o.exit_triggered))));
}

export function activityMarketMarkup(item,bots){
 const d=item.details||item.entry||item,bot=bots.get(item.bot||d.bot)||'Unknown bot';
 const close=d.market_close_at||d.close||d.quote?.entry_close||d.quote?.close;
 const clock=close?new Date(typeof close==='number'?close*1000:close):null;
 const when=clock&&!Number.isNaN(clock.getTime())?'Closes '+clock.toLocaleString():'';
 const title=d.quote?.title||d.quote?.subtitle||(/15M-/i.test(item.ticker||d.ticker||'')?'15-minute market':'Market');
 const label=[title,d.side?.toUpperCase(),when].filter(Boolean).join(' · ');
 return `<strong class="history-bot">${e(bot)}</strong><div>${marketLink(item.ticker||d.ticker,d.quote,label)}</div><details class="market-code"><summary>Market code</summary>${e(item.ticker||d.ticker||'Unavailable')}</details>`;
}
export function completedPairRow(item,bots){
 const entry=item.entry,n=item.estimated_net_cents,qty=new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(item.contracts);
 const when=item.completed_at?new Date(typeof item.completed_at==='number'?item.completed_at*1000:item.completed_at).toLocaleString():'Time unavailable';
 return `<tr><td>${e(when)}</td><td>${activityMarketMarkup(item,bots)}</td><td><span class="trade-badge entry">BUY FILLED</span> ${e(entry.price)}¢<br><span class="trade-badge exit">SELL FILLED</span> ${e(Number(item.sell_price.toFixed(2)))}¢<br>${e(qty)} contracts fully bought &amp; sold${item.sell_count>1?` across ${e(item.sell_count)} sells`:''}<br>${orderDetailButton(entry.client_id,'View buy & sells')}</td><td><strong class="${n>=0?'positive':'negative'}">${money(n)}</strong><br><span class="small">Estimated net · recorded fees ${money(item.fees)}<br>Prices use saved order limits.</span></td></tr>`;
}

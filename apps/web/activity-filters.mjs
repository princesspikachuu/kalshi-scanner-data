export function matchesActivity(item,{bot='',ticker='',kinds=[]}={}){
 return (!bot||item.bot===bot)&&(!ticker||item.ticker===ticker)&&(!kinds.length||kinds.includes(item.kind));
}
export function matchingOrders(orders,{bot='',ticker='',kinds=[]}={}){
 return orders.filter(o=>(!bot||o.bot===bot)&&(!ticker||o.ticker===ticker)&&(!kinds.length||kinds.some(k=>
  k==='order'&&Boolean(o.exchange_id)||k==='fill'&&o.filled>0||k==='cancel'&&o.status==='cancel_pending'||
  k==='exit_trigger'&&(o.kind==='exit'&&o.exit_role!=='profit'||o.kind==='entry'&&o.exit_triggered))));
}

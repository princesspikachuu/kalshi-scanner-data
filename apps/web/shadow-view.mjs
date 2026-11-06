import {escapeHTML as e} from './demo-client.mjs';
export const dollars=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
export const pnlClass=value=>value===null||value===undefined?'':Number(value)>0?'positive':Number(value)<0?'negative':'';
const metric=(label,value,note='')=>`<div><span>${e(label)}</span><strong>${e(dollars(value))}</strong>${note?`<small>${e(note)}</small>`:''}</div>`;
export function pendingLabel(a){
 if(!a||!Number(a.pending_contracts))return 'No payment pending';
 if(a.pending_payout_state==='confirmed')return `Confirmed payout ${dollars(a.pending_value)}`;
 if(a.pending_payout_state==='estimated')return `Estimated payout ${dollars(a.pending_value)} · outcome unconfirmed`;
 return `Outcome unconfirmed · up to ${dollars(a.pending_max_payout)}`;
}
export function exposureMarkup(a){
 if(!a)return '<p class="small">Waiting for the worker’s accounting snapshot…</p>';
 return `<div class="money-grid bot-money">${metric('Unfilled buy bids',a.unfilled_bids,'Cash reserved, not spent')}${metric('Active positions · cost',a.active_cost,`Current value ${dollars(a.active_value)}`)}${metric('Awaiting settlement · cost',a.pending_cost,pendingLabel(a))}${metric('Open position P/L',a.unrealized_pnl,'Current and pending positions · after entry fees')}</div>`;
}
export function accountMarkup(account,now=Date.now()/1000){
 if(!account)return '<p>Waiting for a consistent accounting snapshot…</p>';
 const a=account.portfolio,q=account.quality||{},noVerified=!Number(q.verified_cycles),gaps=Number(q.gap_cycles||0);
 const warning=noVerified?'No verified completed cycles yet. Account P/L includes unverified simulated trades.':gaps?`${gaps} cycles had data gaps. Every simulated trade is still included in account P/L.`:'';
 return `<div class="portfolio-headlines"><div><span>Portfolio value · estimated</span><strong>${e(dollars(a.equity))}</strong><small>Cash plus the current value of positions</small></div><div><span>Total P/L · after fees</span><strong class="${pnlClass(a.total_pnl)}">${e(dollars(a.total_pnl))}</strong><small>Lifetime · all bots and versions</small></div></div>
 <div class="portfolio-breakdown">${metric('Realized P/L',a.realized_pnl,'Closed trades and settled contracts · after fees')}${metric('Unrealized P/L',a.unrealized_pnl,'Value change of positions still held')}${metric('Virtual funds added',a.deposits,'Starting bankroll plus refills; not profit')}</div>
 <div class="money-grid">${metric('Available cash',a.available_cash,`Total cash ${dollars(a.cash)}`)}${metric('Unfilled buy bids',a.unfilled_bids,'Reserved from cash; includes estimated fees')}${metric('Active positions · cost',a.active_cost,`Current value ${dollars(a.active_value)}`)}${metric('Awaiting settlement · cost',a.pending_cost,pendingLabel(a))}</div>
 <p class="small accounting-equation">Portfolio value = cash (including reserved bids) + active position value + estimated pending payout. Position cost is shown separately from value. Values round to cents on screen.</p>
 ${now-account.at>30?`<p class="account-warning">Accounting snapshot is ${e(String(Math.floor(now-account.at)))} seconds old. These figures may be stale.</p>`:''}
 ${a.equity===null?'<p class="account-warning">A position has no current verified quote. Portfolio value and unrealized P/L are unavailable until it can be valued.</p>':''}
 ${warning?`<p class="account-warning">${e(warning)}</p>`:''}
 ${Math.abs(Number(a.reconciliation_difference||0))>.005?`<p class="account-warning">${e(dollars(a.reconciliation_difference))} of account P/L is not assigned to the current bot cards. Account totals come from the wallet ledger.</p>`:''}
 <p class="small">${e(String(q.verified_cycles||0))} verified cycle reports · ${e(String(q.gap_cycles||0))} with data gaps · Accounting updated ${e(new Date(account.at*1000).toLocaleTimeString())}</p>`;
}

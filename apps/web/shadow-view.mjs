import {escapeHTML as e,botSummaryPeriodMarkup} from './demo-client.mjs';
export const dollars=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
export const pnlClass=value=>value===null||value===undefined?'':Number(value)>0?'positive':Number(value)<0?'negative':'';
export function executionMarkup(x){
 if(!x||!x.measured)return '<p class="small">Execution measurements will appear with the next worker snapshot.</p>';
 const rate=x.maker_fill_rate==null?'—':Number(x.maker_fill_rate).toFixed(1)+'%';
 return `<details class="advanced"><summary>Execution quality · latest cycle${x.data_valid?'':' · data gap'}</summary><p class="small">${e(x.scope)}. Public queue position is estimated; simulated fills are not exchange executions. ${e(String(x.latency_ms))}ms modeled action latency.</p><div class="bot-stats">${[['Maker quantity filled / requested',`${x.maker_filled} / ${x.maker_requested} · ${rate}`],['Rejected / submitted orders',`${x.rejections} / ${x.orders}`],['Partial / attempted IOC sweeps',`${x.partial_iocs} / ${x.ioc_attempts}`],['IOC unfilled quantity',x.ioc_unfilled],['Partial-profit contracts sold',x.profit_contracts],['Net cash recovered by partial profits',dollars(x.profit_net_proceeds)],['Fees · entire cycle',dollars(x.cycle_fees)],['Taker slippage · entire cycle',dollars(x.cycle_taker_slippage)]].map(([k,v])=>`<div><span>${e(k)}</span><strong>${e(String(v))}</strong></div>`).join('')}</div><p class="small">Fill rate uses requested contract quantity, including rejected entries. Working bids remain in the denominator. Unfilled IOC quantities can include retries of the same position. Recovery proceeds include exit fees; they are cash receipts, not profit. Partial-profit target: ${(Number(x.partial_profit_price)*100).toFixed(0)}¢ or better, retaining at least one contract.</p></details>`;
}
const metric=(label,value,note='')=>`<div><span>${e(label)}</span><strong>${e(dollars(value))}</strong>${note?`<small>${e(note)}</small>`:''}</div>`;
const finite=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
export function valueBounds(a,positions=[],kind='position'){
 if(!a)return null;
 const exact=a[kind+'_value'];
 if(finite(exact))return {low:Number(exact),high:Number(exact),unpriced:0};
 const quantity=kind==='position'?Number(a.active_contracts||0)+Number(a.pending_contracts||0):Number(a[kind+'_contracts']||0);
 if(!quantity)return null;
 const priced=positions.filter(p=>(kind==='position'||p.state===kind)&&finite(p.value));
 const known=priced.reduce((s,p)=>s+Number(p.value),0);
 const missing=Math.max(0,quantity-priced.reduce((s,p)=>s+Number(p.quantity),0));
 return {low:known,high:known+missing,unpriced:missing};
}
const shifted=(range,amount)=>range&&finite(amount)?{...range,low:range.low+Number(amount),high:range.high+Number(amount)}:null;
export const rangeText=range=>!range?'—':dollars(range.low)===dollars(range.high)?dollars(range.low):`${dollars(range.low)} to ${dollars(range.high)}`;
const rangeClass=range=>!range?'':range.high<0?'negative':range.low>0?'positive':'';
const rangedMetric=(label,range,note)=>`<div><span>${e(label)}</span><strong class="${range?.unpriced?'value-range':''}">${e(rangeText(range))}</strong><small>${e(note)}</small></div>`;
export function accountPnl(a,positions=[]){
 if(finite(a?.total_pnl))return {text:dollars(a.total_pnl),className:pnlClass(a.total_pnl),uncertain:false};
 const range=shifted(valueBounds(a,positions),Number(a?.realized_pnl)-Number(a?.position_cost));
 return {text:rangeText(range),className:rangeClass(range),uncertain:!!range?.unpriced};
}
export function pendingLabel(a){
 if(!a||!Number(a.pending_contracts))return 'No payment pending';
 if(a.pending_payout_state==='confirmed')return `Confirmed payout ${dollars(a.pending_value)}`;
 if(a.pending_payout_state==='estimated')return `Estimated payout ${dollars(a.pending_value)} · outcome unconfirmed`;
 return `Outcome unconfirmed · up to ${dollars(a.pending_max_payout)}`;
}
export function exposureMarkup(a,positions=[]){
 if(!a)return '<p class="small">Waiting for the worker’s accounting snapshot…</p>';
 const unreal=finite(a.unrealized_pnl)?{low:Number(a.unrealized_pnl),high:Number(a.unrealized_pnl),unpriced:0}:shifted(valueBounds(a,positions),-Number(a.position_cost));
 return `<div class="money-grid bot-money">${metric('Unfilled buy bids',a.unfilled_bids,'Cash reserved, not spent')}${metric('Active positions · cost',a.active_cost,`Current value ${rangeText(valueBounds(a,positions,'active'))}`)}${metric('Awaiting settlement · cost',a.pending_cost,pendingLabel(a))}${rangedMetric('Open position P/L',unreal,unreal?.unpriced?'Estimated range · some positions unpriced':'Current and pending positions · after entry fees')}</div>`;
}
export function accountMarkup(account,now=Date.now()/1000,positions=[]){
 if(!account)return '<p>Waiting for a consistent accounting snapshot…</p>';
 const a=account.portfolio,q=account.quality||{},noVerified=!Number(q.verified_cycles),gaps=Number(q.gap_cycles||0);
 const warning=noVerified?'No verified completed cycles yet. Account P/L includes unverified simulated trades.':gaps?`${gaps} cycles had data gaps. Every simulated trade is still included in account P/L.`:'';
 const value=valueBounds(a,positions),uncertain=!!value?.unpriced;
 const equity=finite(a.equity)?{low:Number(a.equity),high:Number(a.equity),unpriced:0}:shifted(value,a.cash);
 const pnl=finite(a.total_pnl)?{low:Number(a.total_pnl),high:Number(a.total_pnl),unpriced:0}:shifted(equity,-Number(a.deposits));
 const unreal=finite(a.unrealized_pnl)?{low:Number(a.unrealized_pnl),high:Number(a.unrealized_pnl),unpriced:0}:shifted(value,-Number(a.position_cost));
 return `<div class="portfolio-headlines"><div><span>Portfolio value · ${uncertain?'estimated range':'estimated'}</span><strong class="${uncertain?'value-range':''}">${e(rangeText(equity))}</strong><small>Cash plus the current value of positions</small></div><div><span>Total P/L · ${uncertain?'estimated range · ':''}after fees</span><strong class="${rangeClass(pnl)} ${uncertain?'value-range':''}">${e(rangeText(pnl))}</strong><small>Lifetime · all bots and versions</small></div></div>
 ${uncertain?`<p class="account-warning">${e(String(Number(value.unpriced.toFixed(2))))} contracts have no usable bid quote. Known cash and priced positions are included; unpriced contracts are valued from $0 to $1 each. These ranges are not predicted payouts.</p>`:''}
 <div class="portfolio-breakdown">${metric('Realized P/L',a.realized_pnl,'Closed trades and settled contracts · after fees')}${rangedMetric('Unrealized P/L',unreal,uncertain?'Estimated range for positions still held':'Value change of positions still held')}${metric('Virtual funds added',a.deposits,'Starting bankroll plus refills; not profit')}</div>
 <div class="money-grid">${metric('Available cash',a.available_cash,`Total cash ${dollars(a.cash)}`)}${metric('Unfilled buy bids',a.unfilled_bids,'Reserved from cash; includes estimated fees')}${metric('Active positions · cost',a.active_cost,`Current value ${rangeText(valueBounds(a,positions,'active'))}`)}${metric('Awaiting settlement · cost',a.pending_cost,pendingLabel(a))}</div>
 <p class="small accounting-equation">Portfolio value = cash (including reserved bids) + active position value + estimated pending payout. Position cost is shown separately from value. Values round to cents on screen.</p>
 ${now-account.at>30?`<p class="account-warning">Accounting snapshot is ${e(String(Math.floor(now-account.at)))} seconds old. These figures may be stale.</p>`:''}
 ${a.equity===null&&!equity?'<p class="account-warning">A position has no current verified quote. Its value is unavailable; confirmed cash and realized P/L remain shown.</p>':''}
 ${warning?`<p class="account-warning">${e(warning)}</p>`:''}
 ${Math.abs(Number(a.reconciliation_difference||0))>.005?`<p class="account-warning">${e(dollars(a.reconciliation_difference))} of account P/L is not assigned to the current bot cards. Account totals come from the wallet ledger.</p>`:''}
 <p class="small">${e(String(q.verified_cycles||0))} verified cycle reports · ${e(String(q.gap_cycles||0))} with data gaps · Accounting updated ${e(new Date(account.at*1000).toLocaleTimeString())}</p>`;
}

export const folderPeriods={all:'All', '1H':'1h', '6H':'6h', '24H':'24h', '7D':'7d', '30D':'30d'};
export function monitoringMarkup(m){
 if(!m)return '';
 const names={weather:'Hourly weather',weather_daily:'Daily weather',hourly:'Hourly prices',sports:'Sports',complete_set:'Complete sets'};
 return `<details class="sequential-comparison monitoring-status"><summary>Market monitoring · ${e(String(m.subscribed_markets))} watched · ${e(String(m.entry_markets))} entry candidates</summary><p class="small">${e(m.reason)}. Positions, protective exits and live games awaiting the Favorites window retain monitoring. Their subscriptions count toward the total limit, separately from entry candidates. Existing positions stay monitored if capacity is exceeded.</p><div class="money-grid"><div><span>Protected monitoring</span><strong>${e(String(m.position_and_exit_markets))}</strong></div><div><span>Entry candidates</span><strong>${e(String(m.entry_markets))} / ${e(String(m.entry_candidates))}</strong></div><div><span>Total admission ceiling</span><strong>${e(String(m.subscribed_markets))} / ${e(String(m.total))}</strong></div><div><span>Pending feed inputs</span><strong>${e(String(m.backlog))}</strong></div></div><p class="small">${Object.entries(names).map(([k,label])=>`${label}: ${e(String(m.categories?.[k]||0))}`).join(' · ')}. Entry slots per category: ${e(String(m.per_category))} (complete sets: 4).</p><p class="small">Recent 95th-percentile processing lag: ${finite(m.lag_p95_seconds)?Number(m.lag_p95_seconds).toFixed(2)+'s':'waiting'} · ${e(String(m.rotated_markets))} candidates rotated out until their market closes. Capacity grows after sustained healthy processing and pauses new discovery during overload.</p></details>`;
}
export function sequentialComparisonMarkup(folders){
 const rows=folders.filter(f=>f.comparison);
 if(!rows.length)return '';
 const number=(v,suffix='')=>finite(v)?Number(v).toFixed(2)+suffix:'—';
 return `<details class="sequential-comparison"><summary>Sequential strategy comparison · ${rows.length} variants</summary><p class="small">New attempts since each comparison start; earlier baseline history is excluded here. Wallet summaries retain full history. Results include failed attempts and data gaps. These experiments are not proven profitable. Comparison figures use their own full test window.</p><div class="comparison-grid">${rows.map(f=>{const c=f.comparison;return `<article class="comparison-card"><h3>${e(f.name)}</h3><p class="small">Since ${e(new Date(c.started_at*1000).toLocaleString())}</p><dl><dt>Net P/L · marked positions included</dt><dd>${e(dollars(c.net_pnl))}${c.unpriced?' · quotes missing':''}</dd><dt>Realized P/L</dt><dd>${e(dollars(c.realized_pnl))}</dd><dt>Completed / first-filled finished attempts</dt><dd>${e(String(c.completed))} / ${e(String(c.first_fills))} · ${finite(c.completion_rate)?number(c.completion_rate*100,'%'):'—'}</dd><dt>Losses on unmatched attempts</dt><dd>${e(dollars(c.unmatched_losses))}</dd><dt>Maximum observed drawdown</dt><dd>${e(dollars(c.max_drawdown))}${c.drawdown_incomplete?' · incomplete quotes':''}</dd><dt>Average start-to-completion time</dt><dd>${number(finite(c.average_completion_seconds)?c.average_completion_seconds/60:null,' min')}</dd><dt>Capital committed × hours</dt><dd>${number(c.dollar_hours,' dollar-hours')}</dd><dt>Net profit / dollar-hour</dt><dd>${number(finite(c.profit_per_dollar_hour)?c.profit_per_dollar_hour*100:null,'¢')}</dd></dl><p class="small">${e(String(c.attempts))} finished attempts · ${e(String(c.open_attempts))} open. Drawdown uses observed snapshots; capital time includes bids and positions.</p></article>`}).join('')}</div></details>`;
}
export function folderSummaryValues(f,period='all',now=Date.now()/1000){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const account=f.accounting,a=account?.portfolio,positions=account?.positions||[];
 const balance=finite(a?.equity)?{low:Number(a.equity),high:Number(a.equity),unpriced:0}:shifted(valueBounds(a,positions),a?.cash);
 const result=f.performance?.[period];
 let pnl=accountPnl(a,positions);
 if(period!=='all'){
  const range=finite(result?.pnl)?{low:Number(result.pnl),high:Number(result.pnl),unpriced:0}:finite(result?.pnl_low)&&finite(result?.pnl_high)?{low:Number(result.pnl_low),high:Number(result.pnl_high),unpriced:result.unpriced?1:0}:null;
  pnl={text:rangeText(range),className:rangeClass(range),uncertain:!!range?.unpriced,available:!!range};
 }
 const since=result?.since?new Date(result.since*1000).toLocaleString():'';
 let detail=period==='all'?'Current session':result?.missing_history||!result?'Waiting for balance history':result.partial?'Tracked since '+since:'Rolling '+folderPeriods[period]+' · minute snapshots';
 if(pnl.uncertain)detail+=' · range includes unpriced positions';
 return {period,balance:rangeText(balance),balanceUncertain:!!balance?.unpriced,cash:dollars(a?.cash),pnl,detail,
  realized:result?.realized_pnl!=null?dollars(result.realized_pnl):null,stale:!!account&&now-account.at>30};
}
export function folderPeriodButtons(period,folderId=null){
 return Object.entries(folderPeriods).map(([key,label])=>`<button type="button" class="secondary" ${folderId?`data-folder-summary-period="${key}" data-summary-folder="${e(folderId)}"`:`data-folder-period="${key}"`} aria-pressed="${period===key}">${label}</button>`).join('');
}
export function folderCardSummaryMarkup(folder,period='all',counts={},now=Date.now()/1000){
 const v=folderSummaryValues(folder,period,now);
 const action=counts.running?'pause':'resume',label=counts.pending?'Saving…':counts.running?'Pause folder':'Resume folder';
 const control=counts.controls===false?'':`<button type="button" class="secondary folder-run-control" data-folder-${action}="${e(folder.id)}" aria-label="${counts.running?'Pause':'Resume'} all bots in ${e(folder.name)}" ${counts.pending||!counts.bots?'disabled':''}>${label}</button>`;
 return `<span class="folder-summary-heading"><span class="folder-name">${e(folder.name)}</span><span class="badge">${counts.bots||0} bots · ${counts.running||0} running</span>${control}<span class="folder-disclosure" aria-hidden="true"></span></span><span class="folder-card-values"><span><span class="folder-card-label">Balance now</span><strong class="${v.balanceUncertain?'value-range':''}">${e(v.balance)}</strong><small>Cash ${e(v.cash)}${v.stale?' · snapshot stale':''}</small></span><span><span class="folder-card-label">P/L · ${e(folderPeriods[v.period])}</span><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${v.period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong><small>${e(v.detail)}</small>${v.realized?`<small>Realized ${e(v.realized)}</small>`:''}</span></span><span class="folder-summary-periods" role="group" aria-label="P/L period for ${e(folder.name)}">${folderPeriodButtons(v.period,folder.id)}</span>`;
}
export function folderOverviewMarkup(folders,period='all',now=Date.now()/1000){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const rows=folders.map(f=>{
  const v=folderSummaryValues(f,period,now);
  return `<tr><th scope="row"><a href="#folder-${e(f.id)}">${e(f.name)}</a></th><td data-label="Balance now"><strong class="${v.balanceUncertain?'value-range':''}">${e(v.balance)}</strong><small>Cash ${e(v.cash)}${v.stale?' · snapshot stale':''}</small></td><td data-label="P/L · ${e(folderPeriods[period])}"><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong><small>${e(v.detail)}</small>${v.realized?`<small>Realized ${e(v.realized)}</small>`:''}</td></tr>`;
 }).join('');
 return `<div class="overview-heading"><h2>At a glance</h2><div class="folder-summary-periods" role="group" aria-label="P/L period for all folders">${folderPeriodButtons(period)}</div></div><div class="folder-overview-wrap"><table class="folder-overview"><thead><tr><th>Strategy folder</th><th>Balance now</th><th>P/L · ${e(folderPeriods[period])}</th></tr></thead><tbody>${rows}</tbody></table></div><p class="small">Balance is cash plus estimated position value. P/L includes realized and unrealized changes after paid fees, excluding added funds. Ranges include positions without quotes. Periods use minute snapshots in the current reset session; shorter tracking coverage is shown per folder.</p>`;
}

export function botPnlMarkup(bot,period='all',positions=[]){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const r=bot.performance?.[period],all=period==='all';
 const fallback=accountPnl(bot.account,positions);
 const total=finite(r?.pnl)?{low:Number(r.pnl),high:Number(r.pnl)}:finite(r?.pnl_low)&&finite(r?.pnl_high)?{low:Number(r.pnl_low),high:Number(r.pnl_high)}:null;
 const realized=finite(r?.realized_pnl)?Number(r.realized_pnl):all&&finite(bot.account?.realized_pnl)?Number(bot.account.realized_pnl):null;
 const unreal=total&&realized!==null?{low:total.low-realized,high:total.high-realized}:null;
 const text=total?rangeText(total):all?fallback.text:'—';
 const coverage=all?'Current session · all versions':r?.missing_history||!r?'Waiting for balance history':r.partial?`Partial window · tracked since ${new Date(r.since*1000).toLocaleString()}`:`Last ${folderPeriods[period]} · sampled to the minute`;
 return `<div class="bot-pnl-panel"><div class="bot-pnl-values"><div><span>Total P/L${all?'':' change'}</span><strong class="${total?rangeClass(total):all?fallback.className:''}">${e(text)}</strong></div><div><span>Realized P/L${all?'':' change'}</span><strong class="${pnlClass(realized)}">${e(dollars(realized))}</strong></div><div><span>${all?'Unrealized P/L':'Change in unrealized P/L'}</span><strong>${e(unreal?rangeText(unreal):all?dollars(bot.account?.unrealized_pnl):'—')}</strong></div></div>${botSummaryPeriodMarkup(bot.id,period,true)}<p class="small">${e(coverage)} · after fees${r?.unpriced?' · range includes unpriced positions':''}. Total P/L includes open-position value changes. Closed trades and confirmed settlements contribute to realized P/L.</p></div>`;
}

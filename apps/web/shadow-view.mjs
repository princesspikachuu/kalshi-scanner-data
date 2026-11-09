import {escapeHTML as e,botSummaryPeriodMarkup} from './demo-client.mjs';
export const dollars=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
export function favoriteCategoryRows(rows=[],combineSeries=false){
 const groups=new Map(),bands=['<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h'];
 for(const r of rows){
  if(r.price==null||!Number.isFinite(Number(r.price)))continue;
  const low=Math.floor((Number(r.price)*100+1e-7)/5)*5;
  const series=combineSeries?'combined':String(r.series||'');
  const key=JSON.stringify([series,combineSeries?'category':r.market_type,r.clock,low,r.horizon]);
  if(!groups.has(key))groups.set(key,{series,market_type:r.market_type,clock:r.clock,low,band:`${low}–${Math.min(low+4,95)}¢`,horizon:r.horizon,contracts:0,closed:0,resolved:0,winners:0,cost:0,net:0,unverified:0,holding_seconds:0,dollar_hours:0});
  const g=groups.get(key);
  for(const field of ['contracts','closed','resolved','winners','cost','net','unverified','holding_seconds','dollar_hours']){
   const n=Number(r[field]??0);if(Number.isFinite(n))g[field]+=n;
  }
 }
 return [...groups.values()].sort((a,b)=>a.series.localeCompare(b.series)||String(a.clock).localeCompare(String(b.clock))||a.low-b.low||bands.indexOf(a.horizon)-bands.indexOf(b.horizon));
}
function researchTable(rows,roundTrips=false){
 if(!rows.length)return '<p class="small">No recorded price-and-time entries yet. Earlier trades without entry timing are not assigned guessed categories.</p>';
 return `<div class="table-scroll"><table><thead><tr><th>Entry percentage tier</th><th>Time remaining at fill</th><th>Purchased</th><th>Still open</th><th>${roundTrips?'Completed contracts':'Settled'}</th><th>${roundTrips?'Profitable round trips':'Win rate'}</th><th>Average entry · fees included</th><th>Realized P/L</th><th>Average holding time</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${e(r.band)}</td><td>${e(r.horizon)} left${r.clock==='estimated_game_end'?' · estimated game end':''}</td><td>${r.contracts}</td><td>${Math.max(0,r.contracts-r.closed)}</td><td>${r.resolved}</td><td>${r.resolved>0?(100*r.winners/r.resolved).toFixed(1)+'%':'—'}</td><td>${r.contracts>0?(100*r.cost/r.contracts).toFixed(2)+'%':'—'}</td><td class="${pnlClass(r.net)}">${r.closed>0?e(dollars(r.net)):'— · no closed contracts'}</td><td>${r.closed>0?(r.holding_seconds/r.closed/60).toFixed(2)+' min':'—'}</td></tr>`).join('')}</tbody></table></div>`;
}
const researchNote='<p class="small">YES and NO purchases are combined by the purchased contract’s implied percentage and time remaining at fill. Win rates use settled contract quantities; unsettled outcomes stay pending. Price percentages are market prices, not proven outcome probabilities. P/L includes exits and fees. Research uses all collected data, independent of the P/L time selector. Bids are still gathering data and do not automatically adjust.</p>';
export function favoriteCategoryResearchMarkup(group,open=new Set()){
 if(group.id==='sports')return '';
 const rows=favoriteCategoryRows(group.bots.flatMap(b=>b.experiment?.entry_timing||[]),true);
 const key='favorites-category-'+group.id;
 return `<details class="favorite-research" data-research="${e(key)}" ${open.has(key)?'open':''}><summary>Combined data · time × percentage tier · ${e(group.label)}</summary><p class="small">Combined across ${group.bots.length} bots in this category.</p>${group.research_kind==='round_trips'?'<p class="small">Both contract directions are combined by entry percentage and time. Win rate measures profitable completed trades, including fees; it is not event prediction accuracy. Data includes all collected history.</p>':researchNote}${researchTable(rows,group.research_kind==='round_trips')}</details>`;
}
export function favoriteResearchMarkup(bots,open=new Set()){
 const contents=bots.map(bot=>{
  const rows=favoriteCategoryRows(bot.experiment?.entry_timing);
  const key='favorites-research-'+bot.id;
  return `<details class="favorite-research" data-research="${e(key)}" ${open.has(key)?'open':''}><summary>${e(bot.name)} · ${e(bot.series)} · ${rows.length} observed tiers</summary>${researchTable(rows)}</details>`;
 }).join('');
 return `<div class="favorite-research">${researchNote}${contents}</div>`;
}
/** Add a complementary 2D price x time view; keep every existing research table intact. */
export function favoriteCollectorOverviewMarkup(bots=[],open=new Set()){
 const HORIZONS=['<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h'];
 const PRICES=[70,75,80,85,90,95];
 const groups=marketTypeGroups(bots.filter(bot=>!bot.retired));
 const matrix=(rows,label)=>{
  const cells=new Map();
  for(const row of favoriteCategoryRows(rows,true)){
   if(!HORIZONS.includes(row.horizon)||!PRICES.includes(row.low))continue;
   const key=row.low+'|'+row.horizon;
   if(!cells.has(key))cells.set(key,{purchased:0,settled:0,winners:0,closed:0,net:0,cost:0,holding:0});
   const current=cells.get(key);
   current.purchased+=row.contracts;current.settled+=row.resolved;
   current.winners+=row.winners;current.closed+=row.closed;
   current.net+=row.net;current.cost+=row.cost;current.holding+=row.holding_seconds;
  }
  const head=HORIZONS.map(h=>'<th scope="col">'+e(h)+'</th>').join('');
  const body=PRICES.map(low=>{
   const bucket=low+'–'+Math.min(low+4,95)+'¢';
   return '<tr><th scope="row">'+e(bucket)+'</th>'+HORIZONS.map(h=>{
    const x=cells.get(low+'|'+h);
    if(!x||x.purchased===0)return '<td class="stat-empty">—</td>';
    const pending=Math.max(0,x.purchased-x.settled);
    const win=x.settled?(100*x.winners/x.settled).toFixed(1)+'%':'—';
    const pnl=x.closed?dollars(x.net):'—';
    const detail='Purchased '+x.purchased+' · settled '+x.settled+' · still open/unsettled '+pending+
       ' · net P/L '+pnl+' · win rate '+win;
    return '<td class="'+(x.settled?'stat-observed':'stat-sparse')+'"><details><summary><strong>'+e(win)+'</strong><small>n='+x.settled+' settled</small><small>'+e(pnl)+' P/L</small></summary><p class="small">'+e(detail)+'</p></details></td>';
   }).join('')+'</tr>';
  }).join('');
  return '<div class="table-scroll"><table class="favorite-stat-matrix"><caption>'+e(label)+'</caption><thead><tr><th scope="col">Entry price</th>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>';
 };
 if(!groups.length)return '<section class="favorite-collector-overview"><h3>High-Probability Favorites · price × time matrix</h3><p class="small">Collector evidence is not yet available.</p></section>';
 const sections=groups.map(group=>{
  const rows=group.bots.flatMap(bot=>bot.experiment?.entry_timing||[]);
  if(group.id==='sports'){
   return '<details class="favorite-collector-category" open><summary>'+e(group.label)+'</summary>'+
      group.bots.map(bot=>matrix(bot.experiment?.entry_timing||[],bot.name)).join('')+'</details>';
  }
  return '<details class="favorite-collector-category" open><summary>'+e(group.label)+'</summary>'+matrix(rows,group.label)+'</details>';
 }).join('');
 return '<section class="favorite-collector-overview" aria-label="High-Probability Favorites price by time matrix"><h3>High-Probability Favorites · price × time matrix</h3>'+
 '<p class="small">Rows are 5¢ entry-price buckets; columns are time remaining at fill. Each cell shows the settled win rate, number settled, and realized P/L. Open and unsettled observations are not counted as wins or losses; tap a cell for purchase and pending counts. Market categories are separate. The original detailed statistics remain below.</p>'+
 sections+'</section>';
}

export function favoriteTimingMarkup(rows){
 if(!rows?.length)return '<p class="small">Time × percentage research starts with the next verified entry fill. Earlier trades are not assigned guessed timings.</p>';
 return `<details class="favorite-timing"><summary>Entry percentage × time remaining · combined sides</summary>${researchNote}${researchTable(favoriteCategoryRows(rows))}</details>`;
}

export function favoriteStatisticsMatrixMarkup(statistics,open=new Set()){
 const grids=statistics?.matrix||[],min=Number(statistics?.min_samples||20);
 if(!grids.length)return '<p class="small">Statistics matrix will populate when verified, settled Favorites observations are available. No missing outcome is treated as a loss or a win.</p>';
 const num=n=>n===null||n===undefined?'—':Number(n).toFixed(1)+'%';
 const status=cell=>cell.eligibility==='evidence_candidate'?'Evidence candidate':cell.eligibility==='fallback_candidate'?'Fallback candidate · sparse cell':cell.eligibility==='exploration_candidate'?'Exploration opportunity · sparse':cell.eligibility==='insufficient_samples'?'Under-sampled':'Evidence rejected';
 return '<section class="statistics-matrices" aria-label="Statistics-backed Favorites evidence"><h3>Statistics-Backed Favorites · entry price × time</h3><p class="small">Each table pools verified, settled outcomes from Data-Collection Favorites and the statistical paper portfolio (shared event IDs count once). Sparse cells can be explored with separately capped paper trades; exploration does not imply profitability. Five-cent price tiers; original time resolution. Sample count is distinct resolved events, not contracts. Evidence candidates still require live maker fill, fees, slippage, and risk checks before an order. Unfilled maker bids are not assumed filled.</p>'+
 grids.map(grid=>{
   const byCell=new Map((grid.cells||[]).map(cell=>[cell.price_bucket+'|'+cell.horizon,cell]));
   return '<details class="favorite-stat-market" open><summary>'+e(grid.market_type)+'</summary><div class="table-scroll"><table class="favorite-stat-matrix"><thead><tr><th scope="col">Entry price</th>'+
   (grid.time_buckets||[]).map(time=>'<th scope="col">'+e(time)+'</th>').join('')+'</tr></thead><tbody>'+
   (grid.price_buckets||[]).map(price=>'<tr><th scope="row">'+e(price.replace('-', '–'))+'¢</th>'+
    (grid.time_buckets||[]).map(time=>{
      const cell=byCell.get(price+'|'+time);
      if(!cell||!cell.samples)return '<td class="stat-empty"><span class="small">No settled events</span></td>';
      const enough=cell.samples>=min,capable=['evidence_candidate','fallback_candidate'].includes(cell.eligibility);
      const label=status(cell);
      const fallback=cell.fallback_level!==cell.level&&cell.fallback_level!=='insufficient_samples'?
        'Fallback available: '+cell.fallback_level.replaceAll('_',' ')+' · n='+cell.fallback_samples:
        cell.fallback_level==='insufficient_samples'?'No reliable fallback':'Exact category/time evidence';
      const detail=['Exact-cell confidence lower bound: '+num(cell.lower===null?null:cell.lower*100),
        cell.fallback_lower===null||cell.fallback_lower===undefined?'':'Fallback confidence lower bound: '+num(cell.fallback_lower*100),
        'Net P/L: '+dollars(cell.realized_net),'Level: '+cell.level.replaceAll('_',' '),fallback,
        'Evidence is not a guarantee of maker execution; live fees and risk can still reject orders'].join(' · ');
      return '<td class="'+(enough?(capable?'stat-candidate':'stat-rejected'):'stat-sparse')+'"><details><summary><strong>n='+e(String(cell.samples))+'</strong><span>Wins '+e(num(cell.win_rate===null?null:cell.win_rate*100))+'</span><span>ROI '+e(num(cell.realized_roi===null?null:cell.realized_roi*100))+'</span><small>'+e(label)+'</small></summary><p class="small">'+e(detail)+'</p></details></td>';
    }).join('')+'</tr>').join('')+'</tbody></table></div></details>';
 }).join('')+'</section>';
}

export const pnlClass=value=>value===null||value===undefined?'':Number(value)>0?'positive':Number(value)<0?'negative':'';
export function executionMarkup(x){
 if(!x||!x.measured)return '<p class="small">Execution measurements will appear with the next worker snapshot.</p>';
 const rate=x.maker_fill_rate==null?'—':Number(x.maker_fill_rate).toFixed(1)+'%';
 return `<details class="advanced"><summary>Execution quality · latest cycle${x.data_valid?'':' · data gap'}</summary><p class="small">${e(x.scope)}. Public queue position is estimated; simulated fills are not exchange executions. ${e(String(x.latency_ms))}ms modeled ${x.worker_delay_included?'transport latency plus measured worker processing delay':'action latency'}.</p><div class="bot-stats">${[['Maker quantity filled / requested',`${x.maker_filled} / ${x.maker_requested} · ${rate}`],['Rejected / submitted orders',`${x.rejections} / ${x.orders}`],['Partial / attempted IOC sweeps',`${x.partial_iocs} / ${x.ioc_attempts}`],['IOC unfilled quantity',x.ioc_unfilled],['Partial-profit contracts sold',x.profit_contracts],['Net cash recovered by partial profits',dollars(x.profit_net_proceeds)],['Fees · entire cycle',dollars(x.cycle_fees)],['Taker slippage · entire cycle',dollars(x.cycle_taker_slippage)]].map(([k,v])=>`<div><span>${e(k)}</span><strong>${e(String(v))}</strong></div>`).join('')}</div><p class="small">Fill rate uses requested contract quantity, including rejected entries. Working bids remain in the denominator. Unfilled IOC quantities can include retries of the same position. Recovery proceeds include exit fees; they are cash receipts, not profit. Partial-profit target: ${(Number(x.partial_profit_price)*100).toFixed(0)}¢ or better, retaining at least one contract.</p></details>`;
}
const metric=(label,value,note='')=>`<div><span>${e(label)}</span><strong>${e(dollars(value))}</strong>${note?`<small>${e(note)}</small>`:''}</div>`;
const finite=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
export function valueBounds(a,positions=[],kind='position'){
 if(!a)return null;
 const exact=a[kind+'_value'];
 if(finite(exact))return {low:Number(exact),high:Number(exact),unpriced:0};
 const quantity=kind==='position'?Number(a.active_contracts||0)+Number(a.pending_contracts||0):Number(a[kind+'_contracts']||0);
 const owned=positions.filter(p=>kind==='position'||p.state===kind);
 let value=0,cost=0,covered=0,estimated=0;
 for(const p of owned){
  const q=Number(p.quantity||0);let mark=finite(p.value)?Number(p.value):null;
  if(mark===null){mark=finite(p.mark_price)?q*Number(p.mark_price):finite(p.price)?q*Number(p.price):finite(p.cost)?Number(p.cost):null;estimated+=q}
  if(mark===null)return null;
  value+=mark;covered+=q;cost+=Number(p.cost||0);
 }
 const totalCost=a[kind+'_cost'];
 if(quantity>covered){if(!finite(totalCost))return null;value+=Math.max(0,Number(totalCost)-cost);estimated+=quantity-covered}
 if(!quantity&&!owned.length&&finite(totalCost))value=Number(totalCost);
 return {low:value,high:value,unpriced:estimated};
}
const performanceEstimate=r=>finite(r?.pnl)?Number(r.pnl):finite(r?.pnl_estimate)?Number(r.pnl_estimate):finite(r?.realized_pnl)?Number(r.realized_pnl):null;
const point=value=>finite(value)?{low:Number(value),high:Number(value),unpriced:0}:null;
const shifted=(range,amount)=>range&&finite(amount)?{...range,low:range.low+Number(amount),high:range.high+Number(amount)}:null;
export const rangeText=range=>!range||range.low!==range.high?'—':dollars(range.low);
const rangeClass=range=>!range?'':range.high<0?'negative':range.low>0?'positive':'';
const rangedMetric=(label,range,note)=>`<div><span>${e(label)}</span><strong class="${range?.unpriced?'value-range':''}">${e(rangeText(range))}</strong><small>${e(note)}</small></div>`;
export function accountPnl(a,positions=[]){
 if(finite(a?.total_pnl))return {text:dollars(a.total_pnl),className:pnlClass(a.total_pnl),uncertain:!!a.valuation_estimated};
 const range=shifted(valueBounds(a,positions),Number(a?.realized_pnl)-Number(a?.position_cost));
 return {text:rangeText(range),className:rangeClass(range),uncertain:!!range?.unpriced};
}
export function pendingLabel(a){
 if(!a||!Number(a.pending_contracts))return 'No payment pending';
 if(a.pending_payout_state==='confirmed')return `Confirmed payout ${dollars(a.pending_value)}`;
 if(a.pending_payout_state==='estimated')return `Estimated value ${dollars(a.pending_value)} · outcome unconfirmed`;
 return 'Outcome unconfirmed · last available estimate';
}
export function exposureMarkup(a,positions=[]){
 if(!a)return '<p class="small">Waiting for the worker’s accounting snapshot…</p>';
 const unreal=finite(a.unrealized_pnl)?{low:Number(a.unrealized_pnl),high:Number(a.unrealized_pnl),unpriced:0}:shifted(valueBounds(a,positions),-Number(a.position_cost));
 return `<div class="money-grid bot-money">${metric('Unfilled buy bids',a.unfilled_bids,'Cash reserved, not spent')}${metric('Active positions · cost',a.active_cost,`Current value ${rangeText(valueBounds(a,positions,'active'))}`)}${metric('Awaiting settlement · cost',a.pending_cost,pendingLabel(a))}${rangedMetric('Open position P/L',unreal,unreal?.unpriced?'Best estimate · last available quote or entry price':'Current and pending positions · after entry fees')}</div>`;
}
export function accountMarkup(account,now=Date.now()/1000,positions=[]){
 if(!account)return '<p>Waiting for a consistent accounting snapshot…</p>';
 const a=account.portfolio,q=account.quality||{},noVerified=!Number(q.verified_cycles),gaps=Number(q.gap_cycles||0);
 const warning=noVerified?'No verified completed cycles yet. Account P/L includes unverified simulated trades.':gaps?`${gaps} cycles had data gaps. Every simulated trade is still included in account P/L.`:'';
 const value=valueBounds(a,positions),uncertain=!!value?.unpriced;
 const equity=finite(a.equity)?{low:Number(a.equity),high:Number(a.equity),unpriced:0}:shifted(value,a.cash);
 const pnl=finite(a.total_pnl)?{low:Number(a.total_pnl),high:Number(a.total_pnl),unpriced:0}:shifted(equity,-Number(a.deposits));
 const unreal=finite(a.unrealized_pnl)?{low:Number(a.unrealized_pnl),high:Number(a.unrealized_pnl),unpriced:0}:shifted(value,-Number(a.position_cost));
 return `<div class="portfolio-headlines"><div><span>Portfolio value · best current estimate</span><strong class="${uncertain?'value-range':''}">${e(rangeText(equity))}</strong><small>Cash plus the current value of positions</small></div><div><span>Total P/L · best current estimate · after fees</span><strong class="${rangeClass(pnl)} ${uncertain?'value-range':''}">${e(rangeText(pnl))}</strong><small>Lifetime · all bots and versions</small></div></div>
 <p class="small">Scalper and Market Maker positions use executable bid depth after exit fees. Other positions use current bids. The last verified bid or entry price provides the fallback estimate; unavailable depth is identified as estimated.</p>
 <div class="portfolio-breakdown">${metric('Realized P/L',a.realized_pnl,'Closed trades and settled contracts · after fees')}${rangedMetric('Unrealized P/L',unreal,uncertain?'Best estimate for positions still held':'Value change of positions still held')}${metric('Virtual funds added',a.deposits,'Starting bankroll plus refills; not profit')}</div>
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
 const names={weather:'Hourly weather',weather_daily:'Daily weather',hourly:'Hourly prices',sports:'Sports',market_maker:'Market Maker',complete_set:'Complete sets'};
 return `<details class="sequential-comparison monitoring-status"><summary>Market monitoring · ${e(String(m.subscribed_markets))} watched · ${e(String(m.entry_markets))} entry candidates</summary><p class="small">${e(m.reason)}. Positions, protective exits and live games awaiting the Favorites window retain monitoring. Their subscriptions count toward the total limit, separately from entry candidates. Existing positions stay monitored if capacity is exceeded.</p><div class="money-grid"><div><span>Protected monitoring</span><strong>${e(String(m.position_and_exit_markets))}</strong></div><div><span>Entry candidates</span><strong>${e(String(m.entry_markets))} / ${e(String(m.entry_candidates))}</strong></div><div><span>Total admission ceiling</span><strong>${e(String(m.subscribed_markets))} / ${e(String(m.total))}</strong></div><div><span>Pending feed inputs</span><strong>${e(String(m.backlog))}</strong></div></div><p class="small">${Object.entries(names).map(([k,label])=>`${label}: ${e(String(m.categories?.[k]||0))}`).join(' · ')}. Entry slots per category: ${e(String(m.per_category))} (complete sets: 4).</p><p class="small">Recent 95th-percentile processing lag: ${finite(m.lag_p95_seconds)?Number(m.lag_p95_seconds).toFixed(2)+'s':'waiting'} · ${e(String(m.rotated_markets))} candidates rotated out until their market closes. Capacity grows after sustained healthy processing and pauses new discovery during overload.</p></details>`;
}
export function sequentialComparisonMarkup(folders){
 const rows=folders.filter(f=>f.comparison);
 if(!rows.length)return '';
 const number=(v,suffix='')=>finite(v)?Number(v).toFixed(2)+suffix:'—';
 return `<details class="sequential-comparison"><summary>Sequential strategy comparison · ${rows.length} variants</summary><p class="small">New attempts since each comparison start; earlier baseline history is excluded here. Wallet summaries retain full history. Results include failed attempts and data gaps. These experiments are not proven profitable. Comparison figures use their own full test window.</p><div class="comparison-grid">${rows.map(f=>{const c=f.comparison;return `<article class="comparison-card"><h3>${e(f.name)}</h3><p class="small">Since ${e(new Date(c.started_at*1000).toLocaleString())}</p><dl><dt>Net P/L · marked positions included</dt><dd>${e(dollars(c.net_pnl))}${c.unpriced?' · quotes missing':''}</dd><dt>Realized P/L</dt><dd>${e(dollars(c.realized_pnl))}</dd><dt>Completed / first-filled finished attempts</dt><dd>${e(String(c.completed))} / ${e(String(c.first_fills))} · ${finite(c.completion_rate)?number(c.completion_rate*100,'%'):'—'}</dd><dt>Losses on unmatched attempts</dt><dd>${e(dollars(c.unmatched_losses))}</dd><dt>Maximum observed drawdown</dt><dd>${e(dollars(c.max_drawdown))}${c.drawdown_incomplete?' · incomplete quotes':''}</dd><dt>Average start-to-completion time</dt><dd>${number(finite(c.average_completion_seconds)?c.average_completion_seconds/60:null,' min')}</dd><dt>Capital committed × hours</dt><dd>${number(c.dollar_hours,' dollar-hours')}</dd><dt>Net profit / dollar-hour</dt><dd>${number(finite(c.profit_per_dollar_hour)?c.profit_per_dollar_hour*100:null,'¢')}</dd></dl><p class="small">${e(String(c.attempts))} finished attempts · ${e(String(c.open_attempts))} open. Drawdown uses observed snapshots; capital time includes bids and positions.</p></article>`}).join('')}</div></details>`;
}
export function marketTypeGroups(bots){
 const groups=new Map();
 for(const bot of bots){
  const series=String(bot.series||'').toUpperCase(),asset=bot.asset;
  const period=series.endsWith('15M')?'15m':asset==='hourly'?'hourly':'';
  let id,label,rank;
  if(bot.strategy==='market_maker'){id='maker-'+bot.market_category;label=({'politics':'Politics','economics':'Economics / Finance','sports_futures':'Sports Futures','entertainment':'Entertainment / Culture'})[bot.market_category]||'Market Maker';rank=5}
  else if(asset==='weather'){id='weather-hourly';label='Hourly weather';rank=40}
  else if(asset==='weather_daily'){id='weather-daily';label='Daily weather';rank=50}
  else if(asset==='sports'){id='sports';label='Sports';rank=60}
  else if(bot.strategy==='complete_set'||series==='ALL_SAME_DAY'){id='complete-sets';label='Complete-set scanner';rank=70}
  else{
   let category='other',name='Other market types';rank=90;
   if(/^KX(BTC|ETH|SOL|XRP|DOGE|BNB|HYPE|ZEC|NEAR)(15M|D|H)?$/.test(series)){category='crypto';name='Crypto';rank=10}
   else if(/^KX(GOLD|SILVER|PLATINUM|PALLADIUM|COPPER|WTI|NATGAS|BRENT)(15M|H|D)?$/.test(series)){category='commodities';name='Commodities';rank=20}
   else if(/^KX(USDCAD|AUDUSD|USDJPY|GBPUSD|EURUSD|2YRRATE|5YRRATE|10YRRATE|30YRRATE|INX|NDQ|NASDAQ100)(15M|AH|H|U|D)?$/.test(series)){category='finance';name='Finance';rank=30}
   id=category+(period?'-'+period:'');label=name+(period==='15m'?' · 15 minutes':period==='hourly'?' · 1 hour':'');
   if(period==='hourly')rank+=1;
  }
  if(!groups.has(id))groups.set(id,{id,label,rank,bots:[]});
  groups.get(id).bots.push(bot);
 }
 for(const group of groups.values())group.bots.sort((a,b)=>
  Number(a.desired==='paused')-Number(b.desired==='paused')||
  String(a.name||a.series).localeCompare(String(b.name||b.series)));
 return [...groups.values()].sort((a,b)=>a.rank-b.rank||a.label.localeCompare(b.label));
}
export function summaryExposure(a){
 const number=key=>finite(a?.[key])?Number(a[key]):null;
 const bids=number('unfilled_bids'),active=number('active_cost'),pending=number('pending_cost');
 const positions=active!==null&&pending!==null?active+pending:number('position_cost');
 return {bids,active,pending,positions};
}
function exposureHeaderMarkup(a){
 const x=summaryExposure(a);
 return `<span class="exposure-header-value"><span class="folder-card-label">Open bids</span><strong>${e(dollars(x.bids))}</strong><small>Reserved for buys · now</small></span><span class="exposure-header-value"><span class="folder-card-label">Open/pending positions</span><strong>${e(dollars(x.positions))}</strong><small>Open ${e(dollars(x.active))} · pending ${e(dollars(x.pending))}</small><small>Money committed · includes entry fees</small><small>Estimated market value ${e(dollars(a?.position_value))}</small></span>`;
}
export function marketTypeSummaryValues(bots,period='all',positions=[]){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 let low=0,high=0,missing=0,partial=false;
 const exposure=bots.map(b=>summaryExposure(b.account));
 const sum=field=>exposure.every(x=>finite(x[field]))?exposure.reduce((n,x)=>n+x[field],0):null;
 for(const bot of bots){
  const r=bot.performance?.[period],a=bot.account;
  partial ||= !!r?.partial;
  let bounds=!r?.missing_history?point(performanceEstimate(r)):null;
  if(!bounds&&period==='all'){
   if(finite(a?.total_pnl))bounds={low:Number(a.total_pnl),high:Number(a.total_pnl)};
   else if(finite(a?.realized_pnl)&&finite(a?.position_cost)){
    const owned=positions.filter(p=>p.bot_id?p.bot_id===bot.id:p.ticker?.startsWith(bot.series+'-'));
    bounds=shifted(valueBounds(a,owned),Number(a.realized_pnl)-Number(a.position_cost));
   }
  }
  if(!bounds||bounds.low>bounds.high)missing++;
  else{low+=bounds.low;high+=bounds.high}
 }
 const pnl=missing?null:{low,high,unpriced:low!==high};
 return {period,pnl,missing,partial,account:{unfilled_bids:sum('bids'),active_cost:sum('active'),
  pending_cost:sum('pending'),position_cost:sum('positions')}};
}
export function marketTypeSummaryMarkup(group,period='all',positions=[],shown=null){
 const v=marketTypeSummaryValues(group.bots,period,positions);
 const running=group.bots.filter(b=>b.desired==='running').length;
 const coverage=v.missing?`${v.missing} ${v.missing===1?'bot':'bots'} missing P/L history`:v.partial?'Partial P/L history':v.period==='all'?'Current session':'Rolling '+folderPeriods[v.period];
 return `<span class="market-type-heading"><span class="market-type-name">${e(group.label)}</span><span class="badge">${group.bots.length} bots · ${running} running${shown!==null?' · '+shown+' shown':''}</span><span class="market-type-disclosure" aria-hidden="true"></span></span><span class="folder-card-values market-type-values"><span class="summary-total-pnl"><span class="folder-card-label">Total P/L · ${e(folderPeriods[v.period])}</span><strong class="${rangeClass(v.pnl)} ${v.pnl?.unpriced?'value-range':''}">${e(rangeText(v.pnl))}</strong><small>${e(coverage)} · after fees</small></span>${exposureHeaderMarkup(v.account)}</span><span class="small market-type-coverage">P/L follows the folder’s time selector. Exposure shows current amounts for all bots in this subfolder.</span>`;
}
export function folderSummaryValues(f,period='all',now=Date.now()/1000){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const account=f.accounting,a=account?.portfolio,positions=account?.positions||[];
 const balance=finite(a?.equity)?{low:Number(a.equity),high:Number(a.equity),unpriced:0}:shifted(valueBounds(a,positions),a?.cash);
 const result=f.performance?.[period];
 let pnl=accountPnl(a,positions);
 if(period!=='all'){
  const range=point(performanceEstimate(result));
  pnl={text:rangeText(range),className:rangeClass(range),uncertain:!!range?.unpriced,available:!!range};
 }
 const since=result?.since?new Date(result.since*1000).toLocaleString():'';
 let detail=period==='all'?'Current session':result?.missing_history||!result?'Waiting for balance history':result.partial?'Tracked since '+since:'Rolling '+folderPeriods[period]+' · minute snapshots';
 if(pnl.uncertain)detail+=' · estimate uses fallback position marks';
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
 return `<span class="folder-summary-heading"><span class="folder-name">${e(folder.name)}</span><span class="badge">${counts.bots||0} bots · ${counts.running||0} running</span>${control}<span class="folder-disclosure" aria-hidden="true"></span></span><span class="folder-card-values"><span class="summary-total-pnl"><span class="folder-card-label">Total P/L · ${e(folderPeriods[v.period])}</span><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${v.period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong><small>${e(v.detail)}${v.stale?' · snapshot stale':''}</small>${v.realized?`<small>Realized ${e(v.realized)}</small>`:''}</span>${exposureHeaderMarkup(folder.accounting?.portfolio)}</span><span class="folder-summary-periods" role="group" aria-label="P/L period for ${e(folder.name)}">${folderPeriodButtons(v.period,folder.id)}</span>`;
}
export function folderOverviewMarkup(folders,period='all',now=Date.now()/1000){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const rows=folders.map(f=>{
  const v=folderSummaryValues(f,period,now),x=summaryExposure(f.accounting?.portfolio);
  return `<tr><th scope="row"><a href="#folder-${e(f.id)}">${e(f.name)}</a></th><td class="summary-total-pnl" data-label="Total P/L · ${e(folderPeriods[period])}"><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong><small>${e(v.detail)}${v.stale?' · snapshot stale':''}</small>${v.realized?`<small>Realized ${e(v.realized)}</small>`:''}</td><td data-label="Open bids"><strong>${e(dollars(x.bids))}</strong><small>Reserved for buys · now</small></td><td data-label="Open/pending positions"><strong>${e(dollars(x.positions))}</strong><small>Open ${e(dollars(x.active))} · pending ${e(dollars(x.pending))}</small><small>Money committed · includes entry fees</small></td></tr>`;
 }).join('');
 return `<div class="overview-heading"><h2>At a glance</h2><div class="folder-summary-periods" role="group" aria-label="P/L period for all folders">${folderPeriodButtons(period)}</div></div><div class="folder-overview-wrap"><table class="folder-overview"><thead><tr><th>Strategy folder</th><th>Total P/L · ${e(folderPeriods[period])}</th><th>Open bids</th><th>Open/pending positions</th></tr></thead><tbody>${rows}</tbody></table></div><p class="small">P/L includes realized and unrealized changes after paid fees, excluding added funds. Open bids show cash reserved for buys; positions show committed cost including entry fees. Exposure amounts are current, independent of the selected P/L period. P/L uses the best available position marks; older baselines without quotes carry positions at cost. Shorter tracking coverage is shown per folder.</p>`;
}

export function botPnlMarkup(bot,period='all',positions=[]){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const r=bot.performance?.[period],all=period==='all';
 const fallback=accountPnl(bot.account,positions);
 const total=point(performanceEstimate(r));
 const realized=finite(r?.realized_pnl)?Number(r.realized_pnl):all&&finite(bot.account?.realized_pnl)?Number(bot.account.realized_pnl):null;
 const unreal=total&&realized!==null?{low:total.low-realized,high:total.high-realized}:null;
 const text=total?rangeText(total):all?fallback.text:'—';
 const coverage=all?'Current session · all versions':r?.missing_history||!r?'Waiting for balance history':r.partial?`Partial window · tracked since ${new Date(r.since*1000).toLocaleString()}`:`Last ${folderPeriods[period]} · sampled to the minute`;
 return `<div class="bot-pnl-panel"><div class="bot-pnl-values"><div class="summary-total-pnl"><span>Total P/L${all?'':' change'}</span><strong class="${total?rangeClass(total):all?fallback.className:''}">${e(text)}</strong></div>${exposureHeaderMarkup(bot.account)}</div>${botSummaryPeriodMarkup(bot.id,period,true)}<p class="small">${e(coverage)} · after fees${r?.unpriced?' · estimate uses fallback position marks':''}. ${all?'Realized P/L':'Realized P/L change'} ${e(dollars(realized))} · ${all?'Unrealized P/L':'Change in unrealized P/L'} ${e(unreal?rangeText(unreal):all?dollars(bot.account?.unrealized_pnl):'—')}. Exposure amounts show money reserved or committed now, independent of the P/L window.</p></div>`;
}

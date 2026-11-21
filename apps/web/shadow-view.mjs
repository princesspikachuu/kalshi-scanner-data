import {escapeHTML as e,botSummaryPeriodMarkup} from './demo-client.mjs';
export const dollars=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
export function favoriteCategoryRows(rows=[],combineSeries=false){
 const groups=new Map(),bands=['<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h'];
 for(const r of rows){
  if(r.price==null||!Number.isFinite(Number(r.price)))continue;
  const low=Math.floor((Number(r.price)*100+1e-7)/5)*5;
  const series=combineSeries?'combined':String(r.series||'');
  const key=JSON.stringify([series,combineSeries?'category':r.market_type,r.clock,low,r.horizon]);
  if(!groups.has(key))groups.set(key,{series,market_type:r.market_type,clock:r.clock,low,band:`${low}–${Math.min(low+4,95)}¢`,horizon:r.horizon,contracts:0,closed:0,resolved:0,winners:0,profitable_closed:0,profit_classified_closed:0,cost:0,net:0,unverified:0,holding_seconds:0,dollar_hours:0,events:0,event_wins:0,return_events:{},outcome_events:{},return_sum:0,return_observations:0,estimated_return_observations:0});
  const g=groups.get(key);
  for(const field of ['contracts','closed','resolved','winners','profitable_closed','profit_classified_closed','cost','net','unverified','holding_seconds','dollar_hours']){
   const n=Number(r[field]??0);if(Number.isFinite(n))g[field]+=n;
  }
  if(r.return_events){
   for(const [event,value] of Object.entries(r.return_events)){
    const v=g.return_events[event]??={cost:0,net:0};v.cost+=Number(value.cost);v.net+=Number(value.net);v.estimated ||= !!value.estimated;
   }
  }else{
   g.return_sum+=Number(r.return_sum)||0;g.return_observations+=Number(r.return_observations)||0;g.estimated_return_observations+=Number(r.estimated_return_observations)||0;
  }
  if(r.outcome_events){
   for(const [event,value]of Object.entries(r.outcome_events))g.outcome_events[event]=Math.min(g.outcome_events[event]??1,Number(value));
  }
  const n=Number(r.events),w=r.event_wins!=null?Number(r.event_wins):Number(r.event_win_rate)*n/100;
  if(!r.outcome_events&&Number.isInteger(n)&&n>0){g.events+=n;if(Number.isFinite(w))g.event_wins+=w;}
 }
 for(const g of groups.values()){
  g.events+=Object.keys(g.outcome_events).length;g.event_wins+=Object.values(g.outcome_events).reduce((a,b)=>a+b,0);
  for(const value of Object.values(g.return_events))if(value.cost>0){g.return_sum+=value.net/value.cost;g.return_observations++;if(value.estimated)g.estimated_return_observations++;}
 }
 return [...groups.values()].sort((a,b)=>a.series.localeCompare(b.series)||String(a.clock).localeCompare(String(b.clock))||a.low-b.low||bands.indexOf(a.horizon)-bands.indexOf(b.horizon));
}
// This signal reflects settlement-based win margin, never realized exit P/L.
export function favoriteProfitSignal({purchased,settled,winners,cost}){
 const qty=Number(purchased),n=Number(settled),wins=Number(winners),entryCost=Number(cost);
 if(!(qty>0&&n>0)||![qty,n,wins,entryCost].every(Number.isFinite)||wins<0||wins>n)return 'unknown';
 const margin=wins/n-entryCost/qty;
 return margin>0?'realized-positive':margin<0?'realized-negative':'neutral';
}
const favoriteProfitClass=signal=>({
 'realized-positive':'profit-positive','realized-negative':'profit-negative'
})[signal]||'';
export const favoriteProfitLegendMarkup=(mode='detailed')=>mode==='single'?'<p class="small favorite-profit-legend"><strong>Colors:</strong> 🟢 Positive hold P/L · 🔴 Negative hold P/L</p>':'<p class="small favorite-profit-legend"><strong>Colors:</strong> 🟢 Positive win margin · 🔴 Negative win margin · blank when margin is unavailable</p>';
const observationCount=n=>Number.isInteger(Number(n))?String(Number(n)):'—';
const averageReturn=r=>Number(r.return_observations)>0&&Number.isFinite(Number(r.return_sum))?(100*Number(r.return_sum)/Number(r.return_observations)).toFixed(2)+'%':'—';
const eventAccuracy=(wins,n)=>n>0?(100*wins/n).toFixed(1)+'%':'—';
export function winConfidence90(wins,n,entryCost=null){
 if(!(n>0)||!Number.isFinite(wins)||wins<0||wins>n)return null;
 const z=1.6448536269514722,p=wins/n,den=1+z*z/n;
 const center=(p+z*z/(2*n))/den,half=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;
 const low=Math.max(0,center-half),high=Math.min(1,center+half);
 return {low,high,error:Math.max(p-low,high-p),margin:entryCost===null?null:p-entryCost};
}
const pointText=n=>n===null?'—':(n>0?'+':'')+(n*100).toFixed(1)+' points';
const confidenceMarkup=(wins,n,cost)=>{
 const c=winConfidence90(wins,n,cost);
 return c?{margin:pointText(c.margin),error:'±'+(100*c.error).toFixed(1)+' points',interval:(100*c.low).toFixed(1)+'–'+(100*c.high).toFixed(1)+'%'}:{margin:'—',error:'—',interval:'—'};
};
function researchTable(rows,roundTrips=false){
 if(!roundTrips)rows=rows.filter(r=>Number(r.events)>0);
 if(!rows.length)return '<p class="small">No timed observations yet.</p>';
 return `<div class="table-scroll"><table><thead><tr><th>Entry price</th><th>Time remaining</th><th>${roundTrips?'Completed cycles':'Resolved observations'}</th><th>${roundTrips?'Profitable cycles':'Outcome win rate'}</th><th>Average entry · with fees</th>${roundTrips?'':'<th>Win margin</th><th>Uncertainty · 90%</th>'}<th>${roundTrips?'Realized P/L':'Average P/L %'}</th><th>Average holding time</th></tr></thead><tbody>${rows.map(r=>{
  const n=Number(r.events)||0,wins=Number(r.event_wins)||0;
  const confidence=confidenceMarkup(wins,n,r.contracts>0?r.cost/r.contracts:null);
  const displayNet=roundTrips?r.net:(r.return_observations>0?r.return_sum:null);
  const margin=winConfidence90(wins,n,r.contracts>0?r.cost/r.contracts:null)?.margin;
  const signal=roundTrips?(r.closed>0?(r.net>0?'realized-positive':r.net<0?'realized-negative':'neutral'):'unknown'):(margin==null?'unknown':margin>0?'realized-positive':margin<0?'realized-negative':'neutral');
  return `<tr class="${favoriteProfitClass(signal)}"><td>${e(r.band)}</td><td>${e(r.horizon)} left${r.clock==='estimated_game_end'?' · estimated game end':''}</td><td>${observationCount(n)}</td><td>${eventAccuracy(wins,n)}</td><td>${r.contracts>0?(100*r.cost/r.contracts).toFixed(2)+'%':'—'}</td>${roundTrips?'':`<td>${e(confidence.margin)}</td><td>${e(confidence.error)}<small>CI ${e(confidence.interval)}</small></td>`}<td class="${roundTrips?pnlClass(displayNet):''}">${e(roundTrips?(r.closed>0?dollars(r.net):'—'):averageReturn(r))}${!roundTrips&&r.return_observations>0?'<small>'+r.return_observations+' return observations'+(r.estimated_return_observations>0?' · '+r.estimated_return_observations+' estimated':'')+'</small>':''}</td><td>${r.closed>0&&finite(r.holding_seconds)?(r.holding_seconds/r.closed/60).toFixed(2)+' min':'—'}</td></tr>`}).join('')}</tbody></table></div>`;
}
// Favorites research uses the same compact price x time cell layout as the
// top-level summary. The single folder toggle determines which buckets appear.
function favoriteResearchGrid(rows=[],options={}){
 if(!rows.length||!rows.some(r=>Number(r.events)>0))return '<p class="small">No verified resolved timed observations yet.</p>';
 const clockNote=rows.some(r=>r.clock==='estimated_game_end')?'<p class="small">Sports time remaining uses estimated game end.</p>':'';
 const wide=options.mode==='wide';
 const horizons=['<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h'];
 const timeLabels=wide?(options.timeBuckets?.length?options.timeBuckets:['Early third','Middle third','Final third']):
   [...new Set([...horizons,...rows.map(r=>String(r.horizon||''))])].filter(t=>rows.some(r=>String(r.horizon||'')===t));
 const keys=wide?timeLabels.map((_,i)=>String(i)):timeLabels;
 const prices=[...new Set(rows.map(r=>String(r.band||'')))].sort((a,b)=>(parseInt(a,10)||0)-(parseInt(b,10)||0));
 const cells=new Map(rows.map(r=>[String(r.band||'')+'|'+(wide?String(r.time_slot):String(r.horizon||'')),r]));
 const body=prices.map(price=>'<tr><th scope="row">'+e(price)+'</th>'+keys.map(key=>{
  const r=cells.get(price+'|'+key);
  if(!r)return '<td class="stat-empty">—</td>';
  const n=Number(r.events)||0,wins=Number(r.event_wins)||0;
  if(!n)return '<td class="stat-empty">—</td>';
  const entry=Number(r.contracts)>0?Number(r.cost)/Number(r.contracts):null;
  const c=confidenceMarkup(wins,n,entry),ret=averageReturn(r);
  const margin=winConfidence90(wins,n,entry)?.margin;
  const signal=margin===null||margin===undefined?'unknown':margin>0?'realized-positive':margin<0?'realized-negative':'neutral';
  return '<td class="stat-observed '+favoriteProfitClass(signal)+'"><details><summary><strong>n='+e(observationCount(n))+'</strong><small>Wins '+e(eventAccuracy(wins,n))+' · Hold P/L '+e(ret)+'</small><small>Margin '+e(c.margin)+' · error '+e(c.error)+'</small></summary><p class="small">90% win-rate interval '+e(c.interval)+' · '+e(String(r.return_observations||0))+' hold-return observations. Settlement-based margin; exits excluded.</p></details></td>';
 }).join('')+'</tr>').join('');
 return clockNote+'<div class="table-scroll"><table class="'+(wide?'favorite-stat-matrix favorite-wide-matrix':'favorite-stat-matrix')+'"><thead><tr><th scope="col">Entry price</th>'+timeLabels.map(t=>'<th scope="col">'+e(t)+(wide?' left':'')+'</th>').join('')+'</tr></thead><tbody>'+body+'</tbody></table></div>';
}
// Single bucket uses event-level backend evidence, never sums overlapping 3x3 cells.
export function favoriteSingleCellMarkup(sample){
 const finitePercent=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
 if(!sample)return '<p class="small">Event-level combined evidence is not available yet. Refresh after the API update; existing tables are unchanged.</p>';
 const n=Number(sample.return_observations)||0,resolved=Number(sample.resolved_events)||0;
 const mean=finitePercent(sample.average_return_pct)?Number(sample.average_return_pct):null;
 const error=finitePercent(sample.uncertainty90_pct)?Number(sample.uncertainty90_pct):null;
 const low=finitePercent(sample.ci90_low_pct)?Number(sample.ci90_low_pct):null;
 const high=finitePercent(sample.ci90_high_pct)?Number(sample.ci90_high_pct):null;
 const result=mean===null?'—':(mean>0?'+':'')+mean.toFixed(2)+'%';
 const uncertainty=error===null?'Not available · fewer than 2 independent return observations':'±'+error.toFixed(2)+' percentage points';
 const interval=low===null||high===null?'':(' · 90% interval '+low.toFixed(2)+'% to '+high.toFixed(2)+'%');
 const signal=mean===null?'':mean>0?'profit-positive':mean<0?'profit-negative':'';
 const win=resolved>0?eventAccuracy(Number(sample.event_wins)||0,resolved):'—';
 const missing=Number(sample.incomplete_events)||0,estimated=Number(sample.estimated_return_observations)||0;
 return '<div class="table-scroll"><table class="favorite-stat-matrix favorite-single-matrix"><thead><tr><th scope="col">All entry prices × all times</th></tr></thead><tbody><tr><td class="stat-observed '+signal+'"><strong>'+e(result)+' Hold P/L</strong><small>90% P/L uncertainty: '+e(uncertainty)+'</small><small>n='+e(String(n))+' distinct event returns · outcome win rate '+e(win)+(resolved!==n?' ('+e(String(resolved))+' resolved)':'')+'</small><details><summary>Evidence details</summary><p class="small">'+e(interval?interval.slice(3):'90% interval unavailable until at least 2 independent returns.')+' · '+e(String(estimated))+' estimated return observations · '+e(String(missing))+' resolved events without complete hold returns. A repeated event across entry buckets contributes one cost-weighted hold return. Returns ignore early exits and include entry fees.</p></details></td></tr></tbody></table></div>';
}
const researchNote='<p class="small">Counts are distinct verified resolved events per price/time cohort, not contracts. Ten contracts from one event count as one observation. One event may appear in multiple cohorts. Hold-only P/L % gives each resolved event equal weight, after fees. Known outcomes assume holding to settlement, ignoring exit proceeds and exit fees. Unknown outcomes are omitted. Estimated historical returns use average entry fees/sizing; account balances retain actual trades.</p>';
export function favoriteCategoryResearchMarkup(group,open=new Set(),options={}){
 const rows=options.mode==='wide'?(options.summary?.rows?.[group.id]||[]):favoriteCategoryRows(Array.isArray(group.aggregated_entry_timing)?group.aggregated_entry_timing:group.bots.flatMap(b=>b.experiment?.entry_timing||[]),true);
 const key='favorites-category-'+group.id;
 return `<details class="favorite-research" data-research="${e(key)}" ${open.has(key)?'open':''}><summary>Combined data · time × percentage tier · ${e(group.label)}</summary><p class="small">Combined across ${group.bots.length} bots in this category.</p>${group.research_kind==='round_trips'?'<p class="small">Both contract directions are combined by entry percentage and time. Win rate measures profitable completed trades, including fees; it is not event prediction accuracy. Data includes all collected history.</p>':researchNote}${group.research_kind==='round_trips'?researchTable(rows,true):options.mode==='single'?favoriteSingleCellMarkup(options.singleSummary?.rows?.[group.id]):favoriteResearchGrid(rows,{mode:options.mode,timeBuckets:options.summary?.coverage?.[group.id]?.time_buckets})}</details>`;
}
export function favoriteResearchMarkup(bots,open=new Set(),options={}){
 const contents=bots.map(bot=>{
  const rows=options.mode==='wide'?(options.summary?.by_bot?.[bot.id]?.rows||[]):favoriteCategoryRows(bot.experiment?.entry_timing);
  const key='favorites-research-'+bot.id;
  return `<details class="favorite-research" data-research="${e(key)}" ${open.has(key)?'open':''}><summary>${e(bot.name)} · ${e(bot.series)} · ${rows.length} observed tiers</summary>${options.mode==='single'?favoriteSingleCellMarkup(options.singleSummary?.by_bot?.[bot.id]):favoriteResearchGrid(rows,{mode:options.mode,timeBuckets:options.summary?.coverage?.[marketTypeGroups([bot])[0]?.id]?.time_buckets})}</details>`;
 }).join('');
 return `<div class="favorite-research">${researchNote}${contents}</div>`;
}
/** Add a complementary 2D price x time view; keep every existing research table intact. */
export function favoriteCollectorOverviewMarkup(bots=[],open=new Set(),source={}){
 const HORIZONS=['<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h'];
 const PRICES=[70,75,80,85,90,95];
 // Keep 15-minute and hourly cohorts separate; each pools its currencies.
 const groups=marketTypeGroups(bots);
 const matrix=(rows,label)=>{
  const cells=new Map();
  const aggregated=favoriteCategoryRows(rows,true);
  // Do not silently drop valid collected tiers that fall outside the strategy's
  // usual 70-95 cent bidding range. The per-market tables already show them.
  const prices=[...new Set([...PRICES,...aggregated.map(row=>row.low)
   .filter(low=>Number.isInteger(low)&&low>=0&&low<=100)])].sort((a,b)=>a-b);
  let unplaced=0;
  for(const row of aggregated){
   if(!HORIZONS.includes(row.horizon)||!prices.includes(row.low)){
    unplaced+=Number(row.events)||0;
    continue;
   }
   const key=row.low+'|'+row.horizon;
   if(!cells.has(key))cells.set(key,{purchased:0,settled:0,winners:0,closed:0,profitable:0,profitClassified:0,net:0,cost:0,holding:0,events:0,eventWins:0,return_sum:0,return_observations:0,estimated_return_observations:0});
   const current=cells.get(key);
   current.purchased+=row.contracts;current.settled+=row.resolved;
   current.winners+=row.winners;current.closed+=row.closed;
   current.profitable+=row.profitable_closed;current.profitClassified+=row.profit_classified_closed;
   current.net+=row.net;current.cost+=row.cost;current.holding+=row.holding_seconds;
   current.return_sum+=row.return_sum;current.return_observations+=row.return_observations;current.estimated_return_observations+=row.estimated_return_observations;
   current.events+=Number(row.events)||0;current.eventWins+=Number(row.event_wins)||0;
  }
  // Mobile viewers see only the leftmost time windows at first. Summarize
  // all actually populated windows before the horizontally scrollable table.
  const windowTotals=new Map();
  for(const [key,cell] of cells){
   const time=key.split('|')[1];
   windowTotals.set(time,(windowTotals.get(time)||0)+cell.events);
  }
  const observedWindows=HORIZONS.filter(time=>(windowTotals.get(time)||0)>0);
  const windowNote='<p class="small">Observed time windows: '+
    (observedWindows.length?observedWindows.map(time=>e(time)+' ('+e(String(Number(windowTotals.get(time).toFixed(2))))+' resolved observations)').join(' · '):
    'No verified resolved timed events in this category')+
    '. Scroll the table horizontally for the other time columns.</p>';
  const head=HORIZONS.map(h=>'<th scope="col">'+e(h)+'</th>').join('');
  const body=prices.map(low=>{
   const bucket=low+'–'+Math.min(low+4,95)+'¢';
   return '<tr><th scope="row">'+e(bucket)+'</th>'+HORIZONS.map(h=>{
    const x=cells.get(low+'|'+h);
    if(!x||x.purchased===0||x.events===0)return '<td class="stat-empty">—</td>';
    const observations=x.events;
    const outcome=eventAccuracy(x.eventWins,observations);
    const pnl=averageReturn(x);
    const confidence=confidenceMarkup(x.eventWins,observations,x.purchased?x.cost/x.purchased:null);
    const margin=winConfidence90(x.eventWins,observations,x.purchased?x.cost/x.purchased:null)?.margin;
    const signal=margin==null?'unknown':margin>0?'realized-positive':margin<0?'realized-negative':'neutral';
    const detail=observationCount(observations)+' verified resolved event observations · '+outcome+' outcome win rate · '+pnl+' average P/L · win margin '+confidence.margin+' · 90% uncertainty '+confidence.error+' (CI '+confidence.interval+') · '+x.return_observations+' return observations. Each event counts once per cohort, regardless of contract quantity.';
    return '<td class="'+(observations?'stat-observed':'stat-sparse')+' '+favoriteProfitClass(signal)+'"><details><summary><strong>n='+e(observationCount(observations))+'</strong><small>Outcome wins '+e(outcome)+'</small><small>'+e(pnl)+' avg P/L</small><small>Win margin '+e(confidence.margin)+' · uncertainty '+e(confidence.error)+'</small>'+'</summary><p class="small">'+e(detail)+'</p></details></td>';
   }).join('')+'</tr>';
  }).join('');
  return windowNote+(unplaced?'<p class="small">Unclassified timing/price: '+e(observationCount(unplaced))+' resolved observations. See individual market research for source details.</p>':'')+'<div class="table-scroll"><table class="favorite-stat-matrix"><caption>'+e(label)+'</caption><thead><tr><th scope="col">Entry price</th>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>';
 };
 if(!groups.length)return '<section class="favorite-collector-overview"><h3>High-Probability Favorites · price × time matrix</h3><p class="small">Collector evidence is not yet available.</p></section>';
 const sections=groups.map(group=>{
  // The authenticated workspace carries a small, exact aggregate of the
  // same stored per-currency entry-timing evidence. It is available even if
  // fetching thousands of detailed rows would exceed gateway limits.
  const authoritative=source.timedSummary?.rows?.[group.id];
  const rows=Array.isArray(authoritative)?authoritative:group.bots.flatMap(bot=>bot.experiment?.entry_timing||[]);
  const recorded=group.bots.filter(bot=>(bot.experiment?.entry_timing||[]).length);
  const counts=source.timedSummary?.coverage?.[group.id];
  const n=counts?counts.bots_with_rows:recorded.length;
  const total=counts?counts.bots_total:group.bots.length;
  const observations=rows.reduce((count,row)=>count+(Number(row.events)||0),0);
  const sourceNote='<p class="small">Verified resolved event observations: '+e(observationCount(observations))+' · '+e(String(n))+' of '+e(String(total))+' market bots have timing records.</p>';
  const key='favorites-collector-'+group.id;
  if(group.id==='sports'){
   const byBot=source.timedSummary?.sports_by_bot||{};
   return '<details class="favorite-collector-category" data-research="'+e(key)+'" '+(open.has(key)?'open':'')+'><summary>'+e(group.label)+'</summary>'+
      sourceNote+matrix(rows,group.label)+group.bots.map(bot=>matrix(Array.isArray(byBot[bot.id])?byBot[bot.id]:bot.experiment?.entry_timing||[],bot.name)).join('')+'</details>';
  }
  return '<details class="favorite-collector-category" data-research="'+e(key)+'" '+(open.has(key)?'open':'')+'><summary>'+e(group.label)+'</summary>'+sourceNote+matrix(rows,group.label)+'</details>';
 }).join('');
 return '<section class="favorite-collector-overview" aria-label="High-Probability Favorites price by time matrix"><h3>High-Probability Favorites · price × time matrix</h3>'+
 '<p class="small">Counts are verified resolved events per price/time cohort, not contracts. Ten contracts from one event count once. An event may appear in multiple cohorts; P/L is the average held-to-outcome return percentage, including entry fees.</p>'+
 (source.timedSummary?.rows?'<p class="small">Combined totals are calculated from the complete saved Favorites evidence, independently of individual card loading.</p>':source.error?'<p class="small" role="alert">Favorites research could not load: '+e(source.error)+'. Showing compact snapshot data only.</p>':!source.loaded?'<p class="small">Detailed Favorites research '+(source.loading?'is loading.':'has not loaded.')+' Combined tables may be incomplete.</p>':'')+
 sections+'</section>';
}

export const favoriteTableSettingsMarkup=mode=>`<div class="favorite-table-settings" role="group" aria-label="Favorites table settings"><strong>Table settings</strong> <button class="secondary" data-favorite-table="detailed" aria-pressed="${mode==='detailed'}">Detailed</button> <button class="secondary" data-favorite-table="wide" aria-pressed="${mode==='wide'}">Wider · 3 × 3</button> <button class="secondary" data-favorite-table="single" aria-pressed="${mode==='single'}">Single bucket</button><p class="small">${mode==='single'?'P/L = mean held-to-settlement return across distinct events. 90% uncertainty estimates the range for the average return, not the win rate. Correlated events can make this optimistic.':'Win margin = win rate − entry cost with fees. 90% uncertainty describes the win rate, not hold P/L. Related events can be correlated.'}</p></div>`;
export function favoriteSingleOverviewMarkup(bots=[],summary=null,open=new Set()){
 const groups=marketTypeGroups(bots);
 const sections=groups.map(group=>{
  const key='favorites-collector-'+group.id,stat=summary?.rows?.[group.id];
  const sports=group.id==='sports'?group.bots.map(bot=>
   '<div class="favorite-single-sport"><h4>'+e(bot.name)+'</h4>'+favoriteSingleCellMarkup(summary?.by_bot?.[bot.id])+'</div>').join(''):'';
  return '<details class="favorite-collector-category" data-research="'+e(key)+'" '+(open.has(key)?'open':'')+'><summary>'+e(group.label)+'</summary>'+favoriteSingleCellMarkup(stat)+sports+'</details>';
 }).join('');
 return '<section class="favorite-collector-overview favorite-single-overview"><h3>High-Probability Favorites · single bucket</h3><p class="small">All verified event-level held returns pooled across entry prices and times, including records that cannot be placed in the 3 × 3 table. Repeated events count once per table.</p>'+sections+'</section>';
}
export function favoriteWideOverviewMarkup(bots,summary,open=new Set()){
 const labels=new Map(marketTypeGroups(bots).map(g=>[g.id,g.label]));
 const categories=[...new Set([...labels.keys(),...Object.keys(summary?.rows||{})])];
 const prices=summary?.price_buckets||['70–<78¢','78–<86¢','86–95¢'];
 const sections=categories.map(category=>{
  const rows=summary?.rows?.[category]||[],coverage=summary?.coverage?.[category]||{};
  const times=coverage.time_buckets||[],key='favorites-wide-'+category;
  const body=prices.map(price=>'<tr><th scope="row">'+e(price)+'</th>'+times.map((time,slot)=>{
   const row=rows.find(r=>r.band===price&&Number(r.time_slot)===slot);
   if(!row||!(Number(row.events)>0))return '<td class="stat-empty">—</td>';
   const n=Number(row.events),wins=Number(row.event_wins),entry=Number(row.cost)/Number(row.contracts);
   const c=confidenceMarkup(wins,n,entry),ret=averageReturn(row);
   const margin=winConfidence90(wins,n,entry)?.margin;
   const signal=margin==null?'unknown':margin>0?'realized-positive':margin<0?'realized-negative':'neutral';
   return '<td class="stat-observed '+favoriteProfitClass(signal)+'"><details><summary><strong>n='+e(String(n))+'</strong><small>Wins '+e(eventAccuracy(wins,n))+'</small><small>Hold P/L '+e(ret)+'</small><small>Win margin '+e(c.margin)+'</small><small>Uncertainty '+e(c.error)+'</small></summary><p class="small">90% win-rate interval '+e(c.interval)+' · '+e(String(row.return_observations))+' hold-return observations.'+(row.estimated_return_observations>0?' '+e(String(row.estimated_return_observations))+' estimated from historical entry averages.':'')+'</p></details></td>';
  }).join('')+'</tr>').join('');
  const excluded=Number(coverage.excluded_legacy_observations)||0;
  const note=(coverage.time_basis==='observed_entry_window'?'Time thirds use the observed betting window. ':'Time thirds use the market duration. ')+(excluded?excluded+' legacy observations cross a time boundary and are excluded.':'');
  return '<details class="favorite-collector-category" data-research="'+e(key)+'" '+(open.has(key)?'open':'')+'><summary>'+e(labels.get(category)||category)+'</summary><p class="small">'+e(note)+'</p>'+(times.length?'<div class="table-scroll"><table class="favorite-stat-matrix favorite-wide-matrix"><thead><tr><th>Entry price</th>'+times.map(t=>'<th>'+e(t)+' left</th>').join('')+'</tr></thead><tbody>'+body+'</tbody></table></div>':'<p class="small">Waiting for exact entry times to establish the betting window.</p>')+'</details>';
 }).join('');
 return '<section class="favorite-collector-overview"><h3>High-Probability Favorites · wider 3 × 3</h3><p class="small">Distinct resolved events · hold-only return after fees · 90% confidence intervals. Wider bins pool different entry states.</p>'+sections+'</section>';
}

export function favoriteTimingMarkup(rows,wideRows=null,options={}){
 if(options.mode==='single')return '<details class="favorite-timing"><summary>All entries · single bucket</summary>'+favoriteSingleCellMarkup(options.single)+'</details>';
 if(wideRows!==null)return `<details class="favorite-timing"><summary>Wider entry price × time thirds</summary>${favoriteResearchGrid(wideRows,{mode:'wide'})}</details>`;
 if(!rows?.length)return '<p class="small">Time × percentage research starts with the next verified entry fill. Earlier trades are not assigned guessed timings.</p>';
 return `<details class="favorite-timing"><summary>Entry percentage × time remaining · combined sides</summary>${researchNote}${favoriteResearchGrid(favoriteCategoryRows(rows))}</details>`;
}

export function favoriteStatisticsMatrixMarkup(statistics,open=new Set()){
 const grids=statistics?.matrix||[],min=Number(statistics?.min_samples||20);
 if(!grids.length)return '<p class="small">Statistics matrix will populate when verified, settled Favorites observations are available. No missing outcome is treated as a loss or a win.</p>';
 const num=n=>n===null||n===undefined?'—':Number(n).toFixed(1)+'%';
 const status=cell=>cell.eligibility==='evidence_candidate'?'Evidence candidate':cell.eligibility==='fallback_candidate'?'Fallback candidate · sparse cell':cell.eligibility==='exploration_candidate'?'Exploration opportunity · sparse':cell.eligibility==='insufficient_samples'?'Under-sampled':'Evidence rejected';
 return '<section class="statistics-matrices" aria-label="Statistics-backed Favorites evidence"><h3>Statistics-Backed Favorites · entry price × time</h3><p class="small">Each table pools verified, settled outcomes from Data-Collection Favorites and the statistical paper portfolio (shared event IDs count once). Sparse cells can be explored with separately capped paper trades; exploration does not imply profitability. Five-cent price tiers; original time resolution. Sample count is distinct resolved events, not contracts. Legacy realized ROI may reflect exits, so hold P/L is unavailable here until verified hold-return attribution exists. Evidence candidates still require live maker fill, fees, slippage, and risk checks before an order. Unfilled maker bids are not assumed filled.</p>'+
 grids.map(grid=>{
   const byCell=new Map((grid.cells||[]).map(cell=>[cell.price_bucket+'|'+cell.horizon,cell]));
   const key='favorites-stat-'+grid.market_type;
   return '<details class="favorite-stat-market" data-research="'+e(key)+'" '+(open.has(key)?'open':'')+'><summary>'+e(grid.market_type)+'</summary><div class="table-scroll"><table class="favorite-stat-matrix"><thead><tr><th scope="col">Entry price</th>'+
   (grid.time_buckets||[]).map(time=>'<th scope="col">'+e(time)+'</th>').join('')+'</tr></thead><tbody>'+
   (grid.price_buckets||[]).map(price=>'<tr><th scope="row">'+e(price.replace('-', '–'))+'¢</th>'+
    (grid.time_buckets||[]).map(time=>{
      const cell=byCell.get(price+'|'+time);
      if(!cell||!cell.samples)return '<td class="stat-empty"><span class="small">No settled events</span></td>';
      const enough=cell.samples>=min,capable=['evidence_candidate','fallback_candidate'].includes(cell.eligibility);
      // Statistics ROI is legacy exit-altered data; do not infer hold margin.
      const signal='unknown';
      const label=status(cell);
      const fallback=cell.fallback_level!==cell.level&&cell.fallback_level!=='insufficient_samples'?
        'Fallback available: '+cell.fallback_level.replaceAll('_',' ')+' · n='+cell.fallback_samples:
        cell.fallback_level==='insufficient_samples'?'No reliable fallback':'Exact category/time evidence';
      const detail=['Exact-cell confidence lower bound: '+num(cell.lower===null?null:cell.lower*100),
        cell.fallback_lower===null||cell.fallback_lower===undefined?'':'Fallback confidence lower bound: '+num(cell.fallback_lower*100),
        'Hold P/L unavailable without verified attribution','Level: '+cell.level.replaceAll('_',' '),fallback,
        'Evidence is not a guarantee of maker execution; live fees and risk can still reject orders'].join(' · ');
      return '<td class="'+(enough?(capable?'stat-candidate':'stat-rejected'):'stat-sparse')+' '+favoriteProfitClass(signal)+'"><details><summary><strong>n='+e(String(cell.samples))+'</strong><span>Outcome wins '+e(num(cell.win_rate===null?null:cell.win_rate*100))+'</span><span>Hold P/L —</span><small>'+e(label)+'</small>'+'</summary><p class="small">'+e(detail)+'</p></details></td>';
    }).join('')+'</tr>').join('')+'</tbody></table></div></details>';
 }).join('')+'</section>';
}

export function learningDiagnosticsMarkup(learning){
 if(!learning)return '';
 const label={data_learning:'Data-learning strategy',operational_only:'Operational-only strategy',future_learning_candidate:'Future-learning candidate'}[learning.classification]||'Operational-only strategy';
 const state={using_statistics_now:'Using collected evidence now',collecting_only:'Collecting evidence; current rules remain fixed/configured',not_learning:'Not currently using historical learning',paused_history:'Paused history preserved; not currently learning'}[learning.state]||learning.state||'';
 const features=(learning.features||[]).map(x=>'<li>'+e(x)+'</li>').join('');
 const counts=[['Observations / attempts',learning.observations??0],['Settled / completed',learning.settled_observations??0],['Open / not yet usable',learning.open_observations??0],['Bots / profiles represented',learning.bot_count??0]];
 if(learning.research_cells!=null)counts.push(['Research cells',learning.research_cells]);
 if(learning.sample_threshold!=null)counts.push(['Preferred sample threshold',learning.sample_threshold]);
 const reasons=learning.decision_counts&&Object.keys(learning.decision_counts).length
  ?'<p class="small"><strong>Recent decision reasons:</strong> '+Object.entries(learning.decision_counts).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([k,v])=>e(k.replaceAll('_',' '))+' '+e(String(v))).join(' · ')+'</p>':'';
 return '<details class="advanced learning-diagnostics"><summary>Data / Learning · '+e(label)+'</summary>'+
   '<p class="small"><strong>'+e(state)+'</strong></p>'+
   '<div class="bot-stats">'+counts.map(([k,v])=>'<div><span>'+e(k)+'</span><strong>'+e(String(v))+'</strong></div>').join('')+'</div>'+
   '<p class="small"><strong>What the evidence improves:</strong> '+e(learning.decisions||'—')+'</p>'+
   '<p class="small"><strong>Segmentation:</strong> '+e(learning.segments||'—')+'</p>'+
   '<p class="small"><strong>Evidence threshold:</strong> '+e(learning.minimum||'—')+'</p>'+
   '<p class="small"><strong>Sparse-data fallback:</strong> '+e(learning.fallback||'—')+'</p>'+
   (features?'<p class="small"><strong>Recorded features:</strong></p><ul class="small">'+features+'</ul>':'')+
   (learning.last_refreshed_at?'<p class="small">Last aggregate refresh: '+e(new Date(Number(learning.last_refreshed_at)*1000).toLocaleString())+'</p>':'')+
   reasons+'</details>';
}

export const pnlClass=value=>value===null||value===undefined?'':Number(value)>0?'positive':Number(value)<0?'negative':'';
export function executionMarkup(x){
 if(!x||!x.measured)return '<p class="small">Execution measurements will appear with the next worker snapshot.</p>';
 const rate=x.maker_fill_rate==null?'—':Number(x.maker_fill_rate).toFixed(1)+'%';
 return `<details class="advanced"><summary>Execution quality · latest cycle${x.data_valid?'':' · data gap'}</summary><p class="small">${e(x.scope)}. Public queue position is estimated; simulated fills are not exchange executions. ${e(String(x.latency_ms))}ms modeled ${x.worker_delay_included?'transport latency plus measured worker processing delay':'action latency'}.</p><div class="bot-stats">${[['Maker quantity filled / requested',`${x.maker_filled} / ${x.maker_requested} · ${rate}`],['Rejected / submitted orders',`${x.rejections} / ${x.orders}`],['Partial / attempted IOC sweeps',`${x.partial_iocs} / ${x.ioc_attempts}`],['IOC unfilled quantity',x.ioc_unfilled],['Partial-profit contracts sold',x.profit_contracts],['Net cash recovered by partial profits',dollars(x.profit_net_proceeds)],['Fees · entire cycle',dollars(x.cycle_fees)],['Taker slippage · entire cycle',dollars(x.cycle_taker_slippage)]].map(([k,v])=>`<div><span>${e(k)}</span><strong>${e(String(v))}</strong></div>`).join('')}</div><p class="small">Fill rate uses requested contract quantity, including rejected entries. Working bids remain in the denominator. Unfilled IOC quantities can include retries of the same position. Recovery proceeds include exit fees; they are cash receipts, not profit. Partial-profit target: ${(Number(x.partial_profit_price)*100).toFixed(0)}¢ or better, retaining at least one contract.</p></details>`;
}
const metric=(label,value,note='')=>`<div><span>${e(label)}</span><strong>${e(dollars(value))}</strong>${note?`<small>${e(note)}</small>`:''}</div>`;
const finite=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
function eventLabel(a,key){
 const raw=a?.[key],value=raw==null?NaN:Number(raw);
 return Number.isSafeInteger(value)&&value>=0?`${value} ${value===1?'event':'events'}`:'';
}
const eventSuffix=(a,key)=>eventLabel(a,key)?` (${eventLabel(a,key)})`:'';
const exposureNote=(a,key,note)=>eventLabel(a,key)?`${eventLabel(a,key)} · ${note}`:note;
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
 return `<div class="money-grid bot-money">${metric('Unfilled buy bids',a.unfilled_bids,exposureNote(a,'unfilled_bid_events','Cash reserved, not spent'))}${metric('Active positions · cost',a.active_cost,exposureNote(a,'active_events',`Current value ${rangeText(valueBounds(a,positions,'active'))}`))}${metric('Awaiting settlement · cost',a.pending_cost,exposureNote(a,'pending_events',pendingLabel(a)))}${rangedMetric('Open position P/L',unreal,unreal?.unpriced?'Best estimate · last available quote or entry price':'Current and pending positions · after entry fees')}</div>`;
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
 <div class="money-grid">${metric('Available cash',a.available_cash,`Total cash ${dollars(a.cash)}`)}${metric('Unfilled buy bids',a.unfilled_bids,exposureNote(a,'unfilled_bid_events','Reserved from cash; includes estimated fees'))}${metric('Active positions · cost',a.active_cost,exposureNote(a,'active_events',`Current value ${rangeText(valueBounds(a,positions,'active'))}`))}${metric('Awaiting settlement · cost',a.pending_cost,exposureNote(a,'pending_events',pendingLabel(a)))}</div>
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
 return `<span class="exposure-header-value"><span class="folder-card-label">Bids</span><strong>${e(dollars(x.bids))}${e(eventSuffix(a,'unfilled_bid_events'))}</strong></span><span class="exposure-header-value"><span class="folder-card-label">Positions · cost</span><strong>${e(dollars(x.positions))}</strong><small>Open ${e(dollars(x.active))}${e(eventSuffix(a,'active_events'))} · pending ${e(dollars(x.pending))}${e(eventSuffix(a,'pending_events'))}</small></span>`;
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
function eventIdForGrouping(row){
 const id=row?.event_ticker;
 if(typeof id==='string'&&id)return id;
 const ticker=row?.ticker;
 if(typeof ticker!=='string'||!ticker)return null;
 const first=ticker.indexOf('-'),last=ticker.lastIndexOf('-');
 return first>=0&&last>first?ticker.slice(0,last):ticker;
}
function marketTypeEventCounts(bots,positions,orders,account){
 const matching=new Set(bots.map(b=>b.id));
 const belongs=row=>row.bot_id?matching.has(row.bot_id):
   bots.some(b=>typeof row.ticker==='string'&&row.ticker.startsWith(b.series+'-'));
 const keys={active:new Set(),pending:new Set(),bid:new Set()};
 for(const row of positions){
  if(!belongs(row)||!['active','pending'].includes(row.state))continue;
  const id=eventIdForGrouping(row);if(id)keys[row.state].add(id);
 }
 for(const row of orders){
  if(!belongs(row)||row.action!=='buy'||!['pending','resting'].includes(row.status))continue;
  const id=eventIdForGrouping(row);if(id)keys.bid.add(id);
 }
 // Do not label an incomplete/old detail list as zero events when it has exposure.
 const count=(kind,amount)=>keys[kind].size||amount===0?keys[kind].size:null;
 return {active_events:count('active',account.active_cost),pending_events:count('pending',account.pending_cost),
         unfilled_bid_events:count('bid',account.unfilled_bids)};
}
export function marketTypeSummaryMarkup(group,period='all',positions=[],shown=null,orders=[]){
 const v=marketTypeSummaryValues(group.bots,period,positions);
 const events=marketTypeEventCounts(group.bots,positions,orders,v.account);
 const running=group.bots.filter(b=>b.desired==='running').length;
 const coverage=v.missing?`${v.missing} ${v.missing===1?'bot':'bots'} missing P/L history`:v.partial?'Partial P/L history':v.period==='all'?'Current session':'Rolling '+folderPeriods[v.period];
 return `<span class="market-type-heading"><span class="market-type-name">${e(group.label)}</span><span class="badge">${running}/${group.bots.length} running${shown!==null?' · '+shown+' shown':''}</span><span class="market-type-disclosure" aria-hidden="true"></span></span><span class="folder-card-values market-type-values"><span class="summary-total-pnl"><span class="folder-card-label">Total P/L · ${e(folderPeriods[v.period])}</span><strong class="${rangeClass(v.pnl)} ${v.pnl?.unpriced?'value-range':''}">${e(rangeText(v.pnl))}</strong>${v.missing?'<small>'+e(coverage)+'</small>':''}</span>${exposureHeaderMarkup({...v.account,...events})}</span>`;
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
 return `<span class="folder-summary-heading"><span class="folder-name">${e(folder.name)}</span>${control}<span class="folder-disclosure" aria-hidden="true"></span></span><span class="folder-card-values"><span class="folder-estimated-balance"><span class="folder-card-label">Estimated portfolio value</span><strong class="${v.balanceUncertain?'value-range':''}">${e(v.balance)}</strong><small>${counts.running||0}/${counts.bots||0} running</small></span><span class="summary-total-pnl"><span class="folder-card-label">Total P/L · ${e(folderPeriods[v.period])}</span><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${v.period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong>${v.stale?'<small>Snapshot stale</small>':''}</span>${exposureHeaderMarkup(folder.accounting?.portfolio)}</span><span class="folder-summary-periods" role="group" aria-label="P/L period for ${e(folder.name)}">${folderPeriodButtons(v.period,folder.id)}</span>`;
}
export function folderOverviewMarkup(folders,period='all',now=Date.now()/1000){
 if(!Object.hasOwn(folderPeriods,period))period='all';
 const rows=folders.map(f=>{
  const v=folderSummaryValues(f,period,now),x=summaryExposure(f.accounting?.portfolio);
  const account=f.accounting?.portfolio;
  return `<tr><th scope="row"><a href="#folder-${e(f.id)}">${e(f.name)}</a></th><td class="folder-estimated-balance" data-label="Estimated portfolio value"><strong class="${v.balanceUncertain?'value-range':''}">${e(v.balance)}</strong></td><td class="summary-total-pnl" data-label="Total P/L · ${e(folderPeriods[period])}"><strong class="${v.pnl.className||''} ${v.pnl.uncertain?'value-range':''}">${period!=='all'&&v.pnl.available?'≈ ':''}${e(v.pnl.text)}</strong><small>${e(v.detail)}${v.stale?' · snapshot stale':''}</small>${v.realized?`<small>Realized ${e(v.realized)}</small>`:''}</td><td data-label="Open bids"><strong>${e(dollars(x.bids))}${e(eventSuffix(account,'unfilled_bid_events'))}</strong></td><td data-label="Open/pending positions"><strong>${e(dollars(x.positions))}</strong><small>Open ${e(dollars(x.active))}${e(eventSuffix(account,'active_events'))} · pending ${e(dollars(x.pending))}${e(eventSuffix(account,'pending_events'))}</small></td></tr>`;
 }).join('');
 return `<div class="overview-heading"><h2>At a glance</h2><div class="folder-summary-periods" role="group" aria-label="P/L period for all folders">${folderPeriodButtons(period)}</div></div><div class="folder-overview-wrap"><table class="folder-overview"><thead><tr><th>Strategy folder</th><th>Estimated portfolio value</th><th>Total P/L · ${e(folderPeriods[period])}</th><th>Open bids</th><th>Open/pending positions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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
 return `<span class="market-pnl-compact"><span>Total P/L</span><strong class="${total?rangeClass(total):all?fallback.className:''}">${e(text)}</strong></span>`;
}

export function botPnlDetailsMarkup(bot,period='all',positions=[]){
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

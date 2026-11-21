import assert from 'node:assert/strict';
import {favoriteProfitSignal,favoriteProfitLegendMarkup,favoriteCategoryResearchMarkup,favoriteCollectorOverviewMarkup,favoriteStatisticsMatrixMarkup} from '../apps/web/shadow-view.mjs';

assert.equal(favoriteProfitSignal({return_observations:1,return_sum:'-0.1'}),'realized-negative');
assert.equal(favoriteProfitSignal({return_observations:1,return_sum:'0.1'}),'realized-positive');
assert.equal(favoriteProfitSignal({return_observations:1,return_sum:0}),'neutral');
assert.equal(favoriteProfitSignal({return_observations:0,return_sum:'-5'}),'unknown');
assert.equal(favoriteProfitSignal({return_observations:undefined,return_sum:undefined}),'unknown');
assert.match(favoriteProfitLegendMarkup(),/Held profit/);
assert.doesNotMatch(favoriteProfitLegendMarkup(),/exit|fee drag/i);

const entry={series:'KXBTC15M',market_type:'crypto_15m',price:'.8',clock:'market_close',horizon:'10–15m',
 contracts:10,closed:10,resolved:10,winners:9,cost:8,net:-1,holding_seconds:600,
 events:1,event_win_rate:100,return_observations:1,return_sum:'.25'};
const group={id:'crypto_15m',label:'Crypto 15m',bots:[{id:'x',series:'KXBTC15M',experiment:{entry_timing:[entry]}}]};
const category=favoriteCategoryResearchMarkup(group);
assert.match(category,/profit-positive/);
assert.doesNotMatch(category,/Exit\/fee drag|profit-exit-drag|Above cost/);
assert.match(category,/Margin/);
assert.doesNotMatch(category,/Purchased<\/th>/);
const overview=favoriteCollectorOverviewMarkup(group.bots,new Set(),{timedSummary:{rows:{crypto_15m:[entry]}}});
assert.match(overview,/stat-observed profit-positive/);
assert.doesNotMatch(overview,/profit-exit-drag|Above cost/);
const unknown=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:[{...entry,return_sum:0,return_observations:0}]}}]});
assert.doesNotMatch(unknown,/profit-positive|profit-negative/);
const loss=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:[{...entry,return_sum:'-.15'}]}}]});
assert.match(loss,/profit-negative/);

const scalper=favoriteCategoryResearchMarkup({
 id:'crypto-15m',label:'Crypto 15m',research_kind:'round_trips',
 bots:[{id:'scalper',series:'KXBTC15M',experiment:{entry_timing:[{...entry,
  events:1,event_wins:1,contracts:10,closed:10,resolved:10,winners:10,net:1}]}}]});
assert.match(scalper,/Completed cycles/);
assert.match(scalper,/>1<\/td>/);

const stat=favoriteStatisticsMatrixMarkup({min_samples:20,matrix:[{market_type:'crypto_15m',
 price_buckets:['80-84'],time_buckets:['10–15m'],cells:[{price_bucket:'80-84',horizon:'10–15m',samples:25,
 win_rate:.91,realized_roi:-.07,realized_net:'-8',eligibility:'evidence_rejected',
 lower:.76,level:'exact',fallback_level:'exact',fallback_samples:25}]}]});
assert.doesNotMatch(stat,/profit-exit-drag|Exit\/fee drag/);

const unequal=[{...entry,return_events:{small:{cost:'1',net:'1'}}},
 {...entry,price:'.81',return_events:{large:{cost:'100',net:'-10'}}}];
const returns=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:unequal}}]});
assert.match(returns,/45\.00%/);
const sameEvent=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:[
 {...entry,return_events:{same:{cost:'1',net:'1'}}},
 {...entry,price:'.81',return_events:{same:{cost:'9',net:'-1'}}}]}}]});
assert.match(sameEvent,/0\.00%/);
console.log('Favorites hold-only profit signals passed');

import assert from 'node:assert/strict';
import {favoriteProfitSignal,favoriteProfitLegendMarkup,favoriteCategoryResearchMarkup,favoriteCollectorOverviewMarkup,favoriteStatisticsMatrixMarkup} from '../apps/web/shadow-view.mjs';

assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:9,cost:8,closed:10,net:-1}),'realized-positive');
assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:7,cost:8,closed:10,net:99}),'realized-negative');
assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:8,cost:8,closed:10,net:-99}),'neutral');
assert.equal(favoriteProfitSignal({purchased:10,settled:0,winners:0,cost:8,closed:3,net:-2}),'unknown');
assert.equal(favoriteProfitSignal({purchased:10,settled:0,winners:0,cost:8,closed:3,net:2}),'unknown');
const entry={series:'KXBTC15M',market_type:'crypto_15m',price:'0.8',clock:'market_close',horizon:'10–15m',contracts:10,closed:10,resolved:10,winners:9,profitable_closed:6,profit_classified_closed:10,cost:8,net:-1,holding_seconds:600,events:1,event_win_rate:100};
const group={id:'crypto_15m',label:'Crypto 15m',bots:[{id:'x',series:'KXBTC15M',experiment:{entry_timing:[entry]}}]};
const category=favoriteCategoryResearchMarkup(group);
assert.match(category,/n=1/);
assert.doesNotMatch(category,/Purchased<\/th>|Exit\/fee drag|profit-exit-drag/);
assert.match(favoriteProfitLegendMarkup(),/Positive win margin/);
assert.doesNotMatch(favoriteProfitLegendMarkup(),/exit|drag/i);
const overview=favoriteCollectorOverviewMarkup(group.bots,new Set(),{timedSummary:{rows:{crypto_15m:[entry]}}});
assert.match(overview,/class="stat-observed profit-positive"/);
assert.doesNotMatch(overview,/profit-exit-drag/);
const scalper=favoriteCategoryResearchMarkup({
 id:'crypto-15m',label:'Crypto 15m',research_kind:'round_trips',
 bots:[{id:'scalper',series:'KXBTC15M',experiment:{entry_timing:[{...entry,
  events:1,event_wins:1,contracts:10,closed:10,resolved:10,winners:10,net:1}]}}]});
assert.match(scalper,/Completed cycles/);
assert.match(scalper,/>1<\/td>/);
assert.doesNotMatch(scalper,/Completed contracts/);
const stat=favoriteStatisticsMatrixMarkup({min_samples:20,matrix:[{market_type:'crypto_15m',price_buckets:['80-84'],time_buckets:['10–15m'],cells:[{price_bucket:'80-84',horizon:'10–15m',samples:25,win_rate:.91,realized_roi:-.07,realized_net:'-8',eligibility:'evidence_rejected',lower:.76,level:'exact',fallback_level:'exact',fallback_samples:25}]}]});
assert.match(stat,/class="stat-rejected/);
assert.doesNotMatch(stat,/Colors:|profit-exit-drag|ROI -7.0%|Net P\/L:/);
assert.match(stat,/Hold P\/L/);
console.log('Favorites profit signal tests passed');
const unequal=[{...entry,return_events:{small:{cost:'1',net:'1'}}},
 {...entry,price:'.81',return_events:{large:{cost:'100',net:'-10'}}}];
const returns=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:unequal}}]});
assert.match(returns,/45\.00%/); // (100% - 10%) / 2, not pooled dollar ROI.
assert.doesNotMatch(returns,/\$9\.00/);
const sameEvent=favoriteCategoryResearchMarkup({...group,bots:[{...group.bots[0],experiment:{entry_timing:[
 {...entry,return_events:{same:{cost:'1',net:'1'}}},
 {...entry,price:'.81',return_events:{same:{cost:'9',net:'-1'}}} ]}}]});
assert.match(sameEvent,/0\.00%/); // One event across prices, after combined cost and net.
assert.match(favoriteCategoryResearchMarkup(group),/Hold P\/L/);

assert.match(returns,/stat-observed profit-positive/);

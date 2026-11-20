import assert from 'node:assert/strict';
import {favoriteProfitSignal,favoriteCategoryResearchMarkup,favoriteCollectorOverviewMarkup,favoriteStatisticsMatrixMarkup} from '../apps/web/shadow-view.mjs';

assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:9,cost:8,closed:10,net:-1}),'exit-drag');
assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:7,cost:8,closed:10,net:-1}),'realized-negative');
assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:9,cost:8,closed:10,net:1}),'realized-positive');
assert.equal(favoriteProfitSignal({purchased:10,settled:0,winners:0,cost:8,closed:0,net:0}),'unknown');
assert.equal(favoriteProfitSignal({purchased:10,settled:10,winners:9,cost:8,closed:10,net:0}),'neutral');
const entry={series:'KXBTC15M',market_type:'crypto_15m',price:'0.8',clock:'market_close',horizon:'10–15m',contracts:10,closed:10,resolved:10,winners:9,profitable_closed:6,profit_classified_closed:10,cost:8,net:-1,holding_seconds:600};
const group={id:'crypto_15m',label:'Crypto 15m',bots:[{id:'x',series:'KXBTC15M',experiment:{entry_timing:[entry]}}]};
assert.match(favoriteCategoryResearchMarkup(group),/Outcome rate above estimated break-even/);
assert.match(favoriteCategoryResearchMarkup(group),/background:rgba\(245,158,11/);
const overview=favoriteCollectorOverviewMarkup(group.bots,new Set(),{timedSummary:{rows:{crypto_15m:[entry]}}});
assert.match(overview,/possible exit\/loss drag/i);
const stat=favoriteStatisticsMatrixMarkup({min_samples:20,matrix:[{market_type:'crypto_15m',price_buckets:['80-84'],time_buckets:['10–15m'],cells:[{price_bucket:'80-84',horizon:'10–15m',samples:25,win_rate:.91,realized_roi:-.07,realized_net:'-8',eligibility:'evidence_rejected',lower:.76,level:'exact',fallback_level:'exact',fallback_samples:25}]}]});
assert.match(stat,/background:rgba\(245,158,11/);
console.log('Favorites profit signal tests passed');

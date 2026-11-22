import test from 'node:test';
import assert from 'node:assert/strict';
import {
  favoriteCollectorOverviewMarkup,
  favoriteWideOverviewMarkup,
  favoriteTimingMarkup,
} from '../apps/web/shadow-view.mjs';

const bot={id:'btc',name:'BTC',series:'KXBTC15M',
  experiment:{entry_timing:[]}};
function summaryRow(overrides={}){
  return {series:'combined',market_type:'15m_price',clock:'market_close',
    price:'.75',horizon:'5–10m',contracts:'50',cost:'37.50',
    events:'50',event_wins:'40',closed:'50',resolved:'50',winners:'40',
    net:'0',return_observations:50,return_sum:'3.333333',
    average_return_pct:'6.666666',estimated_return_observations:10,
    uncertainty_min_samples:50,roi_interval_status:'available',
    uncertainty90_pct:'12.17',ci90_low_pct:'-5.50',
    ci90_high_pct:'18.83',...overrides};
}
function detailMarkup(rows){
  return favoriteCollectorOverviewMarkup([bot],new Set(),{
    timedSummary:{rows:{'crypto-15m':rows},coverage:{
      'crypto-15m':{bots_total:1,bots_with_rows:1}}},
  });
}
function widerMarkup(rows){
  return favoriteWideOverviewMarkup([bot],{
    price_buckets:['70–<78¢'],coverage:{'crypto-15m':{
      time_buckets:['0m–5m','5m–10m','10m–15m']}},
    rows:{'crypto-15m':rows.map(r=>({
      ...r,band:'70–<78¢',time_slot:1}))},
  });
}

test('Detailed and Wider distinguish held profit interval from win-rate Wilson error',()=>{
  const row=summaryRow();
  for(const html of [detailMarkup([row]),widerMarkup([row]),
    favoriteTimingMarkup([row],[
      {...row,band:'70–<78¢',time_slot:1}],{mode:'wide'})]){
    assert.match(html,/P\/L 90% ±12\.17pp/);
    assert.match(html,/90% held P\/L interval -5\.50% to 18\.83%/);
    assert.match(html,/10 estimated/);
    assert.match(html,/Nominal exploratory interval/);
    assert.match(html,/win-rate error|Win-rate error/i);
    assert.doesNotMatch(html,/20 distinct dates|day-cluster/i);
  }
});

test('Under-50 cohorts suppress even stale numeric held ROI bounds',()=>{
  const row=summaryRow({return_observations:49,roi_interval_status:'available'});
  for(const html of [detailMarkup([row]),widerMarkup([row])]){
    assert.match(html,/90% held P\/L error pending 49\/50/);
    assert.doesNotMatch(html,/P\/L 90% ±12\.17pp/);
    assert.doesNotMatch(html,/held P\/L interval -5\.50%/);
  }
});

test('All-winner cohorts do not present zero-variance return uncertainty',()=>{
  const row=summaryRow({roi_interval_status:'insufficient_gain_loss_variation',
    uncertainty90_pct:null,ci90_low_pct:null,ci90_high_pct:null});
  for(const html of [detailMarkup([row]),widerMarkup([row])]){
    assert.match(html,/unavailable until both gains and losses are observed/);
    assert.doesNotMatch(html,/P\/L 90% ±/);
  }
});

test('Never invent a combined event-level interval from multiple pre-averaged rows',()=>{
  const one=summaryRow({market_type:'first',return_sum:'2',return_observations:50});
  const two=summaryRow({market_type:'second',return_sum:'2',return_observations:50});
  const html=detailMarkup([one,two]);
  assert.match(html,/return observations/);
  assert.doesNotMatch(html,/P\/L 90% ±12\.17pp/);
  assert.doesNotMatch(html,/90% held P\/L interval -5\.50%/);
});

test('Old API rows without held-return intervals remain readable without false claims',()=>{
  const old=summaryRow();
  delete old.roi_interval_status;
  delete old.uncertainty90_pct;
  delete old.ci90_low_pct;
  delete old.ci90_high_pct;
  for(const html of [detailMarkup([old]),widerMarkup([old])]){
    assert.match(html,/n=50/);
    assert.match(html,/Win margin|win margin/);
    assert.doesNotMatch(html,/P\/L 90% ±/);
    assert.doesNotMatch(html,/90% held P\/L interval/);
  }
});

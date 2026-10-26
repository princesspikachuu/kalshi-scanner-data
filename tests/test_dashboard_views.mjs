import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('docs/index.html','utf8');
let script=html.split('<script>')[1].split('</script>')[0];
script=script.slice(0,script.lastIndexOf('document.querySelectorAll(".tab")'));
script+='globalThis.dashboard={state,render,lookup,validCollection,collectionDate,renderLossControls,applySavedView,showDetail,csv};})();';
const elements=new Map();
function element(id){
 if(!elements.has(id))elements.set(id,{value:({collectAsset:'crypto',collectMarkets:'300',collectDays:'7',collectOffset:'1'})[id]||'',classList:{toggle(){},remove(){},add(){}},appendChild(){},setAttribute(){},addEventListener(){}});
 return elements.get(id);
}
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>element(Symbol())},localStorage:{setItem(){}},console,URL});
vm.runInContext(script,context);
const {state,render,lookup,validCollection,collectionDate}=context.dashboard;
for(const offset of [31,90,180,365,3644])assert.equal(validCollection({asset:'crypto',markets:300,days:7,offset}),true);
assert.equal(validCollection({asset:'crypto',markets:300,days:7,offset:3650}),false);
assert.equal(validCollection({asset:'crypto',markets:300,days:1,offset:3650}),true);
assert.equal(validCollection({asset:'crypto',markets:300,days:1,offset:0}),false);
assert.match(collectionDate(90),/^\d{4}-\d{2}-\d{2}$/);
const cumulative=JSON.parse(fs.readFileSync('docs/status-crypto.json'));
const latest=JSON.parse(fs.readFileSync('docs/latest-meta.json')).crypto;
Object.assign(state,{asset:'crypto',minimum:1,records:[{asset:'crypto',minutes_before_close:15,price_band_cents:'50-60',sampled_markets:40,average_profit_loss_cents_per_contract:2}],latestRecords:[{asset:'crypto',minutes_before_close:15,price_band_cents:'50-60',sampled_markets:20,average_profit_loss_cents_per_contract:1}],meta:{crypto:cumulative},latestMeta:{crypto:latest}});
state.view='historical';render();
assert.equal(element('marketCount').textContent,cumulative.markets_sampled_total.toLocaleString());
assert.equal(element('coverage').textContent,cumulative.first_date+' → '+cumulative.last_date);
assert.equal(lookup('crypto',15,'50-60').sampled_markets,40);
state.view='latest';render();
assert.equal(element('marketCount').textContent,latest.markets_sampled_total.toLocaleString());
assert.equal(element('coverage').textContent,latest.first_date+' → '+latest.last_date);
assert.equal(lookup('crypto',15,'50-60').sampled_markets,20);

// Loading a study must never replace the original sample or the Off values.
const {applySavedView,showDetail,csv}=context.dashboard;
const original={asset:'crypto',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:100,sampled_days:10,average_purchase_price_cents:95,average_profit_loss_cents_per_contract:-10,hypothetical_roi_percent:-10.5263,wins:85,win_rate_percent:85};
state.records.push(original);
const study={records:[{asset:'crypto',family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:20,sampled_days:2,sampled_dates:['2026-10-06','2026-10-07'],average_purchase_price_cents:95,hold_net_cents:-51,average_profit_loss_cents_per_contract:-16,improvement_cents:35,wins:8,hold_wins:9,early_exits:8,missed_recoveries:1,supported_thresholds:[80]}],rules:[{family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',supported:true,threshold_cents:80,reason:'Validated'}],saved_observations:100,path_observations:70,comparison_observations:20,markets_sampled_total:20,days_sampled:2,first_date:'2026-10-06',last_date:'2026-10-07'};
state.lossStudy={entry_fee_cents:1,exit_fee_cents:2,historical:{crypto:study},latest:{crypto:{records:[],rules:[],saved_observations:5,path_observations:0}}};
state.view='historical';state.lossEnabled=false;render();
let cell=lookup('crypto',15,'90-100');
assert.equal(cell,original);
assert.equal(cell.average_profit_loss_cents_per_contract,-10);
assert.equal(cell.sampled_markets,100);
assert.equal(element('marketCount').textContent,cumulative.markets_sampled_total.toLocaleString());
assert.equal(element('coverage').textContent,cumulative.first_date+' → '+cumulative.last_date);
state.lossEnabled=true;render();
cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-3); // -10 + 20*35/100
assert.equal(cell.sampled_markets,100);
assert.equal(cell.sampled_days,10);
assert.equal(cell.exit_coverage,20);
assert.equal(cell.improvement_cents,7);
assert.equal(cell.early_exits,8);
assert.equal(cell.win_rate_percent,84); // original 85 wins, one foregone recovery
assert.equal(cell.matched_hold_cents,-50); // entry stress cancels in paired delta
assert.equal(cell.matched_exit_cents,-15);
assert.equal(element('marketCount').textContent,cumulative.markets_sampled_total.toLocaleString());
assert.deepEqual(Array.from(cell.thresholds),[80]);
showDetail(cell,15,'90-100');
assert.match(element('detail').innerHTML,/Full-sample hold P\/L/);
assert.match(element('detail').innerHTML,/20 of 100/);
assert.match(element('detail').innerHTML,/absolute sale bid, not a price drop/);
assert.match(element('detail').innerHTML,/\+7.00¢/);
// Differences from multiple families are weighted over the full cell, not
// substituted with the smaller validation subset's average.
study.records.push({...study.records[0],family:'station',sampled_markets:10,hold_net_cents:-7,average_profit_loss_cents_per_contract:-5,early_exits:1,missed_recoveries:0,supported_thresholds:[75]});
cell=lookup('crypto',15,'90-100');
assert.ok(Math.abs(cell.average_profit_loss_cents_per_contract-(-2.8))<1e-10);
assert.equal(cell.hold_net_cents,-10);
assert.equal(cell.exit_coverage,30);
assert.equal(cell.sampled_markets,100);
assert.ok(Math.abs(cell.hypothetical_roi_percent-(-2.8/95*100))<1e-10);
// Preserve an adverse measured change too; never inflate results to look better.
study.records.pop();
study.records[0].average_profit_loss_cents_per_contract=-56;
cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-11);
assert.equal(cell.improvement_cents,-1);
// Stale/mismatched studies cannot apply a larger subset to a smaller cell.
study.records[0].sampled_markets=200;
cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-10);
assert.equal(cell.hypothetical_roi_percent,original.hypothetical_roi_percent);
assert.equal(cell.stale_study,true);
state.view='latest';render();
cell=lookup('crypto',15,'50-60');
assert.equal(cell.sampled_markets,20);
assert.equal(cell.average_profit_loss_cents_per_contract,1);
assert.equal(cell.exit_coverage,0);
state.lossEnabled=false;render();
assert.equal(lookup('crypto',15,'50-60').sampled_markets,20);
applySavedView({lossEnabled:true});assert.equal(state.lossEnabled,true);
assert.doesNotMatch(html,/id="lossComparison"|id="lossTime"/);

// Regression against every published cell, including the sports cell whose
// 584 observations previously shrank to a 29-observation validation subset.
state.records=csv(fs.readFileSync('backtests/AVERAGES_BY_TIME_AND_PRICE.csv','utf8'));
state.latestRecords=csv(fs.readFileSync('backtests/LATEST_BY_CATEGORY.csv','utf8'));
state.lossStudy=JSON.parse(fs.readFileSync('backtests/LOSS_PREVENTION.json','utf8'));
for(const view of ['historical','latest']){
 state.view=view;
 for(const baseline of view==='latest'?state.latestRecords:state.records){
  state.asset=baseline.asset;
  state.lossEnabled=false;
  assert.equal(lookup(state.asset,Number(baseline.minutes_before_close),baseline.price_band_cents),baseline);
  state.lossEnabled=true;
  const adjusted=lookup(state.asset,Number(baseline.minutes_before_close),baseline.price_band_cents);
  assert.equal(adjusted.sampled_markets,Number(baseline.sampled_markets));
  assert.equal(adjusted.sampled_days,baseline.sampled_days);
  assert.equal(adjusted.hold_net_cents,Number(baseline.average_profit_loss_cents_per_contract));
  if(adjusted.early_exits===0){
   assert.equal(adjusted.average_profit_loss_cents_per_contract,Number(baseline.average_profit_loss_cents_per_contract));
   assert.equal(adjusted.hypothetical_roi_percent,Number(baseline.hypothetical_roi_percent));
  }
 }
}
state.asset='sports';state.view='historical';state.lossEnabled=true;
const repaired=lookup('sports',120,'80-90');
console.log('Published sports regression:',JSON.stringify({n:repaired?.sampled_markets,hold:repaired?.hold_net_cents,selected:repaired?.average_profit_loss_cents_per_contract,exitCoverage:repaired?.exit_coverage}));

const workerCode=fs.readFileSync('worker/src/index.js','utf8');
const worker=(await import('data:text/javascript;base64,'+Buffer.from(workerCode).toString('base64'))).default;
const originalFetch=globalThis.fetch;
try{
 let target;
 globalThis.fetch=async url=>{target=url;return new Response(JSON.stringify(cumulative))};
 const response=await worker.fetch(new Request('https://example.test/api/status/crypto'),{});
 assert.match(target,/\/docs\/status-crypto\.json\?/);
 assert.equal((await response.json()).markets_sampled_total,cumulative.markets_sampled_total);
 const lossResponse=await worker.fetch(new Request('https://example.test/api/loss-prevention'),{});
 assert.equal(lossResponse.status,200);assert.match(target,/backtests\/LOSS_PREVENTION\.json/);
 // Verify older requests reach dispatch with their original offset.
 const env={GITHUB_ACTIONS_TOKEN:'test-token',COLLECTION_RATE_LIMIT:{limit:async()=>({success:true})}};
 let dispatched;
 globalThis.fetch=async (url,options)=>{
  if(options.method==='POST'){
   dispatched=JSON.parse(options.body);
   return new Response(null,{status:204});
  }
  return new Response(JSON.stringify({workflow_runs:[]}));
 };
 function request(offset,days=7){return new Request('https://example.test/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset:'crypto',max_markets:300,days_ago:offset,days_to_collect:days})})}
 assert.equal((await worker.fetch(request(180),env)).status,202);
 assert.equal(dispatched.inputs.days_ago,'180');
 assert.equal((await worker.fetch(request(3650,1),env)).status,202);
 assert.equal((await worker.fetch(request(3650,7),env)).status,400);
 assert.equal((await worker.fetch(request(0),env)).status,400);
}finally{globalThis.fetch=originalFetch}
console.log('Latest and historical grids, counts, dates, and Worker routing verified.');

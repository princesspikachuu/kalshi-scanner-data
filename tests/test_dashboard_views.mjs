import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('docs/index.html','utf8');
let script=html.split('<script>')[1].split('</script>')[0];
script=script.slice(0,script.lastIndexOf('document.querySelectorAll(".tab")'));
script+='globalThis.dashboard={state,render,lookup,validCollection,collectionDate,renderLossControls,applySavedView,showDetail,csv,loadLossStudy,thresholdEstimate};})();';
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

// A single visible threshold replaces the old time controls and tap prompts.
const {applySavedView,showDetail,csv,thresholdEstimate}=context.dashboard;
const original={asset:'crypto',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:100,sampled_days:10,average_purchase_price_cents:95,average_profit_loss_cents_per_contract:-10,hypothetical_roi_percent:-10.5263,wins:85,win_rate_percent:85};
state.records.push(original);
const bins=[{bid_low_cents:50,bid_high_cents:60,mean_bid_cents:55,events:10,losses:8},{bid_low_cents:60,bid_high_cents:70,mean_bid_cents:65,events:10,losses:2}];
const riskRecord={asset:'crypto',family:'KXBTC15M',minutes_before_close:15,price_band_cents:'90-100',decision_minutes_remaining:5,observed_events:20,bins};
state.lossStudy={version:2,historical:{crypto:{records:[riskRecord]}}};
state.view='historical';state.lossEnabled=false;render();
assert.equal(lookup('crypto',15,'90-100'),original);
state.lossEnabled=true;render();
let cell=lookup('crypto',15,'90-100');
assert.equal(cell.threshold_cents,60);
assert.equal(cell.average_profit_loss_cents_per_contract,-10);
assert.equal(cell.sampled_markets,100);
assert.equal(element('marketHeading').textContent,'Loss-prevention thresholds');
assert.equal(element('metricControls').hidden,true);
assert.equal(element('valueLegend').hidden,true);
assert.doesNotMatch(html,/id="lossDecision"|Mixed risk pattern · tap|Tap for risk coverage|Series risk ranges · tap/);
assert.match(html,/threshold==null\?"—":"≈"\+threshold\+"¢"/);
// Old saved time-picker preferences cannot override the automatic checkpoint.
state.lossDecision='30';render();
assert.equal(lookup('crypto',15,'90-100').threshold_cents,60);
assert.equal(thresholdEstimate([],95),null);
assert.equal(thresholdEstimate([riskRecord],50),null); // never manufacture an above-entry stop
assert.equal(thresholdEstimate([{bins:[{...bins[0],bid_low_cents:30},bins[1]]}],95),null); // do not bridge missing bands
assert.equal(thresholdEstimate([{bins:bins.map(b=>({...b,losses:0}))}],95),null);
// Small reversals are pooled using event weights, not chosen based on outcomes
// of entire future paths. A flat 50% fit has no established >50% crossing.
assert.equal(thresholdEstimate([{bins:[{...bins[0],losses:2},{...bins[1],losses:8}]}],95),null);
state.view='latest';render();
cell=lookup('crypto',15,'50-60');
assert.equal(cell.sampled_markets,20);
assert.equal(cell.average_profit_loss_cents_per_contract,1);
assert.equal(cell.threshold_cents,null);
assert.equal(element('marketCount').textContent,latest.markets_sampled_total.toLocaleString());
applySavedView({lossEnabled:true});assert.equal(state.lossEnabled,true);

state.records=csv(fs.readFileSync('backtests/AVERAGES_BY_TIME_AND_PRICE.csv','utf8'));
state.latestRecords=csv(fs.readFileSync('backtests/LATEST_BY_CATEGORY.csv','utf8'));
state.lossStudy=JSON.parse(fs.readFileSync('backtests/LOSS_PREVENTION.json','utf8'));
// Older committed reports are ignored until a new study is built by CI.
for(const view of ['historical','latest']){
 state.view=view;
 for(const baseline of view==='latest'?state.latestRecords:state.records){
  state.asset=baseline.asset;state.lossEnabled=false;
  assert.equal(lookup(state.asset,Number(baseline.minutes_before_close),baseline.price_band_cents),baseline);
  state.lossEnabled=true;
  const annotated=lookup(state.asset,Number(baseline.minutes_before_close),baseline.price_band_cents);
  for(const field of ['sampled_markets','sampled_days','average_profit_loss_cents_per_contract','hypothetical_roi_percent','win_rate_percent']){
   assert.equal(annotated[field],baseline[field]);
  }
 }
}
// A legacy remote schema must fall back to the newly built same-origin asset.
let lossRequests=[];
context.fetch=async url=>{lossRequests.push(url);return new Response(JSON.stringify(lossRequests.length===1?{version:1}: {version:2,historical:{}}))};
await context.dashboard.loadLossStudy();
assert.equal(lossRequests.length,2);
assert.match(lossRequests[1],/^\.\/loss-prevention.json/);
assert.equal(state.lossStudy.version,2);
console.log('Conditional risk, checkpoint choice and unchanged historical/latest returns verified.');

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

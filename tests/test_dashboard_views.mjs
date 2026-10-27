import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('docs/index.html','utf8');
let script=html.split('<script>')[1].split('</script>')[0];
script=script.slice(0,script.lastIndexOf('document.querySelectorAll(".tab")'));
script+='globalThis.dashboard={state,render,lookup,validCollection,collectionDate,renderLossControls,applySavedView,showDetail,csv,loadLossStudy,lossLabel};})();';
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

// Loss prevention retains the regular return table and adds the sell label.
const {applySavedView,showDetail,csv,lossLabel}=context.dashboard;
const original={asset:'crypto',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:100,sampled_days:10,average_purchase_price_cents:95,average_profit_loss_cents_per_contract:-10,hypothetical_roi_percent:-10.5263,wins:85,win_rate_percent:85};
state.records.push(original);
const policy={minutes_before_close:15,price_band_cents:'90-100',threshold_cents:60,covered_observations:20,early_exits:8,missed_recoveries:1,total_delta_cents:700,base_n:100,base_wins:85,base_price_cents:95};
state.lossStudy={version:2,roi_policy_version:1,historical:{crypto:{policy_cells:[policy]}},latest:{crypto:{policy_cells:[policy],latest_membership_known:false,run_id:latest.run_id}}};
state.view='historical';state.lossEnabled=false;render();
assert.equal(lookup('crypto',15,'90-100'),original);
state.lossEnabled=true;render();
let cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-3);
assert.ok(Math.abs(cell.hypothetical_roi_percent-(-3/95*100))<1e-10);
assert.equal(cell.sampled_markets,100);
assert.equal(cell.sampled_days,10);
assert.equal(cell.win_rate_percent,84);
assert.equal(lossLabel(cell),'Sell ≤ 60¢');
assert.equal(element('marketHeading').textContent,'Average profit & loss');
assert.equal(element('metricControls').hidden,false);
assert.equal(element('valueLegend').hidden,false);
assert.doesNotMatch(html,/id="lossDecision"|Mixed risk pattern · tap|Tap for risk coverage|Series risk ranges · tap/);
original.win_rate_percent=40;original.wins=40;
assert.equal(lossLabel(lookup('crypto',15,'90-100')),'Trade not recommended');
original.win_rate_percent=50;original.wins=50;
assert.equal(lossLabel(lookup('crypto',15,'90-100')),'Sell ≤ 60¢');
original.win_rate_percent=85;original.wins=85;
policy.total_delta_cents=-100;
assert.equal(lookup('crypto',15,'90-100').average_profit_loss_cents_per_contract,-11);
policy.covered_observations=200;
assert.equal(lookup('crypto',15,'90-100').average_profit_loss_cents_per_contract,-10);
policy.covered_observations=20;
state.view='latest';render();
cell=lookup('crypto',15,'50-60');
assert.equal(cell.sampled_markets,20);
assert.equal(cell.average_profit_loss_cents_per_contract,1);
assert.equal(element('marketCount').textContent,latest.markets_sampled_total.toLocaleString());
// Latest exit deltas require this run's membership, not the historical scope.
state.latestRecords.push({...original,sampled_markets:50,wins:42,win_rate_percent:84,average_profit_loss_cents_per_contract:-5});
state.lossStudy.latest.crypto.policy_cells=[{...policy,base_n:50,base_wins:42}];
assert.equal(lookup('crypto',15,'90-100').average_profit_loss_cents_per_contract,-5);
state.lossStudy.latest.crypto.latest_membership_known=true;
assert.equal(lookup('crypto',15,'90-100').average_profit_loss_cents_per_contract,-7);
state.lossStudy.latest.crypto.run_id='different-run';
assert.equal(lookup('crypto',15,'90-100').average_profit_loss_cents_per_contract,-5);

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
  assert.equal(annotated.sampled_markets,baseline.sampled_markets);
  assert.equal(annotated.sampled_days,baseline.sampled_days);
  assert.equal(annotated.hold_net_cents,Number(baseline.average_profit_loss_cents_per_contract));
  if(annotated.early_exits===0){
   assert.equal(annotated.average_profit_loss_cents_per_contract,Number(baseline.average_profit_loss_cents_per_contract));
   assert.equal(annotated.hypothetical_roi_percent,Number(baseline.hypothetical_roi_percent));
  }
  assert.equal(annotated.trade_not_recommended,Number(baseline.win_rate_percent)<50);
 }
}
// A legacy remote schema must fall back to the newly built same-origin asset.
let lossRequests=[];
context.fetch=async url=>{lossRequests.push(url);return new Response(JSON.stringify(lossRequests.length===1?{version:1}: {version:2,roi_policy_version:1,historical:{}}))};
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

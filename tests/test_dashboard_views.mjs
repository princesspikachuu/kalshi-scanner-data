import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('docs/index.html','utf8');
let script=html.split('<script>')[1].split('</script>')[0];
script=script.slice(0,script.lastIndexOf('document.querySelectorAll(".tab")'));
script+='globalThis.dashboard={state,render,lookup,validCollection,collectionDate,renderLossControls,applySavedView,showDetail};})();';
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

// The main heatmap switches between matched hold and supported exits.
const {applySavedView,showDetail}=context.dashboard;
const study={records:[{asset:'crypto',family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:20,sampled_days:2,sampled_dates:['2026-10-06','2026-10-07'],average_purchase_price_cents:95,hold_net_cents:-50,average_profit_loss_cents_per_contract:-15,improvement_cents:35,wins:10,hold_wins:9,early_exits:8,missed_recoveries:1,supported_thresholds:[80]}],rules:[{family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',supported:true,threshold_cents:80,reason:'Validated'}],saved_observations:100,path_observations:70,comparison_observations:20,markets_sampled_total:20,days_sampled:2,first_date:'2026-10-06',last_date:'2026-10-07'};
state.lossStudy={entry_fee_cents:1,exit_fee_cents:2,historical:{crypto:study},latest:{crypto:{records:[],rules:[],saved_observations:5,path_observations:0}}};
state.view='historical';state.lossEnabled=false;render();
let cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-50);
assert.equal(cell.sampled_markets,20);
assert.equal(cell.early_exits,0);
assert.equal(cell.win_rate_percent,45);
assert.equal(element('marketCount').textContent,'20');
assert.equal(element('marketHeading').textContent,'Average net profit & loss');
state.lossEnabled=true;render();
cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-15);
assert.equal(cell.sampled_markets,20);
assert.equal(cell.improvement_cents,35);
assert.equal(cell.early_exits,8);
assert.equal(cell.win_rate_percent,50);
assert.deepEqual(Array.from(cell.thresholds),[80]);
showDetail(cell,15,'90-100');
assert.match(element('detail').innerHTML,/Sell at \/ below 80¢/);
assert.match(element('detail').innerHTML,/Hold net P\/L/);
assert.match(element('detail').innerHTML,/8 early exits/);
assert.match(element('detail').innerHTML,/1 missed recoveries/);
assert.match(element('detail').innerHTML,/\+35.00¢/);
// Different families must be sample-weighted, not averaged equally.
study.records.push({...study.records[0],family:'station',sampled_markets:10,sampled_days:1,sampled_dates:['2026-10-08'],average_purchase_price_cents:96,hold_net_cents:10,average_profit_loss_cents_per_contract:12,early_exits:2,missed_recoveries:0,wins:9,hold_wins:8,supported_thresholds:[75]});
cell=lookup('crypto',15,'90-100');
assert.equal(cell.average_profit_loss_cents_per_contract,-6);
assert.equal(cell.hold_net_cents,-30);
assert.equal(cell.improvement_cents,24);
assert.equal(cell.sampled_days,3);
assert.deepEqual(Array.from(cell.thresholds),[75,80]);
assert.ok(Math.abs(cell.hypothetical_roi_percent-(-180/2890*100))<1e-10);
state.view='latest';render();
assert.equal(lookup('crypto',15,'50-60'),undefined);
assert.match(element('matrix').innerHTML,/Loss-prevention results need usable price paths/);
state.lossEnabled=false;render();
assert.equal(lookup('crypto',15,'50-60').sampled_markets,20);
applySavedView({lossEnabled:true});assert.equal(state.lossEnabled,true);
assert.doesNotMatch(html,/id="lossComparison"|id="lossTime"/);

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

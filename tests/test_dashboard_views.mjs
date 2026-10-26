import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync('docs/index.html','utf8');
let script=html.split('<script>')[1].split('</script>')[0];
script=script.slice(0,script.lastIndexOf('document.querySelectorAll(".tab")'));
script+='globalThis.dashboard={state,render,lookup,validCollection,collectionDate,renderLossComparison,applySavedView};})();';
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

// The on/off comparison must use the exact same sample and costs.
const {renderLossComparison,applySavedView}=context.dashboard;
const study={records:[{asset:'crypto',family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',sampled_markets:20,sampled_days:2,hold_net_cents:-50,average_profit_loss_cents_per_contract:-15,improvement_cents:35,early_exits:8,missed_recoveries:1}],rules:[{family:'crypto15m',minutes_before_close:15,price_band_cents:'90-100',supported:true,threshold_cents:80,reason:'Validated'}],saved_observations:100,path_observations:70,comparison_observations:20};
state.lossStudy={historical:{crypto:study},latest:{crypto:{records:[],rules:[],saved_observations:5,path_observations:0}}};
state.view='historical';state.lossMinute=15;state.lossEnabled=false;renderLossComparison();
assert.match(element('lossComparison').innerHTML,/Sell at \/ below 80¢/);
assert.match(element('lossComparison').innerHTML,/-50.00¢<\/td><td>-50.00¢/);
assert.match(element('lossComparison').innerHTML,/0 early exits/);
state.lossEnabled=true;renderLossComparison();
assert.match(element('lossComparison').innerHTML,/-50.00¢<\/td><td>-15.00¢/);
assert.match(element('lossComparison').innerHTML,/8 early exits/);
assert.match(element('lossComparison').innerHTML,/1 missed recoveries/);
state.view='latest';renderLossComparison();
assert.match(element('lossComparison').textContent,/No usable price paths/);
applySavedView({lossEnabled:false,lossMinute:5});
assert.equal(state.lossEnabled,false);assert.equal(state.lossMinute,5);

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

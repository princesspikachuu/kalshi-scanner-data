import test from 'node:test';import assert from 'node:assert/strict';import {proxyAuth} from '../apps/gateway/index.mjs';import {selectedSquares} from '../apps/web/bot-builder.mjs';
const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)};
const options=()=>({fetcher:async(url,opts)=>{assert.equal(opts.headers.get('x-pocket-proxy'),env.API_PROXY_SECRET);return new Response(JSON.stringify({contract:'demo-v1',environment:'demo',bots:[],items:[]}),{headers:{'content-type':'application/json'}})}});
test('Demo routes preserve owner gateway and correct method',async()=>{
 for(const path of ['performance?bot=00000000-0000-0000-0000-000000000001','workspace','orders','activity?kind=fill','chart?period=7D','research?asset=btc&start=2026-10-01&end=2026-10-30']){
  const r=await proxyAuth(new Request('https://app.test/api/demo/'+path),env,options());assert.equal(r.status,200,path);
 }
 let called=false;const r=await proxyAuth(new Request('https://app.test/api/demo/bots',{method:'POST',headers:{origin:'https://other.test','content-type':'application/json'},body:'{}'}),env,{fetcher:async()=>{called=true}});assert.equal(r.status,403);assert.equal(called,false);
});
test('Demo rejects credentials query and unexpected response contract',async()=>{
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/workspace?private_key=abc'),env,options())).status,422);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/workspace'),env,{fetcher:async()=>new Response(JSON.stringify({contract:'paper-v1'}),{headers:{'content-type':'application/json'}})})).status,502);
});
test('Selected chart squares form conditions of one bot',()=>{
 const report={id:'123',asset:'btc',entry_minutes:[15,10,5,3,1]};const squares=selectedSquares([{report,cell:{},minutes:5,band:'60-70'},{report,cell:{},minutes:3,band:'80-90'}]);
 assert.equal(squares.length,2);assert.equal(squares[0].max_price,69);assert.equal(squares[0].min_minutes,3);assert.equal(squares[0].report_id,123);
});

import {attentionInfo,attentionMarkup,exitEvidence} from '../apps/web/demo-client.mjs';
test('attention names the failure, recovery action, affected market and order without a generic badge-only state',()=>{
 const h={state:'attention',at:1000,reconciled_at:990,issue:{summary:'Saved order not returned',action:'Review Activity or retry verification',control:'retry',phase:'reconciliation',market:'KXBTC15M-TEST',order_id:'order-one',code:'not_found',http_status:404}};
 const info=attentionInfo({key:'bot'},h,[],1001),html=attentionMarkup(info,{botId:'bot'});
 for(const text of ['Saved order not returned','Review Activity','Retry verification','Order reconciliation','KXBTC15M-TEST','order-one','not_found','HTTP 404','Last successful check'])assert.ok(html.includes(text),text);
 assert.ok(html.includes('ticker=KXBTC15M-TEST'));assert.ok(html.includes('bot=bot'));
});
test('attention explains stale worker and missing connection separately',()=>{
 assert.equal(attentionInfo({key:'b'},{state:'connection_required'},[],1000).control,'connection');
 const stale=attentionInfo({key:'b'},{state:'waiting',at:1,issue:{summary:'old error'}},[],1000);
 assert.match(stale.reason,/stopped checking in/);assert.notEqual(stale.reason,'old error');
});
test('ownership attention is scoped to the affected bot and all inserted evidence is escaped',()=>{
 const h={state:'ready',at:1000,blocked_markets:['market-one']},orders=[{bot:'a',ticker:'market-one'}];
 assert.deepEqual(attentionInfo({key:'a'},h,orders,1000).markets,['market-one']);
 assert.deepEqual(attentionInfo({key:'b'},h,orders,1000).markets,[]);
 const html=attentionMarkup({reason:'<script>x</script>',action:'<img src=x>',phase:'" onclick="x',markets:['<bad>'],orderId:'<order>',code:'<code>',control:'<evil>'},{botId:'b'});
 assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('data-attention-action="<evil>'));
});
test('exit evidence distinguishes the threshold from the actual side bid and ask',()=>{
 assert.deepEqual(exitEvidence({kind:'exit_trigger',details:{threshold:55,side:'no',quote:{bid:1,ask:99}}}),['Exit trigger: BID (previous rule) at or below 55¢','Observed NO bid 1¢ / ask 99¢']);
 assert.deepEqual(exitEvidence({kind:'exit_trigger',details:{threshold:60,reference:'ask',side:'yes',quote:{bid:59,ask:65}}}),['Exit trigger: ASK at or below 60¢','Observed YES bid 59¢ / ask 65¢']);
 assert.deepEqual(exitEvidence({kind:'fill',details:{price:2}}),[]);
});
test('exit evidence exposes sequenced book source and preceding ask',()=>{
 assert.deepEqual(exitEvidence({kind:'exit_trigger',details:{reference:'ask',threshold:55,side:'yes',previous_ask:56,observation_gap_seconds:0.1,quote:{bid:50,ask:54,source:'orderbook',seq:17,clock:300}}}),['Exit trigger: ASK at or below 55¢','Observed YES bid 50¢ / ask 54¢','Source: sequenced order book · sequence 17 · exchange clock 300','Previous ASK 56¢ · 0.1s between observations']);
});
import {resetMarkup} from '../apps/web/demo-client.mjs';
test('Demo reset is an owner POST route without any funding prerequisite',async()=>{
 const response=await proxyAuth(new Request('https://app.test/api/demo/reset',{method:'POST',headers:{origin:'https://app.test','content-type':'application/json'},body:JSON.stringify({request_id:'test'})}),env,options());assert.equal(response.status,200);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/reset'),env,options())).status,405);
 const html=resetMarkup({state:'awaiting_funds',message:'<unsafe>',market:'<market>',cash_cents:10000,target_balance_cents:100000,deposit_needed_cents:90000,open_orders:0,held_markets:0});
 assert.ok(!html.includes('$900.00'));assert.ok(!html.includes('$1,000.00'));assert.ok(!html.includes('<unsafe>'));assert.ok(!html.includes('<market>'));assert.match(html,/No target balance/);
 assert.ok(html.includes('Funding is optional'));assert.equal(resetMarkup(null),'');
});

import {squarePerformanceMarkup} from '../apps/web/demo-client.mjs';
test('Square performance labels estimates, empty denominators and original revisions safely',()=>{
 const empty={revision:2,square:0,condition:{asset:'<img>',min_price:60,max_price:69,min_minutes:0,max_minutes:5},orders:0,filled_orders:0,contracts:0,resting_contracts:0,held_contracts:0,scored:0,wins:0,recorded_pnl_cents:null,unscored_resets:1};
 const html=squarePerformanceMarkup({items:[empty],at:0,limited:true});
 assert.match(html,/&lt;img&gt;/);assert.doesNotMatch(html,/<img>/);assert.match(html,/v2 · square 1/);assert.match(html,/Estimated net/);assert.doesNotMatch(html,/NaN|Infinity/);assert.match(html,/Unscored reset closures: 1/);assert.match(html,/view is partial/);
 const traded=squarePerformanceMarkup({items:[{...empty,orders:4,filled_orders:2,scored:2,wins:1,recorded_pnl_cents:-35}],at:0});
 assert.match(traded,/50.0% filled/);assert.match(traded,/50.0% positive/);assert.match(traded,/-\$0.35/);
});

import {botGroup} from '../apps/web/demo-client.mjs';
test('routine confirmed-order verification keeps bots running; stalled, uncertain and scoped problems stay visible',()=>{
 const bot={key:'one',desired:'running'},health={state:'syncing',at:1002,reconciled_at:1000,sync_pending:{action:'accepted',bot:'two'},bots:{},blocked_markets:[]};
 assert.equal(botGroup(bot,health,[],1003),'Running');
 assert.equal(botGroup(bot,health,[],1046),'Needs attention');
 assert.equal(botGroup(bot,{...health,reconciled_at:0},[],1003),'Needs attention');
 assert.equal(botGroup(bot,{...health,issue:{code:'ambiguous'}},[],1003),'Needs attention');
 assert.equal(botGroup(bot,{...health,bots:{one:{exit_waiting:true}}},[],1003),'Running');
 assert.equal(botGroup(bot,{...health,blocked_markets:['BTC']},[{bot:'one',ticker:'BTC'}],1003),'Needs attention');
 assert.equal(botGroup(bot,{...health,blocked_markets:['BTC']},[{bot:'two',ticker:'BTC'}],1003),'Running');
 assert.equal(botGroup(bot,{...health,state:'attention'},[],1003),'Needs attention');
 assert.equal(botGroup({...bot,desired:'paused'},health,[],1003),'Paused');
});

import {botExposure,botExposureMarkup} from '../apps/web/demo-client.mjs';
test('bot dropdown separates held contracts, partial entry remainders, exits and uncertain writes',()=>{
 const orders=[{kind:'entry',ticker:'BTC<test>',side:'yes',price:60,filled:5,sold:2,remaining:4,status:'resting'},
 {kind:'entry',ticker:'BTC<test>',side:'yes',price:70,filled:2,sold:0,remaining:0,status:'held'},
 {kind:'exit',ticker:'BTC<test>',side:'yes',price:56,filled:0,remaining:3,status:'resting'},
 {kind:'entry',ticker:'OTHER',side:'no',price:80,filled:0,remaining:0,status:'uncertain'}];
 const result=botExposure(orders);assert.equal(result.positions.length,1);assert.equal(result.positions[0].quantity,5);assert.equal(result.positions[0].price,64);
 assert.equal(result.waiting.length,3);
 const html=botExposureMarkup(orders,'bot-one');assert.match(html,/BTC&lt;test&gt;/);assert.doesNotMatch(html,/BTC<test>/);assert.match(html,/Protective exit/);assert.match(html,/Unconfirmed/);assert.match(html,/both sections/);
 const empty=botExposureMarkup([]);assert.match(empty,/No open positions/);assert.match(empty,/No waiting orders/);
});

test('protective exits and rejected maker orders are informational while actual failures keep their explanation',()=>{
 const bot={key:'one',desired:'running'},health={state:'ready',at:1000,reconciled_at:999,bots:{one:{exit_waiting:true,message:'Waiting for a maker-only quote'}}};
 const orders=[{bot:'one',kind:'exit',status:'rejected',ticker:'BTC',remaining:0}];
 assert.equal(botGroup(bot,health,orders,1001),'Running');
 const failed={...health,state:'attention',issue:{summary:'Exchange connection unavailable',action:'Reconnecting automatically',phase:'stream',code:'connection'}};
 assert.equal(botGroup(bot,failed,orders,1001),'Needs attention');
 assert.equal(attentionInfo(bot,failed,orders,1001).reason,'Exchange connection unavailable');
});

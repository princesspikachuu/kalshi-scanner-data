import test from 'node:test';import assert from 'node:assert/strict';import {proxyAuth} from '../apps/gateway/index.mjs';import {selectedSquares} from '../apps/web/bot-builder.mjs';
import gateway from '../apps/gateway/index.mjs';
import {readFile} from 'node:fs/promises';
test('Every page entrypoint and imported module is served through the real gateway allowlist',async()=>{
 const base=new URL('../apps/web/',import.meta.url),queue=['index.html','bots.html','activity.html','collection.html','paper.html'],seen=new Set();
 const environment={APP_ORIGIN:'https://app.test',ASSETS:{fetch:async request=>new Response(await readFile(new URL(new URL(request.url).pathname.slice(1),base),'utf8'),{headers:{'content-type':request.url.endsWith('.mjs')?'text/javascript':'text/html'}})}};
 while(queue.length){
  const path=queue.shift();if(seen.has(path))continue;seen.add(path);
  const response=await gateway.fetch(new Request('https://app.test/'+path),environment);
  assert.equal(response.status,200,`${path} must be reachable before its page can start`);
  const source=await response.text();
  if(path.endsWith('.html'))for(const match of source.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["']/g)){
   if(!match[1].startsWith('http'))queue.push(new URL(match[1],'https://app.test/'+path).pathname.slice(1));
  }
  else for(const match of source.matchAll(/\bimport\s+(?:[^'";]*?\s+from\s+)?['"](\.[^'"]+\.mjs)['"]/g))queue.push(new URL(match[1],'https://app.test/'+path).pathname.slice(1));
 }
 assert.ok(seen.has('order-detail.mjs'));assert.ok(seen.has('activity-filters.mjs'));
 assert.equal((await gateway.fetch(new Request('https://app.test/not-an-app-module.mjs'),environment)).status,404);
});
const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)};
const options=()=>({fetcher:async(url,opts)=>{assert.equal(opts.headers.get('x-pocket-proxy'),env.API_PROXY_SECRET);return new Response(JSON.stringify({contract:'demo-v1',environment:'demo',bots:[],items:[]}),{headers:{'content-type':'application/json'}})}});
test('Demo routes preserve owner gateway and correct method',async()=>{
 for(const path of ['performance?bot=00000000-0000-0000-0000-000000000001','performance?bot=00000000-0000-0000-0000-000000000001&group=hour&period=7D&timezone=America%2FLos_Angeles','workspace','orders','activity?kind=fill','chart?period=7D','research?asset=btc&start=2026-10-01&end=2026-10-30']){
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

import {squarePerformanceMarkup,transactionBadge,orderDetailButton} from '../apps/web/demo-client.mjs';
import {orderDetailMarkup} from '../apps/web/order-detail.mjs';
import {matchingOrders,matchesActivity} from '../apps/web/activity-filters.mjs';
import {marketLink,squareGridMarkup,timePriceGridMarkup} from '../apps/web/demo-client.mjs';
test('History and current order filters agree on the bot and union of selected types',()=>{
 const filters={bot:'daily',ticker:'WEATHER',kinds:['fill','settlement']};
 assert.ok(matchesActivity({bot:'daily',ticker:'WEATHER',kind:'fill'},filters));
 assert.ok(matchesActivity({bot:'daily',ticker:'WEATHER',kind:'settlement'},filters));
 assert.ok(!matchesActivity({bot:'sports',ticker:'WEATHER',kind:'fill'},filters));
 const rows=[{bot:'daily',ticker:'WEATHER',filled:1},{bot:'sports',ticker:'SPORT',filled:1},{bot:'hilo',ticker:'BTC',filled:2}];
 assert.deepEqual(matchingOrders(rows,filters),[rows[0]]);
 assert.deepEqual(matchingOrders(rows,{...filters,kinds:['settlement']}),[]);
});
test('Performance grids retain square axes, empty standard time bands and unknown clocks',()=>{
 const metric={orders:2,filled_orders:1,scored:1,wins:1,resting_contracts:0,held_contracts:0,recorded_pnl_cents:3};
 const html=timePriceGridMarkup({time_bounds:[1,3,5,10,15],default_entry_price:3,items:[{...metric,bucket:15,entry_price:3},{...metric,bucket:null,entry_price:1}]});
 for(const text of ['10–15 min','5–10 min','3–5 min','1–3 min','0–1 min','3¢ entry limit','Time unavailable','No entries'])assert.ok(html.includes(text),text);
 const grid=squareGridMarkup({items:[{...metric,revision:1,square:0,condition:{asset:'btc',min_price:60,max_price:69,min_minutes:3,max_minutes:5}}]});
 assert.match(grid,/60–69¢/);assert.match(grid,/3–5 min/);assert.match(grid,/v1 · square 1/);
});
test('Activity market links stay in Kalshi Demo and cannot inject an arbitrary destination',()=>{
 assert.match(marketLink('KXBTC15M-26NOV011100-00'),/https:\/\/demo.kalshi.co\/markets\/kx\/m\/kxbtc15m-26nov011100/);
 assert.match(marketLink('KXBTC15M-26NOV011100-00',null),/demo.kalshi.co/);
 assert.doesNotMatch(marketLink('javascript:alert(1)'),/href=/);
 assert.doesNotMatch(marketLink('T-ONE',{event_ticker:'https://evil.test'}),/href=/);
});
test('Buy and sell details preserve parent context, partial fills and pending sells',()=>{
 const buy={client_id:'00000000-0000-0000-0000-000000000001',kind:'entry',bot:'b',ticker:'<ticker>',side:'yes',price:3,quantity:10,filled:4,sold:1,remaining:6,status:'resting'};
 const sell={client_id:'00000000-0000-0000-0000-000000000002',parent:buy.client_id,kind:'exit',exit_role:'profit',price:6,quantity:4,filled:1,remaining:3,status:'resting'};
 const html=orderDetailMarkup({entry:buy,exits:[sell],selected:sell.client_id});
 assert.match(html,/3 contracts still held/);assert.match(html,/Profit SELL · EXIT/);assert.match(html,/aria-current="true"/);assert.match(html,/&lt;ticker&gt;/);assert.doesNotMatch(html,/<ticker>/);
 assert.match(orderDetailMarkup({entry:{...buy,filled:0,sold:0},exits:[]}),/Waiting for the buy to fill/);
 assert.match(orderDetailButton(buy.client_id,'Buy → linked sells'),/data-order-detail=/);assert.equal(orderDetailButton('bad" onclick="x'),'');
});
test('Settlement badges use verified resolved sides independently of net P&L; fills distinguish entry and exit',()=>{
 assert.match(transactionBadge({kind:'settlement',details:{side:'yes',quote:{result:'yes'},realized_cents:-3}}),/WIN · SETTLED/);
 assert.match(transactionBadge({kind:'settlement',details:{side:'no',quote:{result:'yes'},realized_cents:3}}),/LOSS · SETTLED/);
 assert.match(transactionBadge({kind:'settlement',details:{realized_cents:10}}),/OUTCOME UNAVAILABLE/);
 assert.match(transactionBadge({kind:'fill',details:{order_kind:'entry'}}),/BUY FILL · ENTRY/);
 assert.match(transactionBadge({kind:'fill',details:{order_kind:'exit'}}),/SELL FILL · EXIT/);
});
test('Order detail remains an owner GET route with a bounded identifier filter',async()=>{
 const path='https://app.test/api/demo/orders?client_id=00000000-0000-0000-0000-000000000001';
 assert.equal((await proxyAuth(new Request(path),env,options())).status,200);
 assert.equal((await proxyAuth(new Request(path,{method:'POST'}),env,options())).status,405);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/workspace?client_id=x'),env,options())).status,422);
});
import {latestTransactionsMarkup} from '../apps/web/demo-client.mjs';
test('Latest transaction dropdown distinguishes order events and fills and escapes evidence',()=>{
 const html=latestTransactionsMarkup({loadedAt:1,items:[{kind:'order_rejected',time:'2026-11-01T08:00:00Z',ticker:'<bad>',message:'Rejected <unsafe>',details:{order_kind:'entry',side:'yes',price:3,quantity:10}},{kind:'fill',time:'2026-11-01T08:01:00Z',details:{order_kind:'exit',side:'no',filled:2,exchange_id:'<order>'}}]},'bot-one');
 for(const value of ['Order rejected','Fill confirmed','Buy','Sell','3¢ limit','Filled so far: 2','/activity?bot=bot-one','&lt;bad&gt;','&lt;order&gt;'])assert.ok(html.includes(value),value);
 assert.doesNotMatch(html,/<bad>|<unsafe>|<order>/);
 assert.match(latestTransactionsMarkup({items:[],loadedAt:1},'b'),/No saved transactions/);
});
test('Time performance shows entry cohorts, local date filters, and unknown historical clocks',()=>{
 const row={label:'Time remaining unavailable',orders:2,filled_orders:1,contracts:1,resting_contracts:0,held_contracts:0,scored:1,wins:1,unscored_resets:0,recorded_pnl_cents:3};
 const html=squarePerformanceMarkup({group:'remaining',items:[row],start:'2026-11-01',end:'2026-11-01',timezone:'America/Los_Angeles',at:0});
 assert.match(html,/Time remaining at entry/);assert.match(html,/2026-11-01 through 2026-11-01/);
 assert.match(html,/America\/Los_Angeles/);assert.match(html,/Time remaining unavailable/);assert.match(html,/across revisions/);
 assert.doesNotMatch(html,/square \?/);
});

test('Time statistics show the selected clock and retain unknown historical times',()=>{
 const item={bucket:null,label:'Time unavailable',orders:2,filled_orders:1,contracts:1,resting_contracts:0,held_contracts:0,scored:1,wins:1,unscored_resets:0,recorded_pnl_cents:5};
 const html=squarePerformanceMarkup({group:'time',period:'7D',items:[item],at:0});
 assert.match(html,/Time remaining at entry/);assert.match(html,/Time unavailable/);assert.match(html,/7D/);assert.doesNotMatch(html,/square \?/);
 assert.match(squarePerformanceMarkup({group:'hour',period:'Lifetime',timezone:'America/Los_Angeles',items:[{...item,label:'01:00–02:00'}],at:0}),/America\/Los_Angeles/);
});
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

import {demoError} from '../apps/web/demo-client.mjs';
test('bot save errors identify the field without exposing submitted values or raw error objects',()=>{
 const message=demoError([{loc:['body','squares',2,'maximum_cents'],msg:'Input should be less than or equal to 99',input:'SECRET'}, {loc:['body','bot_percent'],msg:'Input should be greater than 0'}],422);
 assert.match(message,/Square 3 · Maximum bid/);assert.match(message,/Bot allocation/);assert.doesNotMatch(message,/SECRET/);
 assert.equal(demoError('Bot settings changed elsewhere',409),'Bot settings changed elsewhere');
 assert.equal(demoError([{msg:'PRIVATE'}],500),'Unable to complete the request.');
});

import {historicalExposureMarkup} from '../apps/web/demo-client.mjs';
test('ended-market reconciliation is informational without suppressing live or uncertain problems',()=>{
 const bot={key:'one',desired:'running'},orders=[{bot:'one',ticker:'old'}],health={state:'ready',at:1000,blocked_markets:['old'],historical_markets:['old'],ownership_details:{old:{reason:'awaiting_settlement',expected_contracts:2,exchange_contracts:0,market_state:'closed'}}};
 assert.equal(botGroup(bot,health,orders,1001),'Running');
 const html=historicalExposureMarkup(bot,health,orders);assert.match(html,/awaiting exchange confirmation/);assert.match(html,/Saved net contracts: 2/);
 assert.equal(botGroup(bot,{...health,historical_markets:[]},orders,1001),'Needs attention');
 const failure={...health,state:'attention',issue:{summary:'Connection failed',action:'Retrying',phase:'stream'}};
 assert.equal(botGroup(bot,failure,orders,1001),'Needs attention');assert.equal(attentionInfo(bot,failure,orders,1001).reason,'Connection failed');
 assert.equal(historicalExposureMarkup({key:'unrelated'},health,orders),'');
});

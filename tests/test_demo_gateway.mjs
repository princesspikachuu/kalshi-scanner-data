import {readFileSync} from 'node:fs';
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
 for(const text of ['Saved order not returned','Review Activity','Retry verification','Order reconciliation','KXBTC15M-TEST','order-one','not_found','HTTP 404','Last exchange check'])assert.ok(html.includes(text),text);
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
 const undo=await proxyAuth(new Request('https://app.test/api/demo/reset/undo',{method:'POST',headers:{origin:'https://app.test','content-type':'application/json'},body:JSON.stringify({request_id:'test'})}),env,options());
 assert.equal(undo.status,200);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/reset/undo'),env,options())).status,405);
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

import {botExposure,botExposureMarkup,marketPhase,ordersForView,nextMarketBoundary} from '../apps/web/demo-client.mjs';
test('bot dropdown separates held contracts, partial entry remainders, exits and uncertain writes',()=>{
 const orders=[{kind:'entry',ticker:'BTC<test>',side:'yes',price:60,filled:5,sold:2,remaining:4,status:'resting'},
 {kind:'entry',ticker:'BTC<test>',side:'yes',price:70,filled:2,sold:0,remaining:0,status:'held'},
 {kind:'exit',ticker:'BTC<test>',side:'yes',price:56,filled:0,remaining:3,status:'resting'},
 {kind:'entry',ticker:'OTHER',side:'no',price:80,filled:0,remaining:0,status:'uncertain'}];
 for(const order of orders)order.close=Date.now()/1000+60;
 const result=botExposure(orders);assert.equal(result.positions.length,1);assert.equal(result.positions[0].quantity,5);assert.equal(result.positions[0].price,64);
 assert.equal(result.waiting.length,3);
 const html=botExposureMarkup(orders,'bot-one');assert.match(html,/BTC&lt;test&gt;/);assert.doesNotMatch(html,/BTC<test>/);assert.match(html,/Protective exit/);assert.match(html,/Unconfirmed/);assert.match(html,/both orders and positions/);
 const empty=botExposureMarkup([]);assert.match(empty,/No open positions/);assert.match(empty,/No active buy orders/);assert.match(empty,/No active sell orders/);
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

test('brief identified position synchronization does not mislabel every overlapping bot',()=>{
 const orders=[{bot:'a',ticker:'T'},{bot:'b',ticker:'T'}],bot={key:'a',desired:'running'};
 const health={state:'ready',at:1000,reconciled_at:995,blocked_markets:['T'],syncing_markets:['T'],historical_markets:[],
  ownership_details:{T:{reason:'position_difference',expected_contracts:2,exchange_contracts:0,blocked_seconds:3,
   bots:[{id:'a',name:'Alpha',held_yes:3,held_no:0,net_contracts:3},{id:'b',name:'<bad>',held_yes:0,held_no:1,net_contracts:-1}],
   orders:[{bot_id:'a',bot_name:'Alpha',kind:'entry',side:'yes',client_id:'entry-one',status:'held',filled:3,remaining:0}],order_count:1}}};
 assert.equal(botGroup(bot,health,orders,1001),'Running');
 assert.equal(attentionInfo(bot,health,orders,1001).markets.length,0);
 const unresolved={...health,syncing_markets:[]};
 assert.equal(botGroup(bot,unresolved,orders,1001),'Needs attention');
 const info=attentionInfo(bot,unresolved,orders,1001),html=attentionMarkup(info,{botId:'a'});
 for(const expected of ['Alpha','entry-one','Held YES','Kalshi account net','3','T'])assert.ok(html.includes(expected),expected);
 assert.ok(html.includes('&lt;bad&gt;'));assert.ok(!html.includes('<bad>'));
});


test('active contracts move to Pending exactly at close, before settlement and without a new server snapshot',()=>{
 const now=1000,entry={kind:'entry',client_id:'buy',ticker:'t',side:'yes',entry_strategy:'buy_low_sell_high',market_close_at:1100,close:920,filled:5,sold:0,price:3,remaining:0,status:'held'},
 sell={kind:'exit',parent:'buy',ticker:'t',side:'yes',close:1100,remaining:5,filled:0,price:9,status:'resting'};
 const orders=[entry,sell];
 assert.equal(marketPhase(entry,{},now),'active','buy cancellation deadline is not market close');
 assert.equal(botExposure(orders,{now:1099.999}).positions.length,1);
 assert.equal(botExposure(orders,{now:1099.999}).sells.length,1);
 assert.equal(botExposure(orders,{now:1100}).positions.length,0);
 assert.equal(botExposure(orders,{now:1100}).waiting.length,0);
 const pending=botExposure(orders,{now:1100,view:'pending'});
 assert.equal(pending.positions[0].quantity,5);assert.match(pending.positions[0].sellStatus,/Awaiting settlement/);
 assert.equal(pending.sells.length,1);assert.equal(sell.status,'resting','display must not fake cancellation or settlement');
 assert.equal(nextMarketBoundary(orders,{},now),1100);
});
test('actual market close wins over an early sports deadline; closed exchange status wins over future timestamps',()=>{
 const order={kind:'entry',ticker:'game',entry_strategy:'buy_low_sell_high',condition:{asset:'sports'},market_close_at:800,close:620,status:'held',filled:1,price:3};
 const health={markets:{game:{open:100,close:1200,status:'active'}}};
 assert.equal(marketPhase(order,health,1000),'active');
 assert.equal(marketPhase(order,{markets:{game:{close:1200,status:'closed'}}},1000),'ended');
 assert.equal(marketPhase({...order,market_trading_close_at:1200},{},1000),'active');
 assert.equal(marketPhase(order,{},1000),'unknown','estimated sports finish cannot silently remove a live position');
 assert.equal(ordersForView([order],{},'pending',1000).length,1);
});
test('missing and partial sell coverage are explicit, and terminal records never reappear as active positions',()=>{
 const entry={kind:'entry',ticker:'t',side:'yes',price:3,filled:5,sold:0,close:2000,status:'held',entry_strategy:'buy_low_sell_high'};
 const sell={kind:'exit',ticker:'t',side:'yes',price:6,filled:0,remaining:5,close:2180,status:'resting'};
 assert.match(botExposure([entry],{now:1000}).positions[0].sellStatus,/Sell pending/);
 assert.equal(botExposure([entry,sell],{now:1000}).positions[0].sellStatus,'Sell order active');
 assert.match(botExposure([entry,{...sell,remaining:2}],{now:1000}).positions[0].sellStatus,/Partly covered/);
 assert.match(botExposure([entry,{...sell,status:'uncertain'}],{now:1000}).positions[0].sellStatus,/confirmation pending/);
 assert.equal(botExposure([{...entry,status:'closed'}],{now:1000}).positions.length,0);
});
test('active and pending order summaries share the same boundary across bots and Activity',()=>{
 const orders=[{ticker:'old',kind:'entry',close:900,status:'uncertain',remaining:0},
 {ticker:'live',kind:'entry',close:1100,status:'resting',remaining:2},
 {ticker:'unknown',kind:'entry',status:'uncertain'},
 {ticker:'terminal',kind:'exit',close:1100,status:'rejected'}];
 assert.deepEqual(ordersForView(orders,{},'active',1000).map(o=>o.ticker),['live']);
 assert.deepEqual(ordersForView(orders,{},'pending',1000).map(o=>o.ticker),['old','unknown']);
 const html=botExposureMarkup(orders,'bot',{now:1000,view:'pending'});
 assert.match(html,/Confirmation pending/);assert.doesNotMatch(html,/Waiting to buy/);
 const bots=readFileSync(new URL('../apps/web/bots.mjs',import.meta.url),'utf8');
 const activity=readFileSync(new URL('../apps/web/activity.mjs',import.meta.url),'utf8');
 for(const source of [bots,activity])assert.match(source,/nextMarketBoundary/);
});

test('following an ended buy shows historical orders and pending settlement, never says exit rules are still active',()=>{
 const html=orderDetailMarkup({entry:{ticker:'t',side:'yes',kind:'entry',price:3,filled:2,sold:0,status:'held',close:900},exits:[]},1000);
 assert.match(html,/Market closed/);assert.match(html,/pending settlement \/ confirmation/);
 assert.doesNotMatch(html,/exit rules remain active/);
});

import {loadDemoSnapshots} from '../apps/web/demo-client.mjs';
test('a large valid Demo workspace is not mistaken for a sign-in failure; oversized responses remain bounded',async()=>{
 const payload={contract:'demo-v1',environment:'demo',bots:Array.from({length:70},(_,i)=>({key:String(i),config:{name:'Bot '+i},details:'x'.repeat(4000)}))};
 assert.ok(JSON.stringify(payload).length>262144);
 let response=await proxyAuth(new Request('https://app.test/api/demo/workspace'),env,{fetcher:async()=>new Response(JSON.stringify(payload),{headers:{'content-type':'application/json'}})});
 assert.equal(response.status,200);assert.equal((await response.json()).bots.length,70);
 payload.bots[0].details='x'.repeat(2097153);
 response=await proxyAuth(new Request('https://app.test/api/demo/workspace'),env,{fetcher:async()=>new Response(JSON.stringify(payload),{headers:{'content-type':'application/json'}})});
 assert.equal(response.status,502);assert.match((await response.json()).detail,/Demo data exceeds/);
});
test('failed order requests preserve a successful workspace and identify the failing component',async()=>{
 const workspace={contract:'demo-v1',bots:[{key:'saved'}],health:{state:'ready'}};
 const result=await loadDemoSnapshots(async path=>{if(path==='orders')throw Error('Order request timed out');return workspace});
 assert.equal(result.workspace,workspace);assert.equal(result.orders,null);assert.match(result.errors[0],/^Orders and positions:/);
 const reversed=await loadDemoSnapshots(async path=>{if(path.startsWith('workspace'))throw Error('Workspace unavailable');return {contract:'demo-v1',items:[{client_id:'saved-order'}]}});
 assert.equal(reversed.orders.items[0].client_id,'saved-order');assert.match(reversed.errors[0],/^Bot workspace:/);
});
test('Demo transport errors describe data loading rather than telling an authenticated user sign-in is unavailable',async()=>{
 const response=await proxyAuth(new Request('https://app.test/api/demo/orders'),env,{fetcher:async()=>{throw Error('upstream unavailable')}});
 assert.equal(response.status,502);const body=await response.json();assert.match(body.detail,/Unable to load Demo data/);assert.doesNotMatch(body.detail,/Sign-in/);
});

test('the real dashboard renders bots and balances when orders fail, retries, and preserves last good data',async()=>{
 const original=Object.fromEntries(['document','window','location','localStorage','fetch','setTimeout','clearTimeout'].map(k=>[k,globalThis[k]]));
 const nodes=new Map(),element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,open:false,dataset:{},addEventListener(){},setAttribute(){},querySelectorAll(){return []},replaceChildren(){this.innerHTML=''}});return nodes.get(id)};
 let orderFails=true,workspaceFails=false;const requested=[];
 const now=Date.now()/1000,workspace={contract:'demo-v1',reset_mode:'archive_copy',alerts:[],account:{equity_cents:10000,cash_cents:9000,position_value_cents:1000,at:now},bots:[{key:'saved',revision:1,desired:'running',config:{name:'Saved BTC bot',strategy:'buy_low_sell_high',cycle_buy_cents:3,cycle_sell_cents:6,bot_percent:3,squares:[{asset:'btc'}]}}],health:{state:'ready',at:now,reconciled_at:now,message:'Demo account verified'},metrics:{}};
 try{
  globalThis.document={hidden:false,cookie:'',getElementById:element,querySelectorAll(){return []},addEventListener(){}};
  globalThis.window={addEventListener(){}};globalThis.location={search:'',replace(){}};
  globalThis.localStorage={getItem(key){return key==='money-period'?'6H':null},setItem(){},removeItem(){}};
  globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};
  element('filter').value='active';element('marketView').value='active';
  globalThis.fetch=async url=>{
   requested.push(url);
   if(url.includes('/orders')&&orderFails)throw Error('Orders unavailable');
   if(url.includes('/workspace')&&workspaceFails)throw Error('Workspace unavailable');
   return {ok:true,status:200,json:async()=>url.includes('/workspace')?workspace:{contract:'demo-v1',items:[]}};
  };
  await import('../apps/web/bots.mjs?partial-load-test');
  for(let i=0;i<8;i++)await new Promise(setImmediate);
  assert.match(element('groups').innerHTML,/Saved BTC bot/);assert.equal(element('accountValue').textContent,'$100.00');assert.ok(requested.some(u=>u.endsWith('workspace?period=6H&version=latest')));
  assert.match(element('groups').innerHTML,/Orders and positions · unavailable/);
  assert.match(element('message').textContent,/Orders and positions: Orders unavailable/);
  orderFails=false;await element('reloadData').onclick();
  assert.match(element('groups').innerHTML,/0 positions · 0 buys · 0 sells/);assert.equal(element('message').textContent,'');
  workspaceFails=true;orderFails=true;await element('reloadData').onclick();
  assert.match(element('groups').innerHTML,/Saved BTC bot/);assert.equal(element('accountValue').textContent,'$100.00');assert.ok(requested.some(u=>u.endsWith('workspace?period=6H&version=latest')));
  assert.match(element('message').textContent,/Bot workspace:/);assert.match(element('message').textContent,/Showing the latest data/);
 }finally{for(const [k,v] of Object.entries(original)){if(v===undefined)delete globalThis[k];else globalThis[k]=v}}
});

import {tradingNoticesMarkup} from '../apps/web/demo-client.mjs';
test('trading warnings are compact by default, expandable, and preserve full escaped details',()=>{
 const alerts=[{message:'Transfer waiting <test>',critical:true},{message:'20 markets wait',critical:true}];
 const html=tradingNoticesMarkup(alerts,{message:'Order confirmation pending',stream:{disconnects:37}});
 assert.match(html,/Trading needs attention/);assert.match(html,/2 notices/);
 assert.doesNotMatch(html,/<details[^>]*\bopen\b/);assert.match(html,/Transfer waiting &lt;test&gt;/);
 assert.match(html,/37 price-feed reconnects/);assert.match(tradingNoticesMarkup(alerts,{},true),/<details[^>]*\bopen\b/);
 assert.equal(tradingNoticesMarkup([],{}),'');
});

test('hour and six-hour filters pass through to every Demo performance endpoint',async()=>{
 for(const period of ['1H','6H'])for(const path of ['workspace','chart','performance?bot=00000000-0000-0000-0000-000000000001']){
  let called;const query=path+(path.includes('?')?'&':'?')+'period='+period;
  const response=await proxyAuth(new Request('https://app.test/api/demo/'+query),env,{fetcher:async(url)=>{called=new URL(url);return new Response(JSON.stringify({contract:'demo-v1',period}),{headers:{'content-type':'application/json'}})}});
  assert.equal(response.status,200);assert.equal(called.searchParams.get('period'),period);
 }
});

import {activityMarketMarkup,completedPairRow} from '../apps/web/activity-filters.mjs';
test('Completed pairs show custom bot names, both legs, weighted sell prices, fees and escaped market context',()=>{
 const bots=new Map([['bot','Etherium <custom>']]);
 const item={entry:{client_id:'00000000-0000-0000-0000-000000000001',bot:'bot',ticker:'KXETH15M-26NOV041315-1',side:'yes',price:3,market_close_at:1800000000},contracts:10,sell_price:8.4,sell_count:2,fees:1,estimated_net_cents:53,completed_at:1800000000};
 const html=completedPairRow(item,bots);
 for(const value of ['Etherium &lt;custom&gt;','15-minute market','YES','Closes','BUY FILLED','SELL FILLED','8.4¢','10 contracts fully bought','across 2 sells','$0.53','recorded fees $0.01','data-order-detail=','Market code'])assert.ok(html.includes(value),value);
 assert.doesNotMatch(html,/<custom>/);
 assert.match(activityMarketMarkup({bot:'bot',ticker:item.entry.ticker,details:{side:'no',quote:{title:'<unsafe>'}}},bots),/&lt;unsafe&gt; · NO/);
});
test('Completed pair history is an owner-only GET with bounded filtering',async()=>{
 const path='https://app.test/api/demo/orders?completed=true&bot=00000000-0000-0000-0000-000000000001&ticker=TEST';
 assert.equal((await proxyAuth(new Request(path),env,options())).status,200);
 assert.equal((await proxyAuth(new Request(path,{method:'POST'}),env,options())).status,405);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/workspace?completed=true'),env,options())).status,422);
});
test('Activity switches between events and completed pairs, preserves bot filtering and paginates the selected view',async()=>{
 const names=['document','window','location','fetch','setTimeout','clearTimeout'],original=Object.fromEntries(names.map(k=>[k,globalThis[k]]));
 const nodes=new Map(),element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,insertAdjacentHTML(){},addEventListener(){}});return nodes.get(id)};
 const bot='00000000-0000-0000-0000-000000000010',buy='00000000-0000-0000-0000-000000000001',requested=[];
 const pair={id:buy,entry:{client_id:buy,bot,ticker:'KXETH15M-26NOV041315-1',side:'yes',price:3},contracts:2,sell_price:9,sell_count:1,fees:0,estimated_net_cents:12};
 const workspace={contract:'demo-v1',bots:[{key:bot,config:{name:'My Ethereum'}}],health:{},alerts:[],policy:{}};
 try{
  globalThis.document={hidden:false,cookie:'',getElementById:element,querySelectorAll(){return []},addEventListener(){}};
  globalThis.window={addEventListener(){}};globalThis.location={search:'',replace(){}};globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};
  element('historyView').value='events';element('marketView').value='active';
  globalThis.fetch=async url=>{
   requested.push(url);const parsed=new URL(url,'https://app.test');
   let payload={contract:'demo-v1',items:[]};
   if(parsed.pathname.endsWith('workspace'))payload=workspace;
   if(parsed.searchParams.get('completed')==='true')payload={contract:'demo-v1',items:[pair],next_before:parsed.searchParams.has('before')?null:buy};
   return {ok:true,status:200,json:async()=>payload};
  };
  await import('../apps/web/activity.mjs?completed-pair-test');for(let i=0;i<8;i++)await new Promise(setImmediate);
  element('botFilter').value=bot;element('historyView').value='pairs';await element('historyView').onchange();
  assert.equal(element('activityTypes').hidden,true);assert.match(element('events').innerHTML,/My Ethereum/);assert.match(element('events').innerHTML,/BUY FILLED/);
  assert.match(element('events').innerHTML,/data-label="Bot \/ market"/);assert.equal(element('older').hidden,false);
  await element('older').onclick();assert.equal(element('older').hidden,true);
  const last=new URL(requested.at(-1),'https://app.test');assert.equal(last.searchParams.get('before'),buy);assert.equal(last.searchParams.get('bot'),bot);
  element('historyView').value='events';await element('historyView').onchange();assert.equal(element('activityTypes').hidden,false);assert.doesNotMatch(element('events').innerHTML,/BUY FILLED/);
 }finally{for(const [k,v] of Object.entries(original)){if(v===undefined)delete globalThis[k];else globalThis[k]=v}}
});

import {analysisVersionMarkup,analysisVersionPreference} from '../apps/web/demo-client.mjs';
test('Analysis versions distinguish matched settings times, uncertain boundaries and full history',()=>{
 const cohort={revision:2,buy_cents:3,sell_cents:6,changed_at:1793757600,first_entry_at:1793757700};
 assert.match(analysisVersionMarkup(cohort,'latest'),/Most recent version · v2 · 3¢ buy \/ 6¢ sell/);
 assert.match(analysisVersionMarkup(cohort,'latest'),/Older entry lots are excluded/);
 assert.match(analysisVersionMarkup(cohort,'full'),/Full history · all versions/);
 const uncertain=analysisVersionMarkup({...cohort,changed_at:null,window_start:1793757500,window_end:1793757600},'latest');
 assert.match(uncertain,/First verified entry for this version/);assert.match(uncertain,/Settings change falls between/);
 assert.doesNotMatch(uncertain,/Version started/);
 assert.equal(analysisVersionPreference(),'latest');
});
test('Version filters reach workspace, performance, transaction history and completed pairs',async()=>{
 for(const path of ['workspace?period=6H','performance?bot=00000000-0000-0000-0000-000000000001','activity?kind=transactions','orders?completed=true']){
  let upstream;const response=await proxyAuth(new Request('https://app.test/api/demo/'+path+'&version=latest'),env,{fetcher:async(url)=>{upstream=new URL(url);return new Response(JSON.stringify({contract:'demo-v1',items:[]}),{headers:{'content-type':'application/json'}})}});
  assert.equal(response.status,200);assert.equal(upstream.searchParams.get('version'),'latest');
 }
});

import {botSummaryPeriodMarkup,botSummaryPeriodPreferences} from '../apps/web/demo-client.mjs';
test('Each bot summary has visible Lifetime, 1h, 6h and 24h buttons with an accessible selected state',()=>{
 const html=botSummaryPeriodMarkup('ethereum','6H');
 for(const label of ['Lifetime','1h','6h','24h'])assert.ok(html.includes('>'+label+'</button>'));
 assert.match(html,/data-summary-period="6H" aria-pressed="true"/);
 assert.equal((html.match(/aria-pressed="true"/g)||[]).length,1);
 assert.doesNotMatch(html,/<select|<details/);assert.match(html,/data-bot-summary="ethereum"/);
 const original=globalThis.localStorage;let saved;
 try{
  globalThis.localStorage={getItem(){return saved},setItem(k,v){saved=v}};
  botSummaryPeriodPreferences({ethereum:'6H',bitcoin:'all'});
  assert.deepEqual(botSummaryPeriodPreferences(),{ethereum:'6H',bitcoin:'all'});
 }finally{if(original===undefined)delete globalThis.localStorage;else globalThis.localStorage=original}
});

test('Inactive markets get per-bot attention without pausing healthy bots',async()=>{
 const {botGroup,attentionInfo,analysisVersionMarkup}=await import('../apps/web/demo-client.mjs');
 const now=1800000000,health={at:now,state:'ready',reconciled_at:now,bots:{quiet:{market_inactive:{reason:'No current active market',action:'Recheck every minute; waiting cash released'}}}};
 assert.equal(botGroup({key:'quiet',desired:'running'},health,[],now),'Needs attention');
 assert.equal(botGroup({key:'healthy',desired:'running'},health,[],now),'Running');
 assert.match(attentionInfo({key:'quiet'},health,[],now).reason,/No current/);
 const markup=analysisVersionMarkup({revision:3,buy_cents:3,sell_cents:null,exit_mode:'late_threshold',hold_threshold_cents:40,changed_at:now},'latest');
 assert.match(markup,/conditional late exit below 40/);assert.doesNotMatch(markup,/6¢ sell/);
});

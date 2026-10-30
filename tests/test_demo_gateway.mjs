import test from 'node:test';import assert from 'node:assert/strict';import {proxyAuth} from '../apps/gateway/index.mjs';import {selectedSquares} from '../apps/web/bot-builder.mjs';
const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)};
const options=()=>({fetcher:async(url,opts)=>{assert.equal(opts.headers.get('x-pocket-proxy'),env.API_PROXY_SECRET);return new Response(JSON.stringify({contract:'demo-v1',environment:'demo',bots:[],items:[]}),{headers:{'content-type':'application/json'}})}});
test('Demo routes preserve owner gateway and correct method',async()=>{
 for(const path of ['workspace','orders','activity?kind=fill','chart?period=7D','research?asset=btc&start=2026-10-01&end=2026-10-30']){
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
test('Demo reset is an owner POST route and renders real remaining funds safely',async()=>{
 const response=await proxyAuth(new Request('https://app.test/api/demo/reset',{method:'POST',headers:{origin:'https://app.test','content-type':'application/json'},body:JSON.stringify({request_id:'test'})}),env,options());assert.equal(response.status,200);
 assert.equal((await proxyAuth(new Request('https://app.test/api/demo/reset'),env,options())).status,405);
 const html=resetMarkup({state:'awaiting_funds',message:'<unsafe>',market:'<market>',cash_cents:10000,target_balance_cents:100000,deposit_needed_cents:90000,open_orders:0,held_markets:0});
 assert.ok(html.includes('$900.00'));assert.ok(html.includes('$1,000.00'));assert.ok(!html.includes('<unsafe>'));assert.ok(!html.includes('<market>'));
 assert.ok(html.includes('Fresh bots stay paused'));assert.equal(resetMarkup(null),'');
});

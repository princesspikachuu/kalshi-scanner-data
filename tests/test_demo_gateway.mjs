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

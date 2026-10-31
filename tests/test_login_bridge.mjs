import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import gateway,{proxyAuth} from '../apps/gateway/index.mjs';
import {createAuthClient,cookieValue,AuthError} from '../apps/web/auth-client.mjs';
const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'server-only-'.repeat(4)};
const csrf='c'.repeat(43),nonce='n'.repeat(43);
const challenge={client_id:'client.apps.googleusercontent.com',nonce,csrf_token:csrf,expires_in:300};
function request(path='/api/auth/challenge',options={}){return new Request('https://app.test'+path,options)}
function json(data,status=200,headers={}){return new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json',...headers}})}
function post(options={}){return request('/api/auth/google',{method:'POST',headers:{origin:env.APP_ORIGIN,'content-type':'application/json',...options.headers},body:options.body||JSON.stringify({credential:'opaque',nonce,csrf_token:csrf})})}
function setCookies(){return ['__Host-pocket_session=s; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Secure; HttpOnly; SameSite=strict','__Host-pocket_csrf=c; Path=/; Secure; SameSite=strict','__Host-pocket_login=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=strict','__Host-pocket_login_csrf=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=strict']}

test('gateway requires configuration and never sends credentials to a caller-chosen host',async()=>{
 let calls=0;const fetcher=async()=>{calls++;return json(challenge)};
 assert.equal((await proxyAuth(request(),{}, {fetcher})).status,503);
 for(const API_ORIGIN of ['http://api.test','https://user:secret@api.test','https://api.test/path','https://app.test']){
  assert.equal((await proxyAuth(request(),{...env,API_ORIGIN},{fetcher})).status,503);
 }
 assert.equal((await proxyAuth(request('/api/auth/challenge?destination=https://evil.test'),env,{fetcher})).status,400);
 assert.equal(calls,0);
});
test('gateway rejects unknown paths, methods and cross-origin requests before fetch',async()=>{
 const fetcher=()=>assert.fail('must not fetch');
 assert.equal((await proxyAuth(request('/api/orders'),env,{fetcher})).status,404);
 assert.equal((await proxyAuth(request('/api/auth/google'),env,{fetcher})).status,405);
 assert.equal((await proxyAuth(post({headers:{origin:'https://evil.test'}}),env,{fetcher})).status,403);
 assert.equal((await proxyAuth(request('/api/auth/challenge',{headers:{'sec-fetch-site':'cross-site'}}),env,{fetcher})).status,403);
});
test('gateway replaces forged proxy headers and forwards only application cookies',async()=>{
 let sent;
 const r=await proxyAuth(post({headers:{'x-pocket-proxy':'forged',authorization:'Bearer do-not-forward',cookie:'analytics=private; __Host-pocket_login='+nonce+'; __Host-pocket_login_csrf='+csrf}}),env,{fetcher:async(url,options)=>{sent={url,...options};return json({authenticated:true,email:'owner@example.test',private_backend_field:'hidden'})}});
 assert.equal(sent.url,'https://api.test/auth/google');assert.equal(sent.redirect,'manual');
 assert.equal(sent.headers.get('x-pocket-proxy'),env.API_PROXY_SECRET);
 assert.equal(sent.headers.get('authorization'),null);assert.doesNotMatch(sent.headers.get('cookie'),/analytics/);
 assert.equal(JSON.parse(new TextDecoder().decode(sent.body)).credential,'opaque');
 assert.deepEqual(await r.json(),{authenticated:true,email:'owner@example.test'});
});
test('all four Set-Cookie headers survive separately, including comma-bearing dates',async()=>{
 const headers=new Headers({'content-type':'application/json'});
 for(const line of setCookies())headers.append('set-cookie',line);
 headers.append('set-cookie','unrelated=not-forwarded; Path=/');
 const response=await proxyAuth(post(),env,{fetcher:async()=>new Response(JSON.stringify({authenticated:true,email:'owner@example.test'}),{headers})});
 assert.equal(response.headers.getSetCookie().length,4);
 assert.match(response.headers.getSetCookie()[0],/Expires=Wed, 21 Oct/);
 assert.equal(response.headers.get('cache-control'),'no-store');
});
test('Cloudflare getAll fallback never splits cookie values on commas',async()=>{
 const headers={getSetCookie:undefined,getAll:name=>{assert.equal(name,'Set-Cookie');return setCookies()},get:name=>name==='content-type'?'application/json':null};
 const original=json({authenticated:true,email:'owner@example.test'});
 const result=await proxyAuth(post(),env,{fetcher:async()=>({ok:true,status:200,headers,body:original.body})});
 assert.equal(result.headers.getSetCookie().length,4);
});
test('unsafe backend cookie attributes fail closed',async()=>{
 const response=await proxyAuth(post(),env,{fetcher:async()=>json({authenticated:true,email:'owner@example.test'},200,{'set-cookie':'__Host-pocket_session=secret; Domain=app.test; Path=/; Secure; HttpOnly; SameSite=strict'})});
 assert.equal(response.status,502);assert.equal(response.headers.get('set-cookie'),null);
});
test('redirects and backend errors never expose locations or raw diagnostics',async()=>{
 const redirect=await proxyAuth(request(),env,{fetcher:async()=>new Response(null,{status:302,headers:{location:'https://evil.test'}})});
 assert.equal(redirect.status,502);assert.equal(redirect.headers.get('location'),null);
 const error=await proxyAuth(request(),env,{fetcher:async()=>new Response('private database connection string',{status:500})});
 assert.equal(error.status,502);assert.doesNotMatch(await error.text(),/database/);
});
test('oversized requests are rejected without backend access',async()=>{
 const result=await proxyAuth(post({body:'x'.repeat(20481)}),env,{fetcher:()=>assert.fail('must not fetch')});
 assert.equal(result.status,413);
});
test('timeouts abort backend requests and return a generic error',async()=>{
 const response=await proxyAuth(request(),env,{timeoutMs:1,fetcher:async(_,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('secret'))))});
 assert.equal(response.status,504);assert.doesNotMatch(await response.text(),/secret/);
});
test('login assets carry CSP, popup support and cannot expose arbitrary files',async()=>{
 const assets={fetch:async()=>new Response('<html>preview</html>',{headers:{'content-type':'text/html'}})};
 const response=await gateway.fetch(request('/'),{...env,ASSETS:assets});
 assert.match(response.headers.get('content-security-policy'),/frame-ancestors 'none'/);
 assert.equal(response.headers.get('cross-origin-opener-policy'),'same-origin-allow-popups');
 assert.equal((await gateway.fetch(request('/infra/api.env.example'),{...env,ASSETS:assets})).status,404);
 const config=JSON.parse(fs.readFileSync('infra/wrangler.staging.json','utf8'));
 assert.equal(config.workers_dev,true);assert.equal(config.preview_urls,false);
 assert.equal(config.keep_vars,true);
 assert.notEqual(config.name,JSON.parse(fs.readFileSync('wrangler.jsonc','utf8')).name);
});
test('browser client sends credentials only in a same-origin JSON POST',async()=>{
 let sent;
 const client=createAuthClient({fetcher:async(url,options)=>{sent={url,...options};return json({authenticated:true,email:'owner@example.test'})}});
 await client.signIn('opaque-google-token',challenge);
 assert.equal(sent.url,'/api/auth/google');assert.equal(sent.credentials,'same-origin');assert.equal(sent.redirect,'error');
 assert.equal(JSON.parse(sent.body).nonce,nonce);assert.equal(JSON.parse(sent.body).credential,'opaque-google-token');
 assert.doesNotMatch(sent.url,/opaque|nonce/);
});
test('browser handles expired sessions without exposing provider messages',async()=>{
 const client=createAuthClient({fetcher:async()=>json({detail:'private provider diagnostic'},401)});
 assert.equal(await client.current(),null);
 await assert.rejects(client.signIn('token',challenge),error=>error instanceof AuthError&&!error.message.includes('private'));
});
test('logout reads the app CSRF cookie and waits for server revocation',async()=>{
 let sent;
 const client=createAuthClient({readCookie:()=>`unrelated=x; __Host-pocket_csrf=${csrf}`,fetcher:async(url,options)=>{sent={url,...options};return new Response(null,{status:204})}});
 await client.signOut();assert.equal(sent.url,'/api/auth/logout');assert.equal(sent.headers['x-csrf-token'],csrf);
 assert.equal(cookieValue('__Host-pocket_csrf_extra=wrong','__Host-pocket_csrf'),null);
 const missing=createAuthClient({readCookie:()=>'',fetcher:()=>assert.fail('must not fetch')});
 await assert.rejects(missing.signOut(),AuthError);
});
test('preview has no credential fields or browser-storage persistence',()=>{
 const sources=['apps/web/login.mjs','apps/web/auth-client.mjs'].map(f=>fs.readFileSync(f,'utf8')).join('\n');
 assert.doesNotMatch(sources,/localStorage|sessionStorage/);
 assert.doesNotMatch(fs.readFileSync('apps/web/index.html','utf8'),/<input|password/i);
});

test('research gateway allowlists read routes and bounded unique queries before fetch',async()=>{
 const fetcher=()=>assert.fail('must not fetch');
 for(const path of ['/api/research/results/1/observations?stream=btc','/api/research/orders?stream=btc','/api/research/results/01?stream=btc&view=latest']){
  assert.equal((await proxyAuth(request(path),env,{fetcher})).status,404);
 }
 for(const query of ['','?stream=btc&stream=eth','?stream=btc&limit=51','?stream=btc&day=2026-10-25','?stream=bad%20stream','?stream=btc&cursor=bad!']){
  assert.equal((await proxyAuth(request('/api/research/results'+query),env,{fetcher})).status,400);
 }
 assert.equal((await proxyAuth(request('/api/research/results/1?stream=btc'),env,{fetcher})).status,400);
 assert.equal((await proxyAuth(request('/api/research/results?stream=btc',{method:'POST'}),env,{fetcher})).status,405);
 assert.equal((await proxyAuth(request('/api/research/results?stream=btc',{headers:{origin:'https://evil.test'}}),env,{fetcher})).status,403);
});
test('research gateway forwards exact query and session without arbitrary headers or response cookies',async()=>{
 const body={contract:'research-history-v1',items:[{id:'9007199254740993'}],next_cursor:'opaque_cursor'};
 let sent;
 const response=await proxyAuth(request('/api/research/results?stream=btc-results&limit=1&cursor=opaque_cursor',{
  headers:{cookie:'__Host-pocket_session='+nonce+'; analytics=private',authorization:'Bearer private','x-pocket-proxy':'forged'}
 }),env,{fetcher:async(url,options)=>{sent={url,...options};return json(body,200,{'set-cookie':'private=hidden; Path=/'})}});
 assert.equal(response.status,200);assert.deepEqual(await response.json(),body);
 assert.equal(sent.url,'https://api.test/research/results?stream=btc-results&limit=1&cursor=opaque_cursor');
 assert.equal(sent.headers.get('authorization'),null);assert.equal(sent.headers.get('cookie'),'__Host-pocket_session='+nonce);
 assert.equal(sent.headers.get('x-pocket-proxy'),env.API_PROXY_SECRET);assert.equal(sent.redirect,'manual');
 assert.equal(response.headers.get('set-cookie'),null);assert.equal(response.headers.get('cache-control'),'no-store');
});
test('research gateway bounds responses and requires closed contract envelopes',async()=>{
 for(const data of [
  {contract:'future',items:[],next_cursor:null},
  {contract:'research-history-v1',items:[],next_cursor:null,email:'private-sentinel'},
  {contract:'research-history-v1',items:Array(51).fill({id:'1'}),next_cursor:null},
  {contract:'research-history-v1',items:[{id:9007199254740992}],next_cursor:null},
  {contract:'research-history-v1',items:[],next_cursor:'!'}
 ])assert.equal((await proxyAuth(request('/api/research/datasets?stream=raw'),env,{fetcher:async()=>json(data)})).status,502);
 const large={contract:'research-history-v1',items:[{id:'1',large:'x'.repeat(262144)}],next_cursor:null};
 assert.equal((await proxyAuth(request('/api/research/datasets?stream=raw'),env,{fetcher:async()=>json(large)})).status,502);
 const missing=await proxyAuth(request('/api/research/results/1?stream=btc&view=latest'),env,{fetcher:async()=>json({private:'sentinel'},404)});
 assert.equal(missing.status,404);assert.doesNotMatch(await missing.text(),/sentinel/);
 const valid={contract:'research-history-v1',view:'latest',result:{id:'1',cells:[]}};
 assert.deepEqual(await (await proxyAuth(request('/api/research/results/1?stream=btc&view=latest'),env,{fetcher:async()=>json(valid)})).json(),valid);
});

test('collection gateway allows bounded controls and only the progress date query',async()=>{
 const id='11111111-1111-4111-8111-111111111111';
 const payload={contract:'collection-v1',campaign:{id,status:'queued'}};
 let sent;
 const result=await proxyAuth(request('/api/collection/campaigns',{method:'POST',headers:{origin:env.APP_ORIGIN,'content-type':'application/json','x-csrf-token':csrf},body:'{}'}),env,{fetcher:async(url,options)=>{sent={url,...options};return json(payload)}});
 assert.equal(result.status,200);assert.equal(sent.url,'https://api.test/collection/campaigns');assert.equal(sent.headers.get('x-csrf-token'),csrf);
 const fetcher=()=>assert.fail('must not fetch');
 for(const path of ['/api/collection/run-trades','/api/collection/campaigns/'+id+'/delete','/api/collection/refresh/financial_daily'])assert.equal((await proxyAuth(request(path),env,{fetcher})).status,404);
 for(const path of ['/api/collection/campaigns/'+id+'?after=bad','/api/collection/campaigns/'+id+'?after=2026-10-25&after=2026-10-26','/api/collection/refresh/btc?enabled=true'])assert.equal((await proxyAuth(request(path),env,{fetcher})).status,400);
 const valid={contract:'collection-v1',refresh:{enabled:false,interval_seconds:3600}};
 assert.equal((await proxyAuth(request('/api/collection/refresh/btc'),env,{fetcher:async()=>json(valid)})).status,200);
 assert.equal((await proxyAuth(request('/api/collection/campaigns/'+id),env,{fetcher:async()=>json({...payload,private:'secret'})})).status,502);
});
test('date-range client uses same-origin CSRF mutations and retains request idempotency key',async()=>{
 const {createCollectionClient}=await import('../apps/web/collection-client.mjs');let sent;
 const client=createCollectionClient({readCookie:()=>`__Host-pocket_csrf=${csrf}`,fetcher:async(url,options)=>{sent={url,...options};return json({contract:'collection-v1'})}});
 await client.create('btc','2026-01-01','2026-10-26','request-id');
 assert.equal(sent.url,'/api/collection/campaigns');assert.equal(sent.credentials,'same-origin');assert.equal(sent.redirect,'error');
 assert.equal(sent.headers['x-csrf-token'],csrf);assert.equal(JSON.parse(sent.body).request_key,'request-id');
 assert.equal(JSON.parse(sent.body).end_date,'2026-10-26');
 await client.setRefresh('btc',true);assert.equal(sent.url,'/api/collection/refresh/btc');assert.equal(JSON.parse(sent.body).enabled,true);
 const missing=createCollectionClient({readCookie:()=>'',fetcher:()=>assert.fail('must not fetch')});
 await assert.rejects(missing.create('btc','a','b','id'),/Sign in/);
 const expired=createCollectionClient({fetcher:async()=>json({detail:'private-sentinel'},401)});
 await assert.rejects(expired.refresh('btc'),e=>e.status===401&&!e.message.includes('sentinel'));
});

test('campaign history gateway validates read-only category/keysets before fetching',async()=>{
 const id='11111111-1111-4111-8111-111111111111';let sent;
 const body={contract:'collection-v1',items:[{id,status:'queued'}],next_before:id};
 const response=await proxyAuth(request('/api/collection/campaigns?asset=btc&limit=1&before='+id),env,{fetcher:async(url,options)=>{sent={url,...options};return json(body)}});
 assert.equal(response.status,200);assert.deepEqual(await response.json(),body);assert.equal(sent.method,'GET');
 assert.equal(sent.url,'https://api.test/collection/campaigns?asset=btc&limit=1&before='+id);
 for(const query of ['', '?asset=financial_daily','?asset=btc&limit=51','?asset=btc&before=oops','?asset=btc&asset=eth','?asset=btc&after=2026-01-01']){
  assert.equal((await proxyAuth(request('/api/collection/campaigns'+query),env,{fetcher:()=>assert.fail('must not fetch')})).status,400);
 }
 const invalid={...body,items:Array(51).fill({id,status:'queued'})};
 assert.equal((await proxyAuth(request('/api/collection/campaigns?asset=btc'),env,{fetcher:async()=>json(invalid)})).status,502);
});

test('dashboard allows Cloudflare canonical HTML alias after asset redirect',async()=>{
 const paths=[];const configured={...env,ASSETS:{fetch:async request=>{paths.push(new URL(request.url).pathname);return new Response('<!doctype html><title>Dashboard</title>',{headers:{'content-type':'text/html'}})}}};
 for(const path of ['/collection','/collection.html']){
  const response=await gateway.fetch(request(path),configured);
  assert.equal(response.status,200);assert.match(await response.text(),/Dashboard/);
  assert.match(response.headers.get('content-security-policy'),/default-src 'none'/);
 }
 assert.deepEqual(paths,['/collection','/collection.html']);
});

test('worker heartbeat status is GET-only, bounded and rejects extra query state',async()=>{
 const body={contract:'collection-v1',worker:{state:'online',last_seen:'2026-10-27T19:00:00Z',heartbeat_ttl_seconds:90}};
 assert.deepEqual(await (await proxyAuth(request('/api/collection/status'),env,{fetcher:async()=>json(body)})).json(),body);
 assert.equal((await proxyAuth(request('/api/collection/status?secret=x'),env,{fetcher:()=>assert.fail('must not fetch')})).status,400);
 assert.equal((await proxyAuth(request('/api/collection/status',{method:'POST'}),env,{fetcher:()=>assert.fail('must not fetch')})).status,405);
 assert.equal((await proxyAuth(request('/api/collection/status'),env,{fetcher:async()=>json({...body,private:'sentinel'})})).status,502);
});

test('coverage window reads use the same bounded authenticated research gateway',async()=>{
 const payload={contract:'research-history-v1',items:[{id:'1',dataset_id:'9007199254740993',start_at:'2026-10-01T00:00:00Z',end_at:'2026-10-02T00:00:00Z'}],next_cursor:null};
 const response=await proxyAuth(request('/api/research/results/1/coverage?stream=category-btc&limit=1'),env,{fetcher:async()=>json(payload)});
 assert.equal(response.status,200);assert.deepEqual(await response.json(),payload);
 assert.equal((await proxyAuth(request('/api/research/results/1/coverage?stream=category-btc&view=latest'),env,{fetcher:()=>assert.fail('must not fetch')})).status,400);
});

test('all-category queue pages and removal remain authenticated bounded gateway routes',async()=>{
 const id='11111111-1111-4111-8111-111111111111';
 for(const group of ['unfinished','finished']){
  const body={contract:'collection-v1',items:[{id,status:'queued'}],next_before:null,total:1,group};
  const r=await proxyAuth(request('/api/collection/campaigns?asset=all&group='+group+'&limit=5'),env,{fetcher:async()=>json(body)});
  assert.equal(r.status,200);assert.deepEqual(await r.json(),body);
 }
 assert.equal((await proxyAuth(request('/api/collection/campaigns?asset=all&group=oops'),env,{fetcher:()=>assert.fail('must not fetch')})).status,400);
 const removed={contract:'collection-v1',campaign:{id,status:'cancelled'}};
 const r=await proxyAuth(request('/api/collection/campaigns/'+id+'/remove',{method:'POST',headers:{origin:env.APP_ORIGIN,'content-type':'application/json','x-csrf-token':csrf},body:'{}'}),env,{fetcher:async()=>json(removed)});
 assert.equal(r.status,200);
});

test('analysis and paper routes retain origin, method and paper-only boundaries',async()=>{
 const analysis={contract:'collection-v1',analysis:{categories:[{asset:'btc',saved_days:2,analyzed_days:1}],state:'working through saved data',requests_per_second:18}};
 const a=await proxyAuth(request('/api/collection/analysis'),env,{fetcher:async()=>json(analysis)});
 assert.equal(a.status,200);assert.deepEqual(await a.json(),analysis);
 const paper={contract:'paper-v1',live_trading_enabled:false,strategies:[],runs:[],datasets:[],entry_minutes:{btc:[15,10,5,3,1]}};
 assert.equal((await proxyAuth(request('/api/paper/workspace'),env,{fetcher:async()=>json(paper)})).status,200);
 assert.equal((await proxyAuth(request('/api/paper/workspace'),env,{fetcher:async()=>json({...paper,live_trading_enabled:true})})).status,502);
 const mustNotFetch=()=>assert.fail('must not forward');
 assert.equal((await proxyAuth(request('/api/paper/orders'),env,{fetcher:mustNotFetch})).status,404);
 assert.equal((await proxyAuth(request('/api/paper/strategies'),env,{fetcher:mustNotFetch})).status,405);
 assert.equal((await proxyAuth(request('/api/paper/replays',{method:'POST',headers:{origin:'https://evil.test','content-type':'application/json'},body:'{}'}),env,{fetcher:mustNotFetch})).status,403);
});

test('paper replay setup and cancellation use exact owner API routes',async()=>{
 const id='11111111-1111-4111-8111-111111111111',path='/api/paper/replays/'+id;
 let sent;
 const fetcher=async(url,options)=>{sent={url,...options};return json({contract:'paper-v1',live_trading_enabled:false,id,status:'cancelled'})};
 assert.equal((await proxyAuth(request(path),env,{fetcher})).status,200);
 assert.equal(sent.url,'https://api.test/paper/replays/'+id);
 assert.equal((await proxyAuth(request(path+'/cancel',{method:'POST',headers:{origin:env.APP_ORIGIN,'content-type':'application/json','x-csrf-token':csrf},body:'{}'}),env,{fetcher})).status,200);
 assert.equal(sent.method,'POST');assert.equal(sent.url,'https://api.test/paper/replays/'+id+'/cancel');
 assert.equal((await proxyAuth(request(path+'/cancel'),env,{fetcher:()=>assert.fail('must not fetch')})).status,405);
 assert.equal((await proxyAuth(request(path+'/cancel',{method:'POST',headers:{origin:'https://evil.test','content-type':'application/json'},body:'{}'}),env,{fetcher:()=>assert.fail('must not fetch')})).status,403);
});

test('live paper routes preserve exact methods, owner proxy, CSRF and event cursor bounds',async()=>{
 const id='11111111-1111-4111-8111-111111111111',base='/api/paper/live';let sent;
 const fetcher=async(url,options)=>{sent={url,...options};return json({contract:'paper-v1',live_trading_enabled:false,live_paper_enabled:true})};
 for(const path of [base,base+'/'+id,base+'/'+id+'/events?before=2']){
  assert.equal((await proxyAuth(request(path),env,{fetcher})).status,200);assert.equal(sent.method,'GET');
 }
 const headers={origin:env.APP_ORIGIN,'content-type':'application/json','x-csrf-token':csrf};
 for(const path of [base,base+'/'+id+'/stop']){
  assert.equal((await proxyAuth(request(path,{method:'POST',headers,body:'{}'}),env,{fetcher})).status,200);assert.equal(sent.method,'POST');
 }
 const no=()=>assert.fail('must not fetch');
 for(const path of [base+'?before=2',base+'/'+id+'/events?before=2&before=1',base+'/'+id+'/events?before=-1'])assert.equal((await proxyAuth(request(path),env,{fetcher:no})).status,422);
 assert.equal((await proxyAuth(request(base+'/'+id+'/stop'),env,{fetcher:no})).status,405);
 assert.equal((await proxyAuth(request(base,{method:'POST',headers:{...headers,origin:'https://evil.test'},body:'{}'}),env,{fetcher:no})).status,403);
 assert.equal((await proxyAuth(request(base+'/orders'),env,{fetcher:no})).status,404);
});

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
 assert.equal(config.workers_dev,false);assert.equal(config.preview_urls,false);
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

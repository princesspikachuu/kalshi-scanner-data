// Future staging gateway. This module is not imported by the live research Worker.
const ROUTES=new Map([
 ['/api/auth/challenge','GET'],['/api/auth/me','GET'],
 ['/api/auth/google','POST'],['/api/auth/logout','POST']
]);
const NAMES=new Set(['__Host-pocket_session','__Host-pocket_csrf','__Host-pocket_login','__Host-pocket_login_csrf']);
const STATIC=new Set(['/','/index.html','/login.mjs','/auth-client.mjs','/login.css','/collection.html','/collection.mjs','/collection-client.mjs','/collection.css','/research-client.mjs','/report-view.mjs']);
const BASE_HEADERS={'cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer'};
function problem(status,message){return new Response(JSON.stringify({detail:message}),{status,headers:{...BASE_HEADERS,'content-type':'application/json'}})}
function origin(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&u.pathname==='/'&&!u.search&&!u.hash?u.origin:null}catch{return null}}
function cookies(value){return String(value||'').split(';').map(s=>s.trim()).filter(s=>{
 const i=s.indexOf('=');return NAMES.has(s.slice(0,i))&&/^[A-Za-z0-9_-]{32,256}$/.test(s.slice(i+1));
}).join('; ')}
async function boundedBody(stream,max){
 if(!stream)return new Uint8Array();
 const reader=stream.getReader();const parts=[];let length=0;
 try{while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>max){await reader.cancel();throw new RangeError('body limit')}parts.push(value)}}finally{reader.releaseLock()}
 const body=new Uint8Array(length);let offset=0;for(const part of parts){body.set(part,offset);offset+=part.length}return body;
}
function successBody(path,data){
 if(path==='/api/auth/challenge'){
  if(typeof data.client_id!=='string'||!data.client_id||data.client_id.length>2048||
     !/^[A-Za-z0-9_-]{32,256}$/.test(data.nonce)||!/^[A-Za-z0-9_-]{32,256}$/.test(data.csrf_token)||
     !Number.isInteger(data.expires_in)||data.expires_in<1||data.expires_in>300)throw Error('invalid challenge');
  return {client_id:data.client_id,nonce:data.nonce,csrf_token:data.csrf_token,expires_in:data.expires_in};
 }
 if(data.authenticated!==true||typeof data.email!=='string'||data.email.length>320||!data.email.includes('@'))throw Error('invalid identity');
 return {authenticated:true,email:data.email};
}
function researchBody(path,data){
 const detail=/\/results\/[1-9][0-9]*$/.test(path);
 const keys=Object.keys(data).sort().join(',');
 if(data.contract!=='research-history-v1')throw Error('invalid research contract');
 if(detail){
  if(keys!=='contract,result,view'||!['historical','latest'].includes(data.view)||
     (typeof data.result?.id!=='string'||!/^[1-9][0-9]{0,18}$/.test(data.result.id))||!Array.isArray(data.result?.cells)||data.result.cells.length>45)throw Error('invalid result');
 }else if(keys!=='contract,items,next_cursor'||!Array.isArray(data.items)||data.items.length>50||
    data.items.some(item=>typeof item.id!=='string'||!/^[1-9][0-9]{0,18}$/.test(item.id))||
    (data.next_cursor!==null&&!/^[A-Za-z0-9_-]{1,1024}$/.test(data.next_cursor)))throw Error('invalid research page');
 return data; // Nested fields are validated by the API's closed, versioned response models.
}
function collectionBody(data){
 if(data.contract!=='collection-v1')throw Error('invalid collection');
 const keys=Object.keys(data).sort().join(',');
 if('items' in data){
  if(keys!=='contract,items,next_before'||!Array.isArray(data.items)||data.items.length>50||
     data.items.some(c=>!/^[-a-f0-9]{36}$/.test(c.id)||!['queued','running','succeeded','cancelled','failed'].includes(c.status))||
     (data.next_before!==null&&!/^[-a-f0-9]{36}$/.test(data.next_before)))throw Error('invalid campaign list');
 }else if(data.refresh){
  if(keys!=='contract,refresh'||typeof data.refresh.enabled!=='boolean'||data.refresh.interval_seconds!==3600)throw Error('invalid refresh');
 }else{
  if(!['campaign,contract','campaign,contract,next_after,sections'].includes(keys)||typeof data.campaign?.id!=='string'||
     !['queued','running','succeeded','cancelled','failed'].includes(data.campaign.status))throw Error('invalid campaign');
  if('sections' in data&&(!Array.isArray(data.sections)||data.sections.length>50||
     (data.next_after!==null&&!/^\d{4}-\d{2}-\d{2}$/.test(data.next_after))))throw Error('invalid sections');
 }
 return data;
}
function responseCookies(headers){
 const values=typeof headers.getSetCookie==='function'?headers.getSetCookie():headers.getAll('Set-Cookie');
 return values.filter(value=>{
  const name=value.slice(0,value.indexOf('='));if(!NAMES.has(name))return false;
  if(/;\s*domain\s*=/i.test(value)||!/;\s*secure(?:;|$)/i.test(value)||!/;\s*path=\/(?:;|$)/i.test(value)||!/;\s*samesite=strict(?:;|$)/i.test(value)||
     (name!=='__Host-pocket_csrf'&&!/;\s*httponly(?:;|$)/i.test(value)))throw Error('invalid cookie');
  return true;
 });
}
export async function proxyAuth(request,env,{fetcher=fetch,timeoutMs=8000}={}){
 const url=new URL(request.url);
 const research=/^\/api\/research\/(?:datasets|results(?:\/[1-9][0-9]{0,18}(?:\/datasets)?)?)$/.test(url.pathname);
 const uuid='[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}';
 const category='(?:btc|eth|crypto|weather|weather_daily|sports)';
 const campaignGet=new RegExp('^/api/collection/campaigns/'+uuid+'$').test(url.pathname);
 const collection=url.pathname==='/api/collection/campaigns'||campaignGet||
  new RegExp('^/api/collection/campaigns/'+uuid+'/(?:pause|resume)$').test(url.pathname)||
  new RegExp('^/api/collection/refresh/'+category+'$').test(url.pathname);
 const campaignList=url.pathname==='/api/collection/campaigns'&&request.method==='GET';
 const method=collection?((campaignGet||campaignList)?'GET':url.pathname.includes('/refresh/')&&request.method==='GET'?'GET':'POST'):research?'GET':ROUTES.get(url.pathname);
 if(!method)return problem(404,'Not found');
 if(request.method!==method){const r=problem(405,'Method not allowed');r.headers.set('allow',method);return r}
 if(collection){
  const entries=[...url.searchParams];
  if(campaignList){
   if(url.search.length>180||new Set(entries.map(([k])=>k)).size!==entries.length||
      entries.some(([k])=>!['asset','before','limit'].includes(k))||
      !new RegExp('^'+category+'$').test(url.searchParams.get('asset')||'')||
      (url.searchParams.has('before')&&!new RegExp('^'+uuid+'$').test(url.searchParams.get('before')))||
      (url.searchParams.has('limit')&&!/^(?:[1-9]|[1-4][0-9]|50)$/.test(url.searchParams.get('limit'))))return problem(400,'Invalid collection query');
  }else if(url.search.length>64||entries.length>(campaignGet?1:0)||entries.some(([k,v])=>k!=='after'||!/^\d{4}-\d{2}-\d{2}$/.test(v)))return problem(400,'Invalid collection query');
 }else if(research){
  const detail=/\/results\/[1-9][0-9]*$/.test(url.pathname);
  const allowed=new Set(detail?['stream','view']:['stream','cursor','limit']);
  const params=[...url.searchParams];
  if(url.search.length>2048||params.some(([k])=>!allowed.has(k))||new Set(params.map(([k])=>k)).size!==params.length||
     !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(url.searchParams.get('stream')||'')||
     (detail&&!['historical','latest'].includes(url.searchParams.get('view')))||
     (url.searchParams.has('limit')&&!/^(?:[1-9]|[1-4][0-9]|50)$/.test(url.searchParams.get('limit')))||
     (url.searchParams.has('cursor')&&!/^[A-Za-z0-9_-]{1,1024}$/.test(url.searchParams.get('cursor'))))return problem(400,'Invalid research query');
 }else if(url.search)return problem(400,'Query parameters are not accepted');
 const app=origin(env.APP_ORIGIN),api=origin(env.API_ORIGIN);
 if(!app||!api||app===api||typeof env.API_PROXY_SECRET!=='string'||env.API_PROXY_SECRET.length<32)return problem(503,'Sign-in connection is not configured');
 if(url.origin!==app||request.headers.get('sec-fetch-site')==='cross-site')return problem(403,'Request rejected');
 const supplied=request.headers.get('origin');
 if((method==='POST'&&supplied!==app)||(supplied!==null&&supplied!==app))return problem(403,'Request rejected');
 const headers=new Headers({'accept':'application/json','x-pocket-proxy':env.API_PROXY_SECRET});
 for(const name of ['origin','content-type','x-csrf-token','sec-fetch-site']){
  const value=request.headers.get(name);if(value!==null)headers.set(name,value);
 }
 const filtered=cookies(request.headers.get('cookie'));if(filtered)headers.set('cookie',filtered);
 let body;
 if(method==='POST'){
  if(!/^application\/json(?:\s*;|$)/i.test(headers.get('content-type')||''))return problem(415,'JSON required');
  if(Number(request.headers.get('content-length'))>20480)return problem(413,'Request too large');
  try{body=await boundedBody(request.body,20480)}catch{return problem(413,'Request too large')}
 }
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
 try{
  const upstream=await fetcher(api+url.pathname.slice(4)+url.search,{method,headers,body,redirect:'manual',signal:controller.signal,cache:'no-store'});
  if(upstream.status>=300&&upstream.status<400)return problem(502,'Sign-in connection unavailable');
  const outgoing=new Headers(BASE_HEADERS);
  const setCookies=(research||collection)?[]:responseCookies(upstream.headers);
  let response;
  if(!upstream.ok){
   const messages={400:'Invalid request',401:'Sign in required',403:'Request rejected',413:'Request too large',415:'JSON required',422:'Invalid sign-in request',429:'Too many requests. Try again shortly.',503:'Sign-in connection unavailable'};
   if(research||collection){messages[404]='Result not found';messages[409]='Request conflicts with an existing collection';messages[422]='Invalid request'}
   const status=Object.hasOwn(messages,upstream.status)?upstream.status:502;
   response=problem(status,messages[status]||'Sign-in connection unavailable');
   if(status===429)response.headers.set('retry-after','60');
   await upstream.body?.cancel();
  }else if(url.pathname==='/api/auth/logout'&&upstream.status===204){
   response=new Response(null,{status:204,headers:outgoing});
  }else{
   if(url.pathname==='/api/auth/logout')throw Error('invalid logout response');
   if(upstream.status!==200||!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type')||''))throw Error('invalid response');
   const text=new TextDecoder().decode(await boundedBody(upstream.body,(research||collection)?262144:32768));
   response=new Response(JSON.stringify(collection?collectionBody(JSON.parse(text)):research?researchBody(url.pathname,JSON.parse(text)):successBody(url.pathname,JSON.parse(text))),{status:200,headers:{...BASE_HEADERS,'content-type':'application/json'}});
  }
  for(const value of setCookies)response.headers.append('set-cookie',value);
  return response;
 }catch{return problem(controller.signal.aborted?504:502,'Sign-in connection unavailable')}
 finally{clearTimeout(timer)}
}
export default {
 async fetch(request,env){
  const url=new URL(request.url);
  if(url.pathname.startsWith('/api/'))return proxyAuth(request,env);
  if(!STATIC.has(url.pathname)||!['GET','HEAD'].includes(request.method))return problem(404,'Not found');
  const app=origin(env.APP_ORIGIN);if(app&&url.origin!==app)return problem(403,'Request rejected');
  if(!env.ASSETS)return problem(503,'Preview assets unavailable');
  const asset=await env.ASSETS.fetch(request);
  const response=new Response(asset.body,asset);
  for(const [name,value] of Object.entries(BASE_HEADERS))response.headers.set(name,value);
  response.headers.set('content-security-policy',"default-src 'none'; script-src 'self' https://accounts.google.com/gsi/client; style-src 'self' https://accounts.google.com/gsi/style; connect-src 'self' https://accounts.google.com/gsi/; frame-src https://accounts.google.com/gsi/; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'");
  response.headers.set('cross-origin-opener-policy','same-origin-allow-popups');
  response.headers.set('x-frame-options','DENY');
  response.headers.set('permissions-policy','camera=(), microphone=(), geolocation=()');
  return response;
 }
};

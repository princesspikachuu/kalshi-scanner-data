// Future staging gateway. This module is not imported by the live research Worker.
const ROUTES=new Map([
 ['/api/auth/challenge','GET'],['/api/auth/me','GET'],
 ['/api/auth/google','POST'],['/api/auth/logout','POST']
]);
const NAMES=new Set(['__Host-pocket_session','__Host-pocket_csrf','__Host-pocket_login','__Host-pocket_login_csrf']);
const STATIC=new Set(['/','/index.html','/login.mjs','/auth-client.mjs','/login.css']);
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
 const url=new URL(request.url),method=ROUTES.get(url.pathname);
 if(!method)return problem(404,'Not found');
 if(request.method!==method){const r=problem(405,'Method not allowed');r.headers.set('allow',method);return r}
 if(url.search)return problem(400,'Query parameters are not accepted');
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
  const upstream=await fetcher(api+url.pathname.slice(4),{method,headers,body,redirect:'manual',signal:controller.signal,cache:'no-store'});
  if(upstream.status>=300&&upstream.status<400)return problem(502,'Sign-in connection unavailable');
  const outgoing=new Headers(BASE_HEADERS);
  const setCookies=responseCookies(upstream.headers);
  let response;
  if(!upstream.ok){
   const messages={400:'Invalid request',401:'Sign in required',403:'Request rejected',413:'Request too large',415:'JSON required',422:'Invalid sign-in request',429:'Too many requests. Try again shortly.',503:'Sign-in connection unavailable'};
   const status=Object.hasOwn(messages,upstream.status)?upstream.status:502;
   response=problem(status,messages[status]||'Sign-in connection unavailable');
   if(status===429)response.headers.set('retry-after','60');
   await upstream.body?.cancel();
  }else if(url.pathname==='/api/auth/logout'&&upstream.status===204){
   response=new Response(null,{status:204,headers:outgoing});
  }else{
   if(url.pathname==='/api/auth/logout')throw Error('invalid logout response');
   if(upstream.status!==200||!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get('content-type')||''))throw Error('invalid response');
   const text=new TextDecoder().decode(await boundedBody(upstream.body,32768));
   response=new Response(JSON.stringify(successBody(url.pathname,JSON.parse(text))),{status:200,headers:{...BASE_HEADERS,'content-type':'application/json'}});
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

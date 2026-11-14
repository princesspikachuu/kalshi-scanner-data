// Shared browser client. Google credentials and challenge state stay in memory.
export class AuthError extends Error {constructor(message,status=0){super(message);this.name='AuthError';this.status=status}}
export function cookieValue(text,name){
 const item=String(text||'').split(';').map(v=>v.trim()).find(v=>v.startsWith(name+'='));
 return item?item.slice(name.length+1):null;
}
export function createAuthClient({fetcher=fetch,readCookie=()=>document.cookie}={}){
 async function call(path,{method='GET',body,csrf}={}){
  const headers={accept:'application/json'};if(body!==undefined)headers['content-type']='application/json';if(csrf)headers['x-csrf-token']=csrf;
  let response;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  try{response=await fetcher('/api/auth/'+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal})}
  catch{throw new AuthError('The sign-in connection is unavailable. Please try again.')}
  finally{clearTimeout(timer)}
  if(!response.ok){
   const message=response.status===401?'Your sign-in expired or this account is not allowed. Try again.':response.status===429?'Please wait a minute before trying again.':response.status===503?'The sign-in connection is not ready yet.':'Sign-in could not be completed. Please try again.';
   throw new AuthError(message,response.status);
  }
  if(response.status===204)return null;
  try{return await response.json()}catch{throw new AuthError('The sign-in connection returned an invalid response.')}
 }
 return {
  async current(){try{return await call('me')}catch(error){if(error.status===401)return null;throw error}},
  async challenge(){return call('challenge')},
  async signIn(credential,challenge){
   if(typeof credential!=='string'||!credential||!challenge?.nonce||!challenge?.csrf_token)throw new AuthError('Please start sign-in again.');
   return call('google',{method:'POST',body:{credential,nonce:challenge.nonce,csrf_token:challenge.csrf_token}});
  },
  async signOut(){
   const csrf=cookieValue(readCookie(),'__Host-pocket_csrf');
   if(!csrf)throw new AuthError('Please refresh to check your sign-in status.');
   try{return await call('logout',{method:'POST',body:{},csrf})}catch(error){if(error.status===401)return null;throw error}
  }
 };
}

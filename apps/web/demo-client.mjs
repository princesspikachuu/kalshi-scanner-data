import {cookieValue} from './auth-client.mjs';
export const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=value=>value===null||value===undefined?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100);
export async function demoCall(path,body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 const headers={accept:'application/json'};if(body!==undefined){headers['content-type']='application/json';headers['x-csrf-token']=cookieValue(document.cookie,'__Host-pocket_csrf')||''}
 try{
  const response=await fetch('/api/demo/'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal:controller.signal});
  if(response.status===401){location.replace('/');throw Error('Sign in to continue')}
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(typeof detail==='string'?detail:response.status===429?'Please wait before trying again.':'Unable to complete the request.')}
  const data=await response.json();if(data.contract!=='demo-v1')throw Error('Unexpected workspace response');return data;
 }finally{clearTimeout(timer)}
}

import {cookieValue} from './auth-client.mjs';
export function createCollectionClient({fetcher=fetch,readCookie=()=>document.cookie}={}){
 async function call(path,body){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  const headers={accept:'application/json'};
  if(body!==undefined){
   const csrf=cookieValue(readCookie(),'__Host-pocket_csrf');
   if(!csrf){clearTimeout(timer);throw Error('Sign in again before changing collection settings.')}
   headers['content-type']='application/json';headers['x-csrf-token']=csrf;
  }
  try{
   const response=await fetcher('/api/collection/'+path,{method:body===undefined?'GET':'POST',headers,
    body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',redirect:'error',cache:'no-store',signal:controller.signal});
   if(!response.ok){
    const error=Error(response.status===401?'Sign in to continue.':response.status===422?'Check the dates and try again.':response.status===429?'Please wait a minute before trying again.':'Collection is unavailable. Please retry.');
    error.status=response.status;throw error;
   }
   const data=await response.json();if(data.contract!=='collection-v1')throw Error('Collection response is unavailable.');return data;
  }catch(error){if(Number.isInteger(error.status))throw error;throw Error(controller.signal.aborted?'Collection update timed out. Saved progress is safe; retrying shortly.':'Collection connection unavailable. Saved progress is safe; please retry.')}finally{clearTimeout(timer)}
 }
 const asset=a=>{if(!['btc','eth','crypto','weather','weather_daily','sports'].includes(a))throw Error('Choose a category.');return a};
 const id=i=>{if(!/^[a-f0-9-]{36}$/.test(i))throw Error('Choose a collection.');return i};
 return {
  status:()=>call('status'),analysis:()=>call('analysis'),
  list:(a,before=null,group=null,limit=25)=>{
   if(group!==null&&!['unfinished','finished'].includes(group))throw Error('Invalid collection group.');
   if(!Number.isInteger(limit)||limit<1||limit>50)throw Error('Invalid collection page.');
   return call('campaigns?asset='+(a==='all'?'all':asset(a))+(before?'&before='+encodeURIComponent(id(before)):'')+(group?'&group='+group+'&limit='+limit:''));
  },
  create:(a,start_date,end_date,key,refresh_existing=false)=>call('campaigns',{asset:asset(a),start_date,end_date,request_key:key,refresh_existing}),
  get:(i,after=null)=>call('campaigns/'+id(i)+(after?'?after='+encodeURIComponent(after):'')),
  control:(i,action)=>{if(!['pause','resume','remove'].includes(action))throw Error('Invalid action.');return call('campaigns/'+id(i)+'/'+action,{})},
  refresh:a=>call('refresh/'+asset(a)),setRefresh:(a,enabled,local_time=undefined)=>call('refresh/'+asset(a),{enabled,...(local_time===undefined?{}:{local_time})})
 };
}

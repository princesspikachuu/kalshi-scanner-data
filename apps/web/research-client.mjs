// Saved-result reads only. No archive downloads, collection or policy computation.
export function createResearchClient({fetcher=fetch}={}){
 return {async result(campaign,id){
  if(!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(campaign)||!/^[1-9][0-9]{0,18}$/.test(id))throw Error('Choose a saved report.');
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  try{
   const stream='campaign-'+campaign.replaceAll('-','');
   const response=await fetcher('/api/research/results/'+id+'?stream='+stream+'&view=historical',{
    credentials:'same-origin',redirect:'error',cache:'no-store',headers:{accept:'application/json'},signal:controller.signal});
   if(!response.ok){const e=Error(response.status===401?'Sign in to view saved reports.':response.status===404?'This saved report was not found.':'Saved report unavailable. Please retry.');e.status=response.status;throw e}
   const data=await response.json();
   if(data.contract!=='research-history-v1'||data.view!=='historical'||data.result?.id!==id||!Array.isArray(data.result.cells)||data.result.cells.length>45)throw Error('Saved report unavailable.');
   return data.result;
  }finally{clearTimeout(timer)}
 }};
}

// Saved-result reads only. No archive downloads, collection or policy computation.
const ASSETS=['btc','eth','crypto','weather','weather_daily','sports'];
export function createResearchClient({fetcher=fetch}={}){
 const identifier=id=>{if(typeof id!=='string'||!/^[1-9][0-9]{0,18}$/.test(id))throw Error('Choose a saved report.');return id};
 const stream=value=>{if(!/^(?:campaign-[a-f0-9]{32}|category-(?:btc|eth|crypto|weather|weather_daily|sports))$/.test(value))throw Error('Choose a saved report.');return value};
 async function call(path){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  try{
   const response=await fetcher('/api/research/'+path,{credentials:'same-origin',redirect:'error',cache:'no-store',headers:{accept:'application/json'},signal:controller.signal});
   if(!response.ok){const e=Error(response.status===401?'Sign in to view saved reports.':response.status===404?'This saved report was not found.':'Saved report unavailable. Please retry.');e.status=response.status;throw e}
   const data=await response.json();if(data.contract!=='research-history-v1')throw Error('Saved report unavailable.');return data;
  }catch(error){if(Number.isInteger(error.status))throw error;throw Error('Saved report unavailable. Please retry.')}finally{clearTimeout(timer)}
 }
 async function resultInStream(source,id){
  const data=await call('results/'+identifier(id)+'?stream='+stream(source)+'&view=historical');
  if(data.view!=='historical'||data.result?.id!==id||!Array.isArray(data.result.cells)||data.result.cells.length>45)throw Error('Saved report unavailable.');
  return data.result;
 }
 function campaignStream(campaign){
  if(!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(campaign))throw Error('Choose a saved report.');
  return 'campaign-'+campaign.replaceAll('-','');
 }
 async function page(source,id,kind,cursor){
  if(!['datasets','coverage'].includes(kind))throw Error('Invalid saved source');
  if(cursor!==null&&!/^[A-Za-z0-9_-]{1,1024}$/.test(cursor))throw Error('Invalid saved source page');
  const data=await call('results/'+identifier(id)+'/'+kind+'?stream='+stream(source)+(cursor?'&cursor='+cursor:''));
  if(!Array.isArray(data.items)||data.items.length>50||(data.next_cursor!==null&&typeof data.next_cursor!=='string'))throw Error('Saved sources unavailable.');return data;
 }
 return {
  result:async(campaign,id)=>resultInStream(campaignStream(campaign),id),campaignStream,
  async category(asset){
   if(!ASSETS.includes(asset))throw Error('Choose a category.');
   const source='category-'+asset,data=await call('results?stream='+source+'&limit=1');
   if(!Array.isArray(data.items)||data.items.length>1)throw Error('Saved report unavailable.');
   if(!data.items.length)return null;
   return resultInStream(source,identifier(data.items[0].id));
  },
  sources:(source,id,cursor=null)=>page(source,id,'datasets',cursor),
  coverage:(source,id,cursor=null)=>page(source,id,'coverage',cursor)
 };
}

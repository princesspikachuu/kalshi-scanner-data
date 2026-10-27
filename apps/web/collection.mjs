import {createAuthClient} from './auth-client.mjs';
import {createCollectionClient} from './collection-client.mjs';
const $=id=>document.getElementById(id),client=createCollectionClient();
let timer,revision=0,selected=null,next=null,key=null,busy=false;
const prefs={};
try{Object.assign(prefs,JSON.parse(localStorage.getItem('pocket-collection-v1')||'{}'))}catch{}
const today=new Date().toISOString().slice(0,10);
$('asset').value=['btc','eth','crypto','weather','weather_daily','sports'].includes(prefs.asset)?prefs.asset:'btc';
for(const id of ['start','end']){$(id).max=today;$(id).value=/^\d{4}-\d{2}-\d{2}$/.test(prefs[id]||'')?prefs[id]:today}
$('recheck').checked=prefs.pending?.recheck===true;
key=prefs.pending?.asset===$('asset').value&&prefs.pending?.start===$('start').value&&prefs.pending?.end===$('end').value?prefs.pending.key:null;
function save(){try{localStorage.setItem('pocket-collection-v1',JSON.stringify({...prefs,asset:$('asset').value,start:$('start').value,end:$('end').value}))}catch{}}
function failure(error){$('notice').textContent=error.message;if(error.status===401){$('collection').hidden=true;clearTimeout(timer)}}
function render(data,append=false){
 const c=data.campaign;selected=c.id;$('progress').hidden=false;
 $('counts').textContent=`${c.completed_sections} of ${c.total_sections} sections collected · ${c.status==='cancelled'?'paused':c.completed_sections===c.total_sections&&c.status!=='succeeded'?'building combined report · '+c.status:c.status}`;
 $('range').textContent=`${c.start_at} through ${c.end_at} · ${c.mode==='rolling'?'rolling 24 hours':'date range'}${c.result_id?' · saved research report '+c.result_id:''}`;
 $('pause').hidden=!['queued','running'].includes(c.status);$('resume').hidden=!['failed','cancelled'].includes(c.status);
 if(!append)$('sections').replaceChildren();
 for(const s of data.sections||[]){const li=document.createElement('li');li.textContent=`${s.day} · ${s.stage}${s.dataset_id?' · saved version '+s.dataset_id:''}`;$('sections').append(li)}
 next=data.next_after;$('more').hidden=!next;
 if(c.status==='succeeded')$('notice').textContent='Collection complete. All sections and the combined research report are saved.';
 else if(c.status==='failed')$('notice').textContent='Collection stopped with an unresolved error. Resume retries unfinished work and retains saved pages.';
}
async function poll(version){
 if(!selected)return;
 try{const data=await client.get(selected);if(version!==revision)return;render(data);
  if(['queued','running'].includes(data.campaign.status))timer=setTimeout(()=>poll(version),5000);
 }catch(error){if(version!==revision)return;failure(error);if(error.status!==401)timer=setTimeout(()=>poll(version),15000)}
}
async function category(){
 clearTimeout(timer);const version=++revision;selected=prefs[$('asset').value]||null;key=prefs.pending?.asset===$('asset').value?prefs.pending.key:null;$('progress').hidden=true;save();
 try{const data=await client.refresh($('asset').value);if(version!==revision)return;
  if(!selected)selected=data.refresh.latest_campaign_id;
  $('automatic').checked=data.refresh.enabled;$('refreshStatus').textContent=data.refresh.enabled?'Hourly refresh enabled. Switching it off prevents future refreshes; a current run can finish.':'Automatic refresh is off.';
  await poll(version);
 }catch(error){if(version===revision)failure(error)}
}
$('asset').addEventListener('change',()=>category());
for(const id of ['start','end','recheck'])$(id).addEventListener('change',()=>{key=null;delete prefs.pending;save()});
$('collection').addEventListener('submit',async event=>{
 event.preventDefault();if(busy)return;busy=true;const version=++revision;clearTimeout(timer);$('begin').disabled=true;$('asset').disabled=true;
 // Retain the key on ambiguous network failure; changing dates/category creates a new request.
 key=key||crypto.randomUUID();prefs.pending={asset:$('asset').value,start:$('start').value,end:$('end').value,recheck:$('recheck').checked,key};save();
 $('start').disabled=true;$('end').disabled=true;$('recheck').disabled=true;
 try{const data=await client.create($('asset').value,$('start').value,$('end').value,key,$('recheck').checked);if(version!==revision)return;
  selected=data.campaign.id;prefs[$('asset').value]=selected;delete prefs.pending;save();key=null;$('notice').textContent='Collection queued. You can close this page; the background worker will continue.';await poll(version);
 }catch(error){failure(error)}finally{busy=false;$('begin').disabled=false;$('asset').disabled=false;$('start').disabled=false;$('end').disabled=false;$('recheck').disabled=false}
});
$('showAutomatic').addEventListener('click',async()=>{
 clearTimeout(timer);const version=++revision;
 try{const data=await client.refresh($('asset').value);if(version!==revision)return;
  selected=data.refresh.latest_campaign_id;
  if(selected)await poll(version);else $('notice').textContent='No automatic update has started yet. The background worker starts it after automatic refresh is enabled.';
 }catch(error){if(version===revision)failure(error)}
});
$('automatic').addEventListener('change',async()=>{
 const enabled=$('automatic').checked;$('automatic').disabled=true;
 try{await client.setRefresh($('asset').value,enabled);$('refreshStatus').textContent=enabled?'Hourly refresh enabled; the worker will collect a fresh 24-hour window.':'Automatic refresh is off. A current run can finish.'}
 catch(error){$('automatic').checked=!enabled;failure(error)}finally{$('automatic').disabled=false}
});
for(const action of ['pause','resume'])$(action).addEventListener('click',async()=>{
 if(!selected||busy)return;busy=true;$(action).disabled=true;clearTimeout(timer);const version=++revision;
 try{await client.control(selected,action);await poll(version)}catch(error){failure(error)}finally{busy=false;$(action).disabled=false}
});
$('more').addEventListener('click',async()=>{
 if(!next||!selected)return;const version=revision;$('more').disabled=true;clearTimeout(timer);
 try{const data=await client.get(selected,next);if(version===revision)render(data,true)}catch(error){failure(error)}finally{$('more').disabled=false}
});
window.addEventListener('pagehide',()=>{revision++;clearTimeout(timer)});
try{if(await createAuthClient().current()){$('collection').hidden=false;$('notice').textContent='Ready to collect.';await category()}else{$('notice').textContent='Sign in from the account page to start a collection.'}}catch(error){failure(error)}

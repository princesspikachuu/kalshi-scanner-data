import {createAuthClient} from './auth-client.mjs';
import {createCollectionClient} from './collection-client.mjs';
import {createResearchClient} from './research-client.mjs';
import {renderTable,reportCsv} from './report-view.mjs';
const $=id=>document.getElementById(id),client=createCollectionClient();
let timer,statusTimer,revision=0,selected=null,next=null,key=null,busy=false,historyNext=null,report=null,reportKey=null;
const research=createResearchClient(),auth=createAuthClient();
let reportContext=null,sourceNext=null,windowNext=null,sourcesLoaded=null,reportRequest=0;
const prefs={};
try{Object.assign(prefs,JSON.parse(localStorage.getItem('pocket-collection-v1')||'{}'))}catch{}
const today=new Date().toISOString().slice(0,10);
$('asset').value=['btc','eth','crypto','weather','weather_daily','sports'].includes(prefs.asset)?prefs.asset:'btc';
for(const id of ['start','end']){$(id).max=today;$(id).value=/^\d{4}-\d{2}-\d{2}$/.test(prefs[id]||'')?prefs[id]:today}
$('reportScope').value=prefs.reportScope==='category'?'category':'load';
$('reportScope').addEventListener('change',()=>{prefs.reportScope=$('reportScope').value;save();category()});
$('recheck').checked=prefs.pending?.recheck===true;
key=prefs.pending?.asset===$('asset').value&&prefs.pending?.start===$('start').value&&prefs.pending?.end===$('end').value?prefs.pending.key:null;
function save(){try{localStorage.setItem('pocket-collection-v1',JSON.stringify({...prefs,asset:$('asset').value,start:$('start').value,end:$('end').value}))}catch{}}
function failure(error){$('notice').textContent=error.message;if(error.status===401){$('workspace').hidden=true;$('signOut').hidden=true;$('signIn').hidden=false;clearTimeout(timer);clearTimeout(statusTimer)}}
for(const id of ['metric','minimum','loss']){
 if(id==='loss')$(id).checked=prefs.loss===true;
 else if([...$(id).options].some(o=>o.value===String(prefs[id])))$(id).value=prefs[id];
 $(id).addEventListener('change',()=>{prefs[id]=id==='loss'?$(id).checked:$(id).value;save();drawReport()});
}
async function workerStatus(){
 try{
  const data=await client.status(),online=data.worker.state==='online';
  $('workerTitle').textContent=online?'Worker online · collection enabled':'Waiting for background worker';
  $('workerMessage').textContent=online?'Saved requests are processed section by section, even after you close this page. No trades are placed.':'Requests stay safely queued. The worker has not checked in recently; saved progress is retained.';
 }catch(error){$('workerTitle').textContent='Worker status unavailable';$('workerMessage').textContent='Your saved work is retained. Refresh to retry.';if(error.status===401){failure(error);return}}
 if($('reportScope').value==='category')void loadCategory(revision);
 statusTimer=setTimeout(workerStatus,30000);
}
function clearReport(){report=null;reportKey=null;reportContext=null;reportRequest++;sourcesLoaded=null;sourceNext=null;windowNext=null;$('research').hidden=true;$('reportContent').hidden=true;$('cellDetail').hidden=true;$('exportCsv').hidden=true;$('provenance').open=false}
function showReport(data,context){
 report=data;reportContext=context;sourcesLoaded=null;sourceNext=null;windowNext=null;$('provenance').open=false;
 $('sourceList').replaceChildren();$('windowList').replaceChildren();$('sourcesMore').hidden=true;$('windowsMore').hidden=true;
 $('reportStamp').textContent=($('reportScope').value==='category'?'All saved history':'This load')+(data.collection_complete===false?' · In progress':'')+' · Saved '+new Date(data.published_at).toLocaleString();
 $('candidates').textContent=data.summary.candidate_count===null?'Unknown':data.summary.candidate_count.toLocaleString();
 $('observations').textContent=data.summary.observation_count.toLocaleString();
 $('reportDates').textContent=data.summary.first_date?data.summary.first_date+' – '+data.summary.last_date:'No eligible observations';
 $('scopeNote').textContent=$('reportScope').value==='category'?'Saved candle-complete sections combined, with the newest source version selected once for each covered close time.':data.collection_complete===false?`${data.reported_sections} of ${data.total_sections} sections available. Remaining sections and trade details continue collecting; the table updates automatically.`:'All sections in this collection are combined.';
 $('reportStatus').textContent=data.cells.length?'Full sample · '+data.cells.length+' saved time/price cells.':'No eligible observations. No result has been invented.';
 $('research').hidden=false;$('reportContent').hidden=false;$('exportCsv').hidden=false;drawReport();
}
async function loadCategory(version){
 const ticket=++reportRequest;
 if(!report){$('research').hidden=false;$('reportContent').hidden=true;$('reportStatus').textContent='Loading precomputed category history…'}
 try{
  const data=await research.category($('asset').value);if(version!==revision||ticket!==reportRequest||$('reportScope').value!=='category')return;
  if(!data){clearReport();$('research').hidden=false;$('reportStatus').textContent='No saved category report yet. Completed candle sections will appear as collection progresses.';return}
  if(reportContext?.stream==='category-'+$('asset').value&&reportContext.id===data.id)return;
  showReport(data,{stream:'category-'+$('asset').value,id:data.id});
 }catch(error){if(version===revision&&ticket===reportRequest){$('reportStatus').textContent=error.message;failure(error)}}
}
async function loadSources(kind,append=false){
 const context=reportContext,version=revision;if(!context)return;
 const sources=kind==='sources',target=$(sources?'sourceList':'windowList'),status=$(sources?'sourcesStatus':'windowsStatus'),more=$(sources?'sourcesMore':'windowsMore');
 status.textContent='Loading saved '+(sources?'source versions':'coverage windows')+'…';more.disabled=true;
 try{
  const data=await (sources?research.sources:research.coverage)(context.stream,context.id,append?(sources?sourceNext:windowNext):null);
  if(context!==reportContext||version!==revision)return;
  if(!append)target.replaceChildren();
  for(const item of data.items){const li=document.createElement('li');
   if(sources){const summary=item.summary;li.textContent=item.day+' · source #'+item.id+' · '+(summary?`${summary.candidate_count} candidates · candles ${summary.candidates_with_candles}/${summary.candidate_count} · trades ${summary.candidates_with_trades}/${summary.candidate_count} · unavailable scopes ${summary.scope_states.unavailable}`:'Coverage unavailable');li.title=item.fingerprint}
   else li.textContent=item.start_at+' → '+item.end_at+' · source #'+item.dataset_id;
   target.append(li);
  }
  if(sources)sourceNext=data.next_cursor;else windowNext=data.next_cursor;
  more.hidden=!data.next_cursor;status.textContent=target.children.length?'Saved immutable '+(sources?'source versions.':'close-time coverage. Gaps remain explicit.'):(sources?'No source versions available.':'This load uses its frozen requested range; close-time overlays apply to cumulative history.');
 }catch(error){if(context===reportContext&&version===revision){status.textContent=error.message;failure(error)}}finally{more.disabled=false}
}
$('provenance').addEventListener('toggle',()=>{if($('provenance').open&&reportContext&&sourcesLoaded!==reportContext){sourcesLoaded=reportContext;void loadSources('sources');void loadSources('windows')}});
$('sourcesMore').addEventListener('click',()=>loadSources('sources',true));
$('windowsMore').addEventListener('click',()=>loadSources('windows',true));
$('exportCsv').addEventListener('click',()=>{if(!report)return;const url=URL.createObjectURL(new Blob([reportCsv(report)],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='pocket-'+$('asset').value+'-report-'+report.id+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});

function drawReport(){
 if(!report)return;$('cellDetail').hidden=true;
 renderTable($('table'),report,{loss:$('loss').checked,metric:$('metric').value,minimum:Number($('minimum').value)},(cell,minutes,band)=>{
  const row=$('loss').checked?cell.loss_prevention:cell.hold,p=cell.loss_prevention,doc=document;
  const heading=doc.createElement('h3');heading.textContent=`${minutes} minutes before close · ${band}¢`;
  const lines=[`Full original sample: ${cell.hold.sampled_markets} observations across ${cell.hold.sampled_days} days.`,
   `Wins: ${row.wins} · Win rate: ${row.win_rate_percent.toFixed(2)}%`,
   `Average P/L: ${row.average_profit_loss_cents_per_contract.toFixed(2)}¢ · ROI: ${row.hypothetical_roi_percent.toFixed(2)}%`,
   `Exit coverage: ${p.exit_coverage} of ${cell.hold.sampled_markets} · Early exits: ${p.early_exits}`,
   $('loss').checked?p.sell_label:'Hold to settlement · loss prevention is off'];
  $('cellDetail').replaceChildren(heading,...lines.map(text=>{const p=doc.createElement('p');p.textContent=text;return p}));
  $('cellDetail').hidden=false;$('cellDetail').focus({preventScroll:true});
 });
}
async function loadReport(campaign,version){
 if(!campaign.result_id){clearReport();return}
 const identity=version+'/'+campaign.id+'/'+campaign.result_id;if(reportKey===identity)return;
 reportKey=identity;report=null;$('research').hidden=false;$('reportContent').hidden=true;$('reportStatus').textContent='Loading saved report…';
 try{
  const data=await research.result(campaign.id,campaign.result_id);if(version!==revision||reportKey!==identity)return;
  showReport(data,{stream:research.campaignStream(campaign.id),id:campaign.result_id});
 }catch(error){if(version===revision){reportKey=null;$('reportStatus').textContent=error.message;failure(error)}}
}
async function loadHistory(version,append=false){
 $('historyStatus').textContent='Loading saved collections…';
 try{
  const data=await client.list($('asset').value,append?historyNext:null);if(version!==revision)return [];
  if(!append)$('history').replaceChildren();
  for(const c of data.items){
   const button=document.createElement('button');button.type='button';button.dataset.campaign=c.id;button.setAttribute('aria-pressed',String(c.id===selected));
   const title=document.createElement('strong');title.textContent=c.start_at.slice(0,10)+' – '+c.end_at.slice(0,10);
   const subtitle=document.createElement('small');subtitle.textContent=`${c.mode==='rolling'?'24-hour update':'Date range'} · ${c.status==='cancelled'?'paused':c.status} · ${c.completed_sections}/${c.total_sections} sections${c.result_id?' · report saved':''}`;
   button.append(title,subtitle);button.addEventListener('click',()=>selectCampaign(c.id));$('history').append(button);
  }
  historyNext=data.next_before;$('historyMore').hidden=!historyNext;
  $('historyStatus').textContent=$('history').children.length?'Newest collections first.':'No collections saved for this category yet. Save a date range to begin.';
  return data.items;
 }catch(error){if(version===revision){$('historyStatus').textContent='Could not load saved collections. Use Refresh saved work to retry.';failure(error)}return []}
}
async function selectCampaign(id){
 $('reportScope').value='load';prefs.reportScope='load';
 clearTimeout(timer);const version=++revision;selected=id;prefs[$('asset').value]=id;save();clearReport();
 for(const button of $('history').children)button.setAttribute('aria-pressed',String(button.dataset.campaign===id));
 await poll(version);
}
$('historyMore').addEventListener('click',async()=>{$('historyMore').disabled=true;try{await loadHistory(revision,true)}finally{$('historyMore').disabled=false}});
$('reload').addEventListener('click',()=>category());
$('signOut').addEventListener('click',async()=>{$('signOut').disabled=true;try{await auth.signOut();window.location.replace('/')}catch(error){failure(error);$('signOut').disabled=false}});

function render(data,append=false){
 const c=data.campaign;selected=c.id;$('progress').hidden=false;
 $('workCounts').textContent=`${c.saved_pages||0} pages saved · ${c.completed_work_items||0}/${c.work_items||0} collection tasks finished${c.retry_at?' · retry after '+new Date(c.retry_at).toLocaleTimeString():''}${c.last_work_error?' · last issue: '+c.last_work_error.replaceAll('_',' '):''}`;
 $('completion').max=c.total_sections;$('completion').value=c.completed_sections;if($('reportScope').value==='load')void loadReport(c,revision);
 $('counts').textContent=`${c.completed_sections} of ${c.total_sections} sections fully collected${c.reported_sections?' · '+c.reported_sections+' sections available in the table':''} · ${c.status==='cancelled'?'paused':c.completed_sections===c.total_sections&&c.status!=='succeeded'?'building combined report · '+c.status:c.status}`;
 $('range').textContent=`${c.start_at} through ${c.end_at} · ${c.mode==='rolling'?'rolling 24 hours':'date range'}${c.result_id?' · saved research report '+c.result_id:''}`;
 $('pause').hidden=!['queued','running'].includes(c.status);$('resume').hidden=!['failed','cancelled'].includes(c.status);
 if(!append)$('sections').replaceChildren();
 for(const s of data.sections||[]){const li=document.createElement('li');li.textContent=`${s.day} · ${s.stage}${s.dataset_id?' · saved version '+s.dataset_id:''}`;$('sections').append(li)}
 next=data.next_after;$('more').hidden=!next;
 if(c.status==='succeeded')$('notice').textContent='Collection complete. All sections and the combined research report are saved.';
 else if(['queued','running'].includes(c.status))$('notice').textContent='Collection in progress. Saved pages are retained across retries and restarts.';
 else if(c.status==='failed')$('notice').textContent='Collection stopped with an unresolved error. Resume retries unfinished work and retains saved pages.';
}
async function poll(version){
 if(!selected)return;
 try{const data=await client.get(selected);if(version!==revision)return;render(data);
  if(['queued','running'].includes(data.campaign.status))timer=setTimeout(()=>poll(version),5000);
 }catch(error){if(version!==revision)return;failure(error);if(error.status!==401)timer=setTimeout(()=>poll(version),15000)}
}
async function category(){
 clearTimeout(timer);const version=++revision;selected=prefs[$('asset').value]||null;clearReport();historyNext=null;key=prefs.pending?.asset===$('asset').value?prefs.pending.key:null;$('progress').hidden=true;save();
 try{const [data,items]=await Promise.all([client.refresh($('asset').value),loadHistory(version)]);if(version!==revision)return;
  if(!selected)selected=items[0]?.id||data.refresh.latest_campaign_id;
  for(const button of $('history').children)button.setAttribute('aria-pressed',String(button.dataset.campaign===selected));
  $('automatic').checked=data.refresh.enabled;$('refreshStatus').textContent=data.refresh.enabled?'Hourly refresh enabled. Switching it off prevents future refreshes; a current run can finish.':'Automatic refresh is off.';
  await poll(version);if($('reportScope').value==='category')await loadCategory(version);
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
  selected=data.campaign.id;prefs[$('asset').value]=selected;delete prefs.pending;save();key=null;$('notice').textContent='Collection queued. The worker continues from saved checkpoints when you leave this page.';await loadHistory(version);await poll(version);
 }catch(error){failure(error)}finally{busy=false;$('begin').disabled=false;$('asset').disabled=false;$('start').disabled=false;$('end').disabled=false;$('recheck').disabled=false}
});
$('showAutomatic').addEventListener('click',async()=>{
 clearTimeout(timer);const version=++revision;
 try{const data=await client.refresh($('asset').value);if(version!==revision)return;
  if(data.refresh.latest_campaign_id)await selectCampaign(data.refresh.latest_campaign_id);
  else{selected=null;clearReport();$('progress').hidden=true;$('notice').textContent='No automatic update has started yet. It will start when the worker and automatic refresh are enabled.'}
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
 try{const data=await client.get(selected,next);if(version===revision)render(data,true)}catch(error){failure(error)}finally{$('more').disabled=false;if(version===revision)timer=setTimeout(()=>poll(version),5000)}
});
window.addEventListener('pagehide',()=>{revision++;clearTimeout(timer);clearTimeout(statusTimer)});
try{if(await auth.current()){$('workspace').hidden=false;$('signOut').hidden=false;$('collection').hidden=false;$('notice').textContent='Choose a date range or open a saved collection.';await Promise.all([category(),workerStatus()])}else{$('signIn').hidden=false;$('notice').textContent='Sign in to open your research workspace.'}}catch(error){failure(error)}

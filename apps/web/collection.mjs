import {createAuthClient} from './auth-client.mjs';
import {createCollectionClient} from './collection-client.mjs';
import {createResearchClient} from './research-client.mjs';
import {renderTable,reportCsv} from './report-view.mjs';
import {openBetOverlay} from './bet-overlay.mjs';
let choosingBet=false,betSelections=new Map();
const betKey=(minutes,band)=>`${minutes}:${band}`;
function betSelectionStatus(){
 const count=betSelections.size;
 document.getElementById('betHint').textContent=choosingBet?`${count} squares selected. Tap squares to add/remove, then choose Configure selected bets.`:'Choose New bet, then tap one or more statistics squares.';
 document.getElementById('betConfigure').hidden=!choosingBet||!count;
 document.getElementById('betClear').hidden=!choosingBet||!count;
}
document.getElementById('newBet').addEventListener('click',()=>{choosingBet=!choosingBet;document.getElementById('newBet').setAttribute('aria-pressed',String(choosingBet));betSelectionStatus();drawReport()});
document.getElementById('betConfigure').addEventListener('click',()=>openBetOverlay([...betSelections.values()]));
document.getElementById('betClear').addEventListener('click',()=>{betSelections.clear();betSelectionStatus();drawReport()});
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
 // A different collection may finish while this page polls a selected run.
 // Refresh active/finished queue membership without resetting selection.
 if(!$('workspace').hidden)void loadHistory(revision);
 statusTimer=setTimeout(workerStatus,30000);
}
function clearReport(){betSelections.clear();betSelectionStatus();report=null;reportKey=null;reportContext=null;reportRequest++;sourcesLoaded=null;sourceNext=null;windowNext=null;$('research').hidden=true;$('reportContent').hidden=true;$('cellDetail').hidden=true;$('exportCsv').hidden=true;$('provenance').open=false}
function showReport(data,context){
 report=data;reportContext=context;sourcesLoaded=null;sourceNext=null;windowNext=null;$('provenance').open=false;
 $('sourceList').replaceChildren();$('windowList').replaceChildren();$('sourcesMore').hidden=true;$('windowsMore').hidden=true;
 $('reportStamp').textContent=(data.sampled_preview?`${data.sample_limit}-market preview`:$('reportScope').value==='category'?'All saved history':'This load')+(data.collection_complete===false?' · In progress':'')+' · Saved '+new Date(data.published_at).toLocaleString();
 $('candidates').textContent=data.summary.candidate_count===null?'Unknown':data.summary.candidate_count.toLocaleString();
 $('observations').textContent=data.summary.observation_count.toLocaleString();
 $('reportDates').textContent=data.summary.first_date?data.summary.first_date+' – '+data.summary.last_date:'No eligible observations';
 $('scopeNote').textContent=data.sampled_preview?`Preliminary stratified sample: at most ${data.sample_limit} markets per date, across ${data.reported_sections} of ${data.total_sections} dates. The full market collection continues and its verified reports update separately.`:$('reportScope').value==='category'?'Saved candle-complete sections combined, with the newest source version selected once for each covered close time.':data.collection_complete===false?`${data.reported_sections} of ${data.total_sections} date windows included. Remaining sections and trade details continue collecting; the table updates automatically.`:'All sections in this collection are combined.';
 $('reportStatus').textContent=data.cells.length?(data.sampled_preview?'Preliminary sample':'Full sample')+' · '+data.cells.length+' saved time/price cells.':data.summary.candidate_count===0?`No settled candidate markets in the ${data.reported_sections??'saved'} processed date windows (${data.summary.first_date} – ${data.summary.last_date}).${data.collection_complete===false?' Remaining dates are still collecting.':''}`:'Markets were found, but no quotes met the entry rules in the available sections. Check source coverage for missing candles.';
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
$('exportCsv').addEventListener('click',()=>{if(!report)return;const url=URL.createObjectURL(new Blob([reportCsv(report)],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='pocket-'+$('asset').value+(report.sampled_preview?'-sample-preview':'-report')+'-'+report.id+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});

function drawReport(){
 if(!report)return;$('cellDetail').hidden=true;
 renderTable($('table'),report,{loss:$('loss').checked,metric:$('metric').value,minimum:Number($('minimum').value)},(cell,minutes,band)=>{
  if(choosingBet){const k=betKey(minutes,band);if(betSelections.has(k))betSelections.delete(k);else betSelections.set(k,{report,cell,minutes,band});betSelectionStatus();drawReport();return}
  const row=$('loss').checked?cell.loss_prevention:cell.hold,p=cell.loss_prevention,doc=document;
  const heading=doc.createElement('h3');heading.textContent=`${minutes} minutes before close · ${band}¢`;
  const lines=[`${report.sampled_preview?'Preliminary sampled cohort':'Full original sample'}: ${cell.hold.sampled_markets} observations across ${cell.hold.sampled_days} days.`,
   `Wins: ${row.wins} · Win rate: ${row.win_rate_percent.toFixed(2)}%`,
   `Average P/L: ${row.average_profit_loss_cents_per_contract.toFixed(2)}¢ · ROI: ${row.hypothetical_roi_percent.toFixed(2)}%`,
   `Exit coverage: ${p.exit_coverage} of ${cell.hold.sampled_markets} · Early exits: ${p.early_exits}`,
   $('loss').checked?p.sell_label:'Hold to settlement · loss prevention is off'];
  $('cellDetail').replaceChildren(heading,...lines.map(text=>{const p=doc.createElement('p');p.textContent=text;return p}));
  $('cellDetail').hidden=false;$('cellDetail').focus({preventScroll:true});
 });
}
async function loadReport(campaign,version){
 const sampled=campaign.sample_result_id&&campaign.sample_reported_sections>campaign.reported_sections;
 const identifier=sampled?campaign.sample_result_id:campaign.result_id;
 if(!identifier){clearReport();return}
 const identity=version+'/'+campaign.id+'/'+identifier+'/'+(sampled?'sample':'full');if(reportKey===identity)return;
 reportKey=identity;report=null;$('research').hidden=false;$('reportContent').hidden=true;$('reportStatus').textContent='Loading saved report…';
 try{
  const data=await (sampled?research.sampleResult:research.result)(campaign.id,identifier);if(version!==revision||reportKey!==identity)return;
  showReport(data,{stream:sampled?research.campaignSampleStream(campaign.id):research.campaignStream(campaign.id),id:identifier});
 }catch(error){if(version===revision){reportKey=null;$('reportStatus').textContent=error.message;failure(error)}}
}
const queuePages={unfinished:{next:null,total:0},finished:{next:null,total:0}};
async function loadHistory(version,append=false,group=null){
 if(group===null){const pages=await Promise.all(['unfinished','finished'].map(g=>loadHistory(version,append,g)));return pages.flat()}
 const state=queuePages[group],unfinished=group==='unfinished';
 const target=$(unfinished?'history':'finished'),status=$(unfinished?'historyStatus':'finishedStatus'),more=$(unfinished?'historyMore':'finishedMore');
 status.textContent='Loading saved collections…';
 try{
  const remaining=unfinished?5:Math.min(5,100-target.children.length);
  if(append&&remaining<=0)return [];
  const data=await client.list('all',append?state.next:null,group,append?remaining:5);if(version!==revision)return [];
  if(!append)target.replaceChildren();
  const existing=new Set([...target.children].map(b=>b.dataset.campaign));
  for(const c of data.items){
   if(existing.has(c.id))continue;existing.add(c.id);
   const button=document.createElement('button');button.type='button';button.dataset.campaign=c.id;button.setAttribute('aria-pressed',String(c.id===selected));
   const title=document.createElement('strong');title.textContent=({btc:'Bitcoin',eth:'Ethereum',crypto:'All crypto',weather:'Hourly temperature',weather_daily:'Daily weather',sports:'Sports'}[c.asset]||c.asset)+' · '+c.start_at.slice(0,10)+' – '+c.end_at.slice(0,10);
   const subtitle=document.createElement('small');subtitle.textContent=`${c.mode==='rolling'?'24-hour update':'Date range'} · ${c.status==='cancelled'?'paused':c.status} · ${c.completed_sections}/${c.total_sections} days collected${c.result_id?' · report saved':''}`;
   button.append(title,subtitle);button.addEventListener('click',async()=>{if($('asset').value!==c.asset){$('asset').value=c.asset;prefs[c.asset]=c.id;await category()}else await selectCampaign(c.id)});
   if(unfinished){const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='Remove from queue';remove.setAttribute('aria-label','Remove '+title.textContent+' from queue');remove.addEventListener('click',async()=>{remove.disabled=true;try{await client.control(c.id,'remove');await category();$('notice').textContent='Removed from queue. Saved data and history are retained.'}catch(error){failure(error);remove.disabled=false}});const entry=document.createElement('div');entry.className='queue-entry';entry.dataset.campaign=c.id;entry.append(button,remove);target.append(entry)}else target.append(button)
  }
  state.next=data.next_before;state.total=data.total??target.children.length;
  more.hidden=!state.next||(!unfinished&&target.children.length>=100);
  status.textContent=unfinished?`Showing ${target.children.length}/${state.total} in queue · oldest first. Includes paused and failed collections.`:`Showing ${target.children.length}/${state.total} finished · newest finishes first. Up to 100 recent finishes.`;
  return data.items;
 }catch(error){if(version===revision){status.textContent='Could not load saved collections. Use Refresh saved work to retry.';failure(error)}return []}
}
function markSelected(){for(const target of ['history','finished'])for(const item of $(target).children){const button=item.className==='queue-entry'?item.children[0]:item;button.setAttribute('aria-pressed',String(button.dataset.campaign===selected))}}

async function selectCampaign(id){
 $('reportScope').value='load';prefs.reportScope='load';
 clearTimeout(timer);const version=++revision;selected=id;prefs[$('asset').value]=id;save();clearReport();
 markSelected();
 await poll(version);
}
for(const [id,group] of [['historyMore','unfinished'],['finishedMore','finished']])$(id).addEventListener('click',async()=>{$(id).disabled=true;try{await loadHistory(revision,true,group)}finally{$(id).disabled=false}});
$('reload').addEventListener('click',()=>category());
$('signOut').addEventListener('click',async()=>{$('signOut').disabled=true;try{await auth.signOut();window.location.replace('/')}catch(error){failure(error);$('signOut').disabled=false}});

function render(data,append=false){
 const c=data.campaign;selected=c.id;$('progress').hidden=false;
 $('workCounts').textContent=`${c.saved_pages||0} pages saved · ${c.completed_work_items||0}/${c.work_items||0} collection tasks finished${c.retry_at?' · retry after '+new Date(c.retry_at).toLocaleTimeString():''}${c.last_work_error?' · last recorded issue: '+c.last_work_error.replaceAll('_',' '):''}`;
 $('completion').max=c.total_sections;$('completion').value=c.completed_sections||0;if($('reportScope').value==='load')void loadReport(c,revision);
 $('counts').textContent=`${c.completed_sections||0} of ${c.total_sections} days collected · ${c.reported_sections||0} days reported · ${c.analyzed_sections||0} days analyzed · ${c.status==='cancelled'?'paused':c.status==='succeeded'?'collected — analyzing in background':c.status}`;
 $('range').textContent=`${c.start_at} through ${c.end_at} · ${c.mode==='rolling'?'rolling 24 hours':'date range'}${c.result_id?' · saved research report '+c.result_id:''}`;
 $('pause').hidden=!['queued','running'].includes(c.status);$('resume').hidden=!['failed','cancelled'].includes(c.status);
 if(!append)$('sections').replaceChildren();
 for(const s of data.sections||[]){const li=document.createElement('li');li.textContent=`${s.day} · ${s.stage}${s.dataset_id?' · saved version '+s.dataset_id:''}`;$('sections').append(li)}
 next=data.next_after;$('more').hidden=!next;
 if(c.status==='succeeded'){$('notice').textContent='Collection complete. All requested raw data is saved. Reports and analysis continue while workers are idle.';void loadHistory(revision)}
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
  if(!selected)selected=items.find(c=>c.asset===$('asset').value)?.id||data.refresh.latest_campaign_id;
  markSelected();
  showRefresh(data.refresh);
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
function showRefresh(refresh){
 $('automatic').checked=refresh.enabled;$('refreshTime').value=refresh.local_time||'03:00';
 $('refreshStatus').textContent=refresh.enabled?`Daily reconciliation at ${refresh.local_time||'03:00'} Pacific · preceding 24 hours${refresh.next_due?' · next '+new Date(refresh.next_due).toLocaleString():''}. A current run can finish.`:'Daily reconciliation is off. A current run can finish.';
}
$('saveRefreshTime').addEventListener('click',async()=>{
 const button=$('saveRefreshTime');button.disabled=true;
 try{const data=await client.setRefresh($('asset').value,$('automatic').checked,$('refreshTime').value);showRefresh(data.refresh)}catch(error){failure(error)}finally{button.disabled=false}
});
$('automatic').addEventListener('change',async()=>{
 const enabled=$('automatic').checked;$('automatic').disabled=true;
 try{const data=await client.setRefresh($('asset').value,enabled);showRefresh(data.refresh)}
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

async function showAnalysisProgress(){
 try{const {analysis}=await client.analysis();const row=analysis.categories.find(r=>r.asset===$('asset').value);
  $('analysisProgress').textContent=`Analysis: ${row?.analyzed_days||0} of ${row?.saved_days||0} saved days · ${analysis.state}`;
 }catch{$('analysisProgress').textContent='Analysis progress unavailable; saved data is retained.'}
}
void showAnalysisProgress();const analysisTimer=setInterval(showAnalysisProgress,15000);analysisTimer?.unref?.();

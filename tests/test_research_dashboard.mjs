import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {tableModel,renderTable} from '../apps/web/report-view.mjs';
import {createResearchClient} from '../apps/web/research-client.mjs';

const id='11111111-1111-4111-8111-111111111111';
function fixture(){
 const hold={asset:'btc',minutes_before_close:15,price_band_cents:'80-90',sampled_markets:10,wins:5,win_rate_percent:50,average_purchase_price_cents:85,average_profit_loss_cents_per_contract:-35,hypothetical_roi_percent:-41.18,sampled_days:2};
 return {id:'9007199254740993',published_at:'2026-10-27T10:00:00Z',entry_minutes:[15,10],price_bands:['80-90','90-100'],summary:{candidate_count:10,observation_count:10,first_date:'2026-10-25',last_date:'2026-10-26'},cells:[{hold,loss_prevention:{...hold,average_profit_loss_cents_per_contract:-20,hypothetical_roi_percent:-23.53,exit_coverage:3,early_exits:2,sell_label:'Sell ≤ 70¢',trade_not_recommended:false,threshold_cents:70}}]};
}
test('loss toggle uses saved metrics and retains original denominator and exact 50% label',()=>{
 const report=fixture(),before=JSON.stringify(report);
 const hold=tableModel(report)[0].cells[0],loss=tableModel(report,{loss:true})[0].cells[0];
 assert.equal(hold.value,-35);assert.equal(loss.value,-20);assert.equal(hold.n,10);assert.equal(loss.n,10);assert.equal(loss.label,'Sell ≤ 70¢');
 assert.equal(tableModel(report,{loss:true,metric:'roi'})[0].cells[0].value,-23.53);
 assert.equal(tableModel(report,{loss:true,minimum:20})[0].cells[0].n,10);
 assert.equal(tableModel(report,{loss:true,minimum:20})[0].cells[0].hidden,true);
 assert.equal(JSON.stringify(report),before);assert.equal(tableModel(report)[1].cells[0].empty,true);
 report.cells[0].loss_prevention.sell_label='Trade not recommended';
 assert.equal(tableModel(report,{loss:true})[0].cells[0].label,'Trade not recommended');
});
test('empty cohorts stay empty and IDs stay exact strings in saved-report reads',async()=>{
 const report=fixture();report.cells=[];assert.ok(tableModel(report).every(row=>row.cells.every(c=>c.empty)));
 let sent;const client=createResearchClient({fetcher:async(url,options)=>{sent={url,...options};return Response.json({contract:'research-history-v1',view:'historical',result:report})}});
 assert.equal((await client.result(id,report.id)).id,'9007199254740993');
 assert.equal(sent.url,'/api/research/results/9007199254740993?stream=campaign-11111111111141118111111111111111&view=historical');
 assert.equal(sent.credentials,'same-origin');assert.equal(sent.redirect,'error');assert.equal(sent.body,undefined);
 const invalid=createResearchClient({fetcher:()=>assert.fail('must not fetch')});await assert.rejects(invalid.result('bad','1'));
});
test('saved-report errors never reveal server diagnostics or accept wrong result identity',async()=>{
 for(const status of [401,404,503]){
  const client=createResearchClient({fetcher:async()=>Response.json({detail:'private-sentinel'},{status})});
  await assert.rejects(client.result(id,'1'),e=>e.status===status&&!e.message.includes('sentinel'));
 }
 const wrong=createResearchClient({fetcher:async()=>Response.json({contract:'research-history-v1',view:'historical',result:fixture()})});
 await assert.rejects(wrong.result(id,'1'),/unavailable/);
});

class Element{
 constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.listeners={};this.dataset={};this.attributes={};this.hidden=false;this.value='';this.checked=false;this.disabled=false;this._text=''}
 set textContent(t){this._text=String(t);this.children=[]}get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ')}
 append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this._text='';this.children=nodes}
 setAttribute(k,v){this.attributes[k]=v}addEventListener(k,v){this.listeners[k]=v}focus(){}
 async fire(type){return this.listeners[type]?.({preventDefault(){},currentTarget:this})}
}
function documentFixture(){
 const nodes={},doc={cookie:'__Host-pocket_csrf='+'c'.repeat(43),getElementById:id=>{assert.ok(nodes[id],'Missing HTML node '+id);return nodes[id]},createElement:tag=>new Element(tag,doc)};
 const html=fs.readFileSync('apps/web/collection.html','utf8');
 for(const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
  const e=nodes[match[3]]=doc.createElement(match[1]);e.hidden=/\bhidden\b/.test(match[2]);
 }
 for(const [id,values] of Object.entries({metric:['pnl','roi','win'],minimum:['1','5','10','20','30']})){
  nodes[id].options=values.map(value=>({value}));nodes[id].value=values[0];
 }
 return {doc,nodes};
}
test('table DOM renders text safely and cell selection retains full-cohort coverage',async()=>{
 const {doc}=documentFixture(),target=doc.createElement('div'),report=fixture();let chosen;
 report.cells[0].loss_prevention.sell_label='<img src=x onerror=alert(1)>';
 renderTable(target,report,{loss:true},cell=>chosen=cell);
 assert.equal(target.children[0].tagName,'table');
 const button=target.children[0].children[1].children[0].children[1].children[0];
 assert.match(button.textContent,/n = 10/);assert.match(button.textContent,/<img/);
 assert.equal(button.children.at(-1).tagName,'small');await button.fire('click');
 assert.equal(chosen.hold.sampled_markets,10);assert.equal(chosen.loss_prevention.exit_coverage,3);
});
test('signed-in workspace displays progressive reports and restores category/display choices',async()=>{
 const {doc,nodes}=documentFixture(),previous={document:globalThis.document,window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
 let saved=JSON.stringify({asset:'eth',metric:'roi',minimum:'1',loss:true});const events={},requests=[];
 const campaign={id,asset:'eth',status:'running',mode:'backfill',start_at:'2026-10-25T00:00:00Z',end_at:'2026-10-27T00:00:00Z',result_id:fixture().id,completed_sections:0,total_sections:2};
 try{
  globalThis.document=doc;globalThis.window={addEventListener:(name,fn)=>events[name]=fn,location:{replace:url=>requests.push(url)}};
  globalThis.localStorage={getItem:()=>saved,setItem:(key,value)=>saved=value};
  globalThis.fetch=async(url,options)=>{
   requests.push(url);assert.equal(options.credentials,'same-origin');
   if(url==='/api/auth/me')return Response.json({authenticated:true,email:'owner@example.test'});
   if(url==='/api/collection/status')return Response.json({contract:'collection-v1',worker:{state:'online',last_seen:'2026-10-27T19:00:00Z',heartbeat_ttl_seconds:90}});
   if(url.includes('/refresh/'))return Response.json({contract:'collection-v1',refresh:{enabled:false,latest_campaign_id:null}});
   if(url.includes('campaigns?asset='))return Response.json({contract:'collection-v1',items:[campaign],next_before:null});
   if(url.includes('/campaigns/'+id))return Response.json({contract:'collection-v1',campaign,sections:[],next_after:null});
   if(url.includes('/research/results/'))return Response.json({contract:'research-history-v1',view:'historical',result:{...fixture(),collection_complete:false,reported_sections:1,total_sections:2}});
   throw Error('Unexpected request');
  };
  await import('../apps/web/collection.mjs?workspace-test');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes.workspace.hidden,false);assert.equal(nodes.signOut.hidden,false);assert.equal(nodes.asset.value,'eth');
  assert.equal(nodes.metric.value,'roi');assert.equal(nodes.loss.checked,true);assert.equal(nodes.history.children.length,1);
  assert.equal(nodes.reportContent.hidden,false);assert.equal(nodes.candidates.textContent,'10');assert.equal(nodes.completion.value,0);assert.equal(nodes.workerTitle.textContent,'Worker online · collection enabled');
  assert.match(nodes.table.textContent,/-23.53%/);assert.match(nodes.scopeNote.textContent,/1 of 2 sections available/);assert.match(nodes.reportStamp.textContent,/In progress/);
  nodes.metric.value='win';await nodes.metric.fire('change');assert.equal(JSON.parse(saved).metric,'win');
  assert.ok(!saved.includes('owner@example.test'));assert.ok(!saved.includes('__Host-pocket'));
  assert.ok(requests.every(url=>!url.includes('/auth/google')));
 }finally{events.pagehide?.();Object.assign(globalThis,previous)}
});
test('signed-out workspace exposes a sign-in link and fetches no private history',async()=>{
 const {doc,nodes}=documentFixture(),previous={document:globalThis.document,window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};const events={};
 try{
  globalThis.document=doc;globalThis.window={addEventListener:(name,fn)=>events[name]=fn};globalThis.localStorage={getItem:()=>null,setItem(){}};
  globalThis.fetch=async(url)=>{assert.equal(url,'/api/auth/me');return new Response(null,{status:401})};
  await import('../apps/web/collection.mjs?signed-out-test');
  assert.equal(nodes.workspace.hidden,true);assert.equal(nodes.signIn.hidden,false);
 }finally{events.pagehide?.();Object.assign(globalThis,previous)}
});

test('cumulative reports and paginated sources stay same-origin and retain string IDs',async()=>{
 const requests=[],report=fixture();
 const client=createResearchClient({fetcher:async(url,options)=>{
  requests.push(url);assert.equal(options.credentials,'same-origin');assert.equal(options.body,undefined);
  if(url.includes('results?'))return Response.json({contract:'research-history-v1',items:[{id:report.id}],next_cursor:null});
  if(url.includes('/datasets?')||url.includes('/coverage?'))return Response.json({contract:'research-history-v1',items:[],next_cursor:null});
  return Response.json({contract:'research-history-v1',view:'historical',result:report});
 }});
 assert.equal((await client.category('btc')).id,report.id);
 await client.sources('category-btc',report.id,'opaque_cursor');await client.coverage('category-btc',report.id);
 assert.equal(requests[0],'/api/research/results?stream=category-btc&limit=1');
 assert.match(requests[1],/stream=category-btc&view=historical$/);assert.match(requests[2],/datasets.*cursor=opaque_cursor$/);
 const blocked=createResearchClient({fetcher:()=>assert.fail('must not fetch')});await assert.rejects(blocked.category('arbitrary'));
 await assert.rejects(blocked.sources('https://evil.test','1'));await assert.rejects(blocked.coverage('category-btc','1','!'));
});
test('full report CSV preserves every cell and both original denominators regardless of display minimum',async()=>{
 const {reportCsv}=await import('../apps/web/report-view.mjs'),report=fixture();
 const csv=reportCsv(report),lines=csv.trim().split('\r\n');
 assert.equal(lines.length,3);assert.match(lines[1],/"hold","10","2"/);assert.match(lines[2],/"loss_prevention","10","2"/);
 assert.match(csv,/9007199254740993/);assert.match(lines[2],/Sell ≤ 70¢/);
 tableModel(report,{minimum:100});assert.equal(reportCsv(report),csv);
});

test('transport errors do not expose browser or connection diagnostics',async()=>{
 const {createCollectionClient}=await import('../apps/web/collection-client.mjs');
 const fetcher=async()=>{throw Error('private-sentinel signal is aborted without reason')};
 await assert.rejects(createCollectionClient({fetcher}).status(),e=>!e.message.includes('sentinel')&&/Saved progress is safe/.test(e.message));
 await assert.rejects(createResearchClient({fetcher}).category('btc'),e=>!e.message.includes('sentinel')&&/unavailable/i.test(e.message));
});

test('all-category queue expands independently, labels categories, removes safely and caps recent finishes',async()=>{
 const {doc,nodes}=documentFixture(),previous={document:globalThis.document,window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};const events={};
 const make=(i,status)=>({id:`11111111-1111-4111-8111-${String(i).padStart(12,'0')}`,asset:i%2?'btc':'weather',status,mode:'backfill',start_at:'2026-01-01',end_at:'2026-02-01',result_id:null,total_sections:32,completed_sections:status==='succeeded'?32:1});
 let pending=Array.from({length:7},(_,i)=>make(i+1,'queued')),finished=Array.from({length:105},(_,i)=>make(i+101,'succeeded'));const calls=[];
 try{
  globalThis.document=doc;globalThis.window={addEventListener:(n,f)=>events[n]=f};globalThis.localStorage={getItem:()=>null,setItem(){}};
  globalThis.fetch=async(url,options)=>{
   calls.push({url,options});
   if(url==='/api/auth/me')return Response.json({authenticated:true,email:'owner@example.test'});
   if(url.includes('/status'))return Response.json({contract:'collection-v1',worker:{state:'online'}});
   if(url.includes('/refresh/'))return Response.json({contract:'collection-v1',refresh:{enabled:true,local_time:'03:00',interval_seconds:86400,next_due:'2026-10-28T10:00:00Z'}});
   if(url.includes('campaigns?')){
    const q=new URL(url,'https://app.test').searchParams;assert.equal(q.get('asset'),'all');
    const rows=q.get('group')==='unfinished'?pending:finished,start=q.has('before')?rows.findIndex(c=>c.id===q.get('before'))+1:0;
    const items=rows.slice(start,start+Number(q.get('limit')));
    return Response.json({contract:'collection-v1',items,total:rows.length,next_before:start+items.length<rows.length?items.at(-1).id:null});
   }
   if(url.endsWith('/remove')){const identifier=url.split('/').at(-2);pending=pending.filter(c=>c.id!==identifier);return Response.json({contract:'collection-v1',campaign:{id:identifier,status:'cancelled'}})}
   const campaign=[...pending,...finished].find(c=>url.includes(c.id));
   if(campaign)return Response.json({contract:'collection-v1',campaign,sections:[]});
   throw Error('Unexpected request '+url);
  };
  await import('../apps/web/collection.mjs?all-queue');await new Promise(r=>setImmediate(r));
  assert.match(nodes.historyStatus.textContent,/Showing 5\/7 in queue/);assert.match(nodes.history.textContent,/Hourly weather/);assert.match(nodes.history.textContent,/Bitcoin/);
  await nodes.historyMore.fire('click');assert.equal(nodes.history.children.length,7);assert.equal(nodes.historyMore.hidden,true);
  assert.equal(nodes.finished.children.length,5);
  for(let i=0;i<19;i++)await nodes.finishedMore.fire('click');
  assert.equal(nodes.finished.children.length,100);assert.equal(nodes.finishedMore.hidden,true);assert.match(nodes.finishedStatus.textContent,/100\/105/);
  await nodes.history.children[0].children[1].fire('click');assert.equal(pending.length,6);assert.match(nodes.historyStatus.textContent,/5\/6/);
  assert.match(nodes.refreshStatus.textContent,/Daily reconciliation at 03:00 Pacific/);
  nodes.refreshTime.value='04:30';await nodes.saveRefreshTime.fire('click');
  assert.ok(calls.some(c=>c.options.body&&JSON.parse(c.options.body).local_time==='04:30'));
 }finally{events.pagehide?.();Object.assign(globalThis,previous)}
});

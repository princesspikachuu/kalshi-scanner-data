import {accountSummary} from './live-paper-view.mjs';
import {paperCall} from './paper-client.mjs';
const $=id=>document.getElementById(id),money=c=>'$'+((c??0)/100).toFixed(2);
let selected=null,key=null,busy=false,loading=false,timer=null,delay=10000,before=null,hasOlder=false;
const time=t=>t?new Date(t*1000).toLocaleString():'not yet';
const line=(parent,text)=>{const p=document.createElement('p');p.textContent=text;parent.append(p);return p};

function table(id,headings,rows){
 const root=$(id);root.replaceChildren();
 if(!rows.length){root.textContent='None yet.';return}
 const t=document.createElement('table'),thead=document.createElement('thead'),tr=document.createElement('tr'),body=document.createElement('tbody');
 for(const h of headings){const th=document.createElement('th');th.textContent=h;tr.append(th)}thead.append(tr);
 for(const row of rows){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}body.append(tr)}
 t.append(thead,body);const wrap=document.createElement('div');wrap.style.overflowX='auto';wrap.append(t);root.append(wrap);
}
function showEvents(events,append=false){
 if(!append)$('liveEvents').replaceChildren();
 for(const e of events){line($('liveEvents'),`${time(e.time)} · ${e.kind.replaceAll('_',' ')}${e.order_id?' · '+e.order_id:''}${e.ticker?' · '+e.ticker:''}${e.side?' · '+e.side.toUpperCase():''}${e.bid_cents!=null?' · bid '+e.bid_cents+'¢':''}${e.sale_cents!=null?' · sale '+e.sale_cents+'¢':''}${e.contracts!=null?' · '+e.contracts+' contracts':''}${e.remaining!=null?' · '+e.remaining+' remaining':''}${e.profit_loss_cents!=null?' · P/L '+money(e.profit_loss_cents):''}${e.reason?' · '+e.reason:''}${e.evidence?' · '+e.evidence:''}`)}
}
function render(session){
 const s=session.state,summary=accountSummary(session),root=$('liveSummary');root.replaceChildren();
 line(root,`${session.name} · ${summary.label}`);
 line(root,`${money(s.cash)} available · ${money(summary.reserved)} reserved in bids · ${money(summary.cost)} invested at cost · ${money(s.realized_pnl)} realized P/L before fees`);
 line(root,`${s.orders_placed??0} bids placed · ${s.filled_contracts??0} contracts filled · ${session.watched_markets} watched markets · last saved ${time(s.updated_at)}`);
 if(summary.stale&&['queued','running'].includes(session.status))line(root,'Worker update is overdue. New entries require a connected feed and a fresh market quote; saved positions remain in the database.');
 line(root,`Feed: ${s.feed}. Last market message ${time(s.last_message_at)}. ${s.gaps??0} recorded feed gaps · ${s.provider_reads??0} discovery requests this worker lifetime · ${s.reconnects??0} reconnects.`);
 if(s.discovery_note)line(root,s.discovery_note);
 if(s.capacity_limited)line(root,'Capacity protection is active. The app limits the watched market set or new bids to keep this account within its memory and subscription bounds.');
 $('stopLive').disabled=!['queued','running'].includes(session.status)||s.stopping;
 table('liveOrders',['Order','Market','Side','Bid','Remaining / ordered','Expires'],(s.orders||[]).map(o=>[o.id,o.ticker,o.side,o.bid+'¢',o.remaining+' / '+o.quantity,time(o.expires)]));
 table('livePositions',['Order','Market','Side','Contracts','Cost','Loss prevention'],(s.positions||[]).map(p=>[p.id,p.ticker,p.side,p.quantity,money(p.cost),p.stop==null?'Off':p.stop+'¢ trigger']));
 const setup=$('liveConfiguration');setup.replaceChildren();
 line(setup,`Started with ${money(session.configuration.starting_cash_cents)} · ${session.configuration.fill_model} fills · account ID ${session.id}`);
 for(const st of session.configuration.strategies)line(setup,`${st.name} · ${st.asset} · ask ${st.min_price}–${st.max_price}¢ · ${st.entry_minute_min}< minutes remaining ≤${st.entry_minute_max} · ${st.bid_reference??'ask'} adjustment ${st.bid_adjustment_cents??-st.below_ask_cents}¢ · maximum ${st.maximum_bid_cents==null?'none':st.maximum_bid_cents+'¢'} · ${st.contracts} contracts · ${st.balance_percent}% of balance · loss prevention ${st.loss_trigger_cents==null?'off':st.loss_trigger_cents+'¢'}`);
 if(!hasOlder){showEvents([...(s.recent||[])].reverse());before=s.recent?.[0]?.sequence??null;$('olderLive').disabled=!before}
}
async function refresh(){
 if(loading||document.hidden)return;loading=true;
 try{
  const workspace=await paperCall('live'),checked=new Set([...$('liveStrategies').querySelectorAll('input:checked')].map(x=>x.value));
  $('liveStrategies').replaceChildren(...workspace.strategies.map(({id,strategy:s})=>{const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.value=id;input.checked=checked.has(id);const text=document.createElement('span');text.textContent=`${s.name} · ${s.asset} · saved reference yield ${s.statistical_yield_percent.toFixed(2)}%`;label.append(input,text);return label}));
  if(!workspace.strategies.length)$('liveStrategies').textContent='Save a bet from a statistics square first.';
  const sessions=workspace.sessions;selected=selected&&sessions.some(s=>s.id===selected)?selected:sessions[0]?.id;
  $('liveSessions').replaceChildren(...sessions.map(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.name+' · '+s.status;o.selected=s.id===selected;return o}));
  $('startLive').disabled=busy||sessions.some(s=>['queued','running'].includes(s.status));
  if(selected)render((await paperCall('live/'+selected)).session);
  const health=workspace.worker,age=health?Date.now()/1000-health.updated_at:Infinity;
  $('liveStatus').textContent=age>45?'Live worker heartbeat is overdue or has not started. Saved accounts and positions are retained.':'Live paper worker ready · simulated money only';
  delay=10000;
 }catch(e){$('liveStatus').textContent=e.message;delay=Math.min(60000,delay*2)}
 finally{loading=false;clearTimeout(timer);timer=setTimeout(refresh,delay)}
}
$('startLive').addEventListener('click',async()=>{
 if(busy)return;busy=true;let started=false;$('startLive').disabled=true;
 try{const strategy_ids=[...$('liveStrategies').querySelectorAll('input:checked')].map(x=>x.value);if(!strategy_ids.length)throw Error('Choose at least one saved strategy.');key??=crypto.randomUUID();
  const response=await paperCall('live',{name:$('liveName').value.trim()||'Live paper account',strategy_ids,starting_cash_cents:Math.round(Number($('liveCash').value)*100),fill_model:$('liveFill').value,request_key:key});selected=response.id;key=null;hasOlder=false;started=true;await refresh();
 }catch(e){$('liveStatus').textContent=e.message}finally{busy=false;if(!started)$('startLive').disabled=false}
});
$('stopLive').addEventListener('click',async()=>{if(!selected||busy)return;busy=true;$('stopLive').disabled=true;try{await paperCall('live/'+selected+'/stop',{});await refresh()}catch(e){$('liveStatus').textContent=e.message}finally{busy=false}});
$('olderLive').addEventListener('click',async()=>{if(!selected||!before)return;$('olderLive').disabled=true;try{const result=await paperCall('live/'+selected+'/events?before='+before);hasOlder=true;showEvents(result.events,true);before=result.next_before;$('olderLive').disabled=!before}catch(e){$('liveStatus').textContent=e.message}});
$('liveSessions').addEventListener('change',()=>{selected=$('liveSessions').value;hasOlder=false;void refresh()});
$('refreshLive').addEventListener('click',()=>{hasOlder=false;void refresh()});
for(const id of ['liveStrategies','liveCash','liveFill','liveName'])$(id).addEventListener('change',()=>{key=null});
document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)void refresh()});
void refresh();

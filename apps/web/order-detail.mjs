import {demoCall,escapeHTML as e,money,marketPhase,orderDetailButton,transactionBadge,marketLink} from './demo-client.mjs';

const qty=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(n||0);
const date=n=>n?new Date(typeof n==='number'?n*1000:n).toLocaleString():'Not recorded';
const states={resting:'Working',held:'Buy filled',closed:'Closed',rejected:'Rejected',intent:'Submitting',uncertain:'Awaiting confirmation',cancel_pending:'Cancellation awaiting confirmation'};
export function orderDetailMarkup(data,now=Date.now()/1000){
 const ended=marketPhase(data.entry,{},now)==='ended';
 const buy=data.entry,held=buy.status==='closed'?0:Math.max(0,(buy.filled||0)-(buy.sold||0)),exits=data.exits||[];
 const row=(o,label)=>`<tr ${o.client_id===data.selected?'aria-current="true"':''}><td><strong>${e(label)}</strong><br>${e(ended&&!['closed','rejected'].includes(o.status)?'Market ended · historical record':states[o.status]||o.status)}<br><span class="small">${e(date(o.created_at))}</span></td><td>${e(o.price)}¢<br><span class="small">${e(o.side?.toUpperCase())}</span></td><td>${qty(o.quantity)} ordered<br>${qty(o.filled)} filled<br>${qty(o.remaining)} remaining</td><td><span class="small">${e(o.exchange_id||'Exchange confirmation pending')}<br>${e(o.client_id)}</span></td></tr>`;
 let message='';
 if(ended)message='Market closed. Any unresolved contracts are awaiting settlement or confirmation; the orders below are history, not active trading orders.';
 else if(!exits.length){
  message=buy.status==='rejected'?'This buy was rejected; no sell order was created.':!buy.filled?'Waiting for the buy to fill. A sell can be created after a confirmed fill.':buy.status==='closed'?'This buy is closed without a linked sell. Check activity for settlement, offset, or reset details.':buy.exit_triggered?'Protection triggered; waiting for a verified sell order.':'No sell order has been submitted yet. The bot’s exit rules remain active.';
 }
 const table=rows=>`<div class="scroll" tabindex="0"><table class="activity-table"><thead><tr><th>Order / state</th><th>Limit</th><th>Contracts</th><th>Order identifiers</th></tr></thead><tbody>${rows}</tbody></table></div>`;
 return `${data.settlement?transactionBadge(data.settlement):''}${ended?`<p class="small" role="status">${e(message)}</p>`:''}<p><strong>${marketLink(buy.ticker)}</strong> · ${e(buy.side?.toUpperCase())}</p><p class="small">${qty(held)} contracts ${ended?'pending settlement / confirmation':'still held'} · ${qty(buy.sold)} closed or offset${Number.isFinite(buy.offset_quantity)?` · ${qty(buy.offset_quantity)} offset against opposite-side fills`:''}${Number.isFinite(buy.realized_cents)?` · estimated realized net ${money(buy.realized_cents)}`:''}</p><h3>Original buy</h3>${table(row(buy,'Buy · ENTRY'))}<h3>Linked sells · ${exits.length}${data.limited?'+':''}</h3>${exits.length?table(exits.map(o=>row(o,o.exit_role==='profit'?'Profit SELL · EXIT':'Protective SELL · EXIT')).join('')):`<p class="small" role="status">${e(message)}</p>`}<p class="small">Each sell belongs to this exact buy. Partially filled, canceled, replaced, and rejected sells stay visible. Quantities come from the paper ledger. Fills are estimates from production trade evidence and conservative queue assumptions. Last saved ${e(date(data.saved_at))}.${data.limited?' The latest 100 sells are shown, with active orders first.':''}</p><a class="button secondary" href="/activity?${e(new URLSearchParams({bot:buy.bot,ticker:buy.ticker}))}">View this bot’s market activity</a>`;
}

let dialog,selected,version=0,timer;
export async function openOrderDetail(identifier){
 if(!orderDetailButton(identifier))return;
 clearTimeout(timer);selected=identifier;const token=++version;
 if(!dialog){
  dialog=document.createElement('dialog');dialog.className='order-detail';dialog.setAttribute('aria-labelledby','orderDetailTitle');
  dialog.innerHTML='<div class="dialog-head"><h2 id="orderDetailTitle">Buy &amp; linked sells</h2><div class="row"><button type="button" data-detail-refresh>Refresh</button><button type="button" data-detail-close>Close</button></div></div><div class="dialog-body" data-detail-content></div>';
  document.body.append(dialog);dialog.querySelector('[data-detail-close]').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{version++;clearTimeout(timer);selected=null});
  dialog.querySelector('[data-detail-refresh]').onclick=()=>openOrderDetail(selected);
 }
 if(!dialog.open)dialog.showModal();
 const content=dialog.querySelector('[data-detail-content]'),button=dialog.querySelector('[data-detail-refresh]');
 content.textContent='Loading this buy and its linked sell orders…';button.disabled=true;
 async function refresh(){
  if(token!==version||!dialog.open)return;
  if(document.hidden){timer=setTimeout(refresh,15000);return}
  button.disabled=true;
  try{
   const data=await demoCall('orders?'+new URLSearchParams({client_id:identifier}));
   if(token!==version||!dialog.open)return;
   content.innerHTML=orderDetailMarkup(data);
  }catch(error){if(token===version&&dialog.open)content.textContent=error.message}
  finally{if(token===version&&dialog.open){button.disabled=false;timer=setTimeout(refresh,15000)}}
 }
 await refresh();
}
if(typeof document!=='undefined')document.addEventListener('click',event=>{
 const button=event.target.closest?.('[data-order-detail]');if(!button)return;
 event.preventDefault();openOrderDetail(button.dataset.orderDetail);
});

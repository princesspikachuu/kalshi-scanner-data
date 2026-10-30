import {paperCall,squareStrategy} from './paper-client.mjs';
export function openBetOverlay(selections){
 if(!selections?.length)return;
 const [{report,cell,minutes,band}]=selections;
 const $=id=>document.getElementById(id),dialog=$('betDialog');
 let context={report,cell,minutes,band};
 $('betSquare').textContent=selections.length===1?`${report.asset} · ${band}¢ ask · ${Math.max(0,...report.entry_minutes.filter(m=>m<minutes))}–${minutes} minutes before close`:`${selections.length} selected price/time squares · ${report.asset}`;
 $('betStats').textContent=`Reference BID-grid ROI ${cell.hold.hypothetical_roi_percent.toFixed(2)}% (not a paper-trading forecast) · bid-grid win rate ${cell.hold.win_rate_percent.toFixed(2)}% · ${cell.hold.sampled_markets} observations across ${cell.hold.sampled_days} days. Statistics use historical bid prices; new entry eligibility uses the current ask.`;
 $('betName').value=selections.length===1?`${report.asset} ${band}¢ / ${minutes} min`:`${report.asset} selection`;
 $('betMaximum').value='';$('betReference').value='ask';$('betAdjustment').value='-1';$('betContracts').value='1';$('betPercent').value='10';
 $('betStop').value='';$('betStopEnabled').checked=false;
 $('betMessage').textContent='Paper only. Unfilled orders expire at the end of their game or market period. Each event is capped at 10%, including other strategies and pending bids.';
 const preview=()=>{
  const basis=$('betReference').value,adjustment=Number($('betAdjustment').value);
  const maximum=$('betMaximum').value,stop=$('betStopEnabled').checked?$('betStop').value:null;
  const adjustmentLabel=$('betAdjustment').value===''?'…':adjustment===0?'at':adjustment<0?`${Math.abs(adjustment)}¢ below`:`${adjustment}¢ above`;
  const referenceLabel=basis==='best_bid'?'current best bid':'current ask';
  $('betPreview').textContent=`Bid ${adjustmentLabel==='at'?'at':adjustmentLabel} ${referenceLabel}${maximum!==''?`, capped at ${maximum}¢`:''}. Ask-price band and entry window still decide when to place a bid. Orders crossing the ask or below 1¢ will be skipped to preserve maker-only behavior. Up to ${$('betContracts').value} contracts, using up to ${$('betPercent').value}% of the shared balance. ${stop!==null?`Sell when the available bid reaches ${stop||'…'}¢ or lower, at the available price.`:'Hold filled positions to settlement.'}`;
  $('betStop').disabled=!$('betStopEnabled').checked;
 };
 $('betReference').onchange=()=>{$('betAdjustment').value=$('betReference').value==='best_bid'?'0':'-1';preview()};
 for(const id of ['betMaximum','betAdjustment','betContracts','betPercent','betStop','betStopEnabled'])$(id).oninput=preview;
 $('betClose').onclick=()=>dialog.close();
 $('betForm').onsubmit=async event=>{
  event.preventDefault();if(!$('betForm').reportValidity())return;
  const button=$('betSave');button.disabled=true;
  try{
   if($('betStopEnabled').checked&&$('betStop').value==='')throw Error('Enter a loss-prevention trigger price.');
   if($('betAdjustment').value==='')throw Error('Enter a maker bid price adjustment.');
   if($('betReference').value==='ask'&&Number($('betAdjustment').value)>=0)
    throw Error('Ask-based maker bids must be below the ask. Choose a negative price adjustment.');
   const settings={
    name:$('betName').value.trim(),bid_reference:$('betReference').value,bid_adjustment_cents:Number($('betAdjustment').value),maximum_bid_cents:$('betMaximum').value===''?null:Number($('betMaximum').value),
    contracts:Number($('betContracts').value),balance_percent:Number($('betPercent').value),starting_cash_cents:10000,
    loss_trigger_cents:$('betStopEnabled').checked?Number($('betStop').value):null};
   const rules=selections.map(item=>squareStrategy(item.report,item.cell,item.minutes,item.band,{}));
   if(new Set(rules.map(r=>r.asset)).size!==1)throw Error('Choose squares from one category per strategy.');
   const first=rules[0];
   await paperCall('strategies',{...settings,...first,name:settings.name,minutes:[first.entry_minute_max],
      rules:rules.map(r=>({report_id:r.report_id,entry_minute_min:r.entry_minute_min,
        entry_minute_max:r.entry_minute_max,min_price:r.min_price,max_price:r.max_price}))});
   $('betMessage').textContent='Saved one strategy with '+rules.length+' selected square(s). It is available for both live paper and historical replays.';
  }catch(error){$('betMessage').textContent=error.message}finally{button.disabled=false}
 };
 preview();dialog.showModal();
}

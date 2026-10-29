import {paperCall,squareStrategy} from './paper-client.mjs';
export function openBetOverlay(report,cell,minutes,band){
 const $=id=>document.getElementById(id),dialog=$('betDialog');
 let context={report,cell,minutes,band};
 $('betSquare').textContent=`${report.asset} · ${band}¢ ask · ${Math.max(0,...report.entry_minutes.filter(m=>m<minutes))}–${minutes} minutes before close`;
 $('betStats').textContent=`Saved ROI ${cell.hold.hypothetical_roi_percent.toFixed(2)}% · win rate ${cell.hold.win_rate_percent.toFixed(2)}% · ${cell.hold.sampled_markets} observations across ${cell.hold.sampled_days} days. Statistics use historical bid prices; new entry eligibility uses the current ask.`;
 $('betName').value=`${report.asset} ${band}¢ / ${minutes} min`;
 $('betMaximum').value='';$('betDistance').value='1';$('betContracts').value='1';$('betPercent').value='10';
 $('betStop').value='';$('betStopEnabled').checked=false;
 $('betMessage').textContent='Paper only. Unfilled orders expire at the end of their game or market period. Each event is capped at 10%, including other strategies and pending bids.';
 const preview=()=>{const distance=Number($('betDistance').value),maximum=$('betMaximum').value,stop=$('betStopEnabled').checked?$('betStop').value:null;
  $('betPreview').textContent=`Bid ${distance}¢ below ask${maximum!==''?`, capped at ${maximum}¢`:''}. Up to ${$('betContracts').value} contracts, using up to ${$('betPercent').value}% of the shared balance. ${stop!==null?`Sell when the available bid reaches ${stop||'…'}¢ or lower, at the available price.`:'Hold filled positions to settlement.'}`;
  $('betStop').disabled=!$('betStopEnabled').checked;};
 for(const id of ['betMaximum','betDistance','betContracts','betPercent','betStop','betStopEnabled'])$(id).oninput=preview;
 $('betClose').onclick=()=>dialog.close();
 $('betForm').onsubmit=async event=>{
  event.preventDefault();if(!$('betForm').reportValidity())return;
  const button=$('betSave');button.disabled=true;
  try{
   if($('betStopEnabled').checked&&$('betStop').value==='')throw Error('Enter a loss-prevention trigger price.');
   await paperCall('strategies',squareStrategy(context.report,context.cell,context.minutes,context.band,{
    name:$('betName').value.trim(),below_ask_cents:Number($('betDistance').value),maximum_bid_cents:$('betMaximum').value===''?null:Number($('betMaximum').value),
    contracts:Number($('betContracts').value),balance_percent:Number($('betPercent').value),starting_cash_cents:10000,
    loss_trigger_cents:$('betStopEnabled').checked?Number($('betStop').value):null}));
   $('betMessage').textContent='Saved. Add more squares, then open Paper trading to replay them together using one shared balance.';
  }catch(error){$('betMessage').textContent=error.message}finally{button.disabled=false}
 };
 preview();dialog.showModal();
}

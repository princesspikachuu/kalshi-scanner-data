import {cookieValue} from './auth-client.mjs';
export async function paperCall(path,body){
 const headers={accept:'application/json'};
 if(body!==undefined){headers['content-type']='application/json';headers['x-csrf-token']=cookieValue(document.cookie,'__Host-pocket_csrf')||''}
 const response=await fetch('/api/paper/'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',redirect:'error',cache:'no-store'});
 if(!response.ok)throw Error(response.status===401?'Sign in to use paper trading.':response.status===409?'This replay request already has different settings. Try again.':'Unable to save or load. Check the selected square and saved trade evidence.');
 const data=await response.json();if(data.contract!=='paper-v1'||data.live_trading_enabled!==false)throw Error('Paper workspace unavailable.');return data;
}
export function squareStrategy(report,cell,minutes,band,settings){
 const [low,high]=band.split('-').map(Number);
 return {...settings,asset:report.asset,report_id:Number(report.id),minutes:[minutes],min_price:low,max_price:high-1,
  entry_minute_max:minutes,entry_minute_min:Math.max(0,...report.entry_minutes.filter(m=>m<minutes))};
}

import {cookieValue} from './auth-client.mjs';
import {demoError,escapeHTML as e,money} from './demo-client.mjs';
export async function liveCall(path,body){
 const headers={accept:'application/json'};
 if(body!==undefined){headers['content-type']='application/json';headers['x-csrf-token']=cookieValue(document.cookie,'__Host-pocket_csrf')||''}
 const response=await fetch('/api/live/'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store'});
 if(response.status===401){location.replace('/');throw Error('Sign in to continue')}
 if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(demoError(detail,response.status))}
 const data=await response.json();if(data.contract!=='live-bots-v1'||data.environment!=='live'||data.execution_enabled!==false)throw Error('Unexpected live workspace response');return data;
}
export function liveBotCard(bot){
 const c=bot.config,s=bot.sizing;
 const exit=c.cycle_exit_mode==='late_threshold'?`Final ${e(c.late_exit_minutes)} min: below ${e(c.late_exit_threshold_cents)}¢, maker sell at bid + 1¢; follow down when the gap exceeds ${e(c.late_exit_reprice_cents)}¢. At or above ${e(c.late_exit_threshold_cents)}¢, hold.`:`Maker sell at ${e(c.cycle_sell_cents)}¢.`;
 return `<article class="bot-card"><div class="bot-top"><div><h3 class="bot-name">${e(c.name)}</h3><span class="small">LIVE · ${e(c.squares.map(s=>s.asset.toUpperCase()).join(', '))}</span></div><span class="badge paused">Paused</span></div><p class="live-strategy">Maker buy ${e(c.cycle_buy_cents)}¢ · cancel unfilled buys after ${e(c.cycle_entry_minutes??'—')} min.<br>${exit}</p><div class="bot-stats"><div><span>Per bid · ${e(c.bid_percent)}% of trial</span><strong>${s?money(s.bid_cents):'Set trial budget'}</strong></div><div><span>Per market · ${e(c.market_percent)}%</span><strong>${s?money(s.market_cents):'—'}</strong></div><div><span>Per bot · ${e(c.bot_percent)}%</span><strong>${s?money(s.bot_cents):'—'}</strong></div></div><div class="bot-footer"><span class="small">${s?`${e(s.contracts_per_bid)} contracts per ${e(c.cycle_buy_cents)}¢ bid · `:''}No live trades<br>Copied Demo version ${e(bot.source_demo_revision)} · independent LIVE settings</span><button class="secondary" data-sizing="${e(bot.key)}">Edit allocation</button></div></article>`;
}

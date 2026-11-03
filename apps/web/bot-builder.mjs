import {demoCall,escapeHTML as e} from './demo-client.mjs';
import {createOfferingLoader,renderOfferings,toggleOffering,conditionKey} from './bot-table.mjs';
let activeDialog,activeCleanup;
// Group the exact trading series by market family, retaining broad choices
// for saved bots. Distinct assets stay distinct across conditions and results.
export const categoryGroups=[
 {name:'Crypto · 15-minute',items:{
  btc:'Bitcoin (BTC)',eth:'Ethereum (ETH)',sol:'Solana (SOL)',
  xrp:'XRP',doge:'Dogecoin (DOGE)',bnb:'BNB',hype:'Hyperliquid (HYPE)',
  zec:'Zcash (ZEC)',near:'NEAR',crypto:'All 15-minute crypto (legacy / broad)'
 }},
 {name:'Commodities · 15-minute',items:{
  gold_15m:'Gold',silver_15m:'Silver',platinum_15m:'Platinum',
  palladium_15m:'Palladium',copper_15m:'Copper',wti_15m:'WTI crude oil',
  natgas_15m:'Natural gas',brent_15m:'Brent crude oil',
  commodities_15m:'All 15-minute commodities (legacy / broad)'
 }},
 {name:'Finance · 15-minute',items:{
  usdcad_15m:'USD/CAD',audusd_15m:'AUD/USD',usdjpy_15m:'USD/JPY',
  gbpusd_15m:'GBP/USD',eurusd_15m:'EUR/USD',
  rate2y_15m:'2-year Treasury yield',rate5y_15m:'5-year Treasury yield',
  rate10y_15m:'10-year Treasury yield',rate30y_15m:'30-year Treasury yield',
  sp500_15m:'S&P 500 index',nasdaq100_15m:'Nasdaq 100 index',
  finance_15m:'All 15-minute finance (legacy / broad)'
 }},
 {name:'Other markets',items:{
  weather:'Hourly weather',weather_daily:'Daily weather',sports:'Sports winners'
 }}
];
export const categories=Object.assign({},...categoryGroups.map(g=>g.items));
export function marketCategoryOptions(){
 return categoryGroups.map(group=>`<optgroup label="${e(group.name)}">${Object.entries(group.items).map(([id,label])=>`<option value="${id}">${e(label)}</option>`).join('')}</optgroup>`).join('');
}

export function selectedSquares(selections){return selections.map(({report,cell,minutes,band})=>{const [low,high]=band.split('-').map(Number);return {asset:report.asset,min_price:low,max_price:high-1,min_minutes:Math.max(0,...report.entry_minutes.filter(m=>m<minutes)),max_minutes:minutes,report_id:Number(report.id),expected_roi:null,loss_cents:null}})}
export const BOT_DRAFT_KEY='money-bot-draft-v1';
const draftFields=['botName','qualification','priceReference','adjustment','minimum','maximum','bidPercent','marketPercent','botPercent','lossMode','lossCents','dailyLoss','tableAsset','squareAsset','squareLow','squareHigh','squareAfter','squareThrough'];
const cycleDraftFields=['strategy','cycleBuy','cycleSell','cycleCutoff','cycleRepeat','cycleAsset'];
draftFields.push(...cycleDraftFields);
export function cycleSquare(asset){return {asset,min_price:1,max_price:99,min_minutes:0,max_minutes:1440,report_id:null,expected_roi:null,loss_cents:null}}
const squareFields=['asset','min_price','max_price','min_minutes','max_minutes','report_id','expected_roi','loss_cents'];
function cleanDraft(value){
 if(!value||value.version!==1||!['new','edit'].includes(value.mode)||!value.fields||!Array.isArray(value.squares)||value.squares.length>45)return null;
 const fields={};
 for(const id of draftFields){if(value.fields[id]===undefined&&cycleDraftFields.includes(id))continue;if(typeof value.fields[id]!=='string'||value.fields[id].length>256)return null;fields[id]=value.fields[id]}
 const squares=[];
 for(const raw of value.squares){
  if(!raw||!Object.hasOwn(categories,raw.asset))return null;
  if(!['min_price','max_price','min_minutes','max_minutes'].every(k=>Number.isSafeInteger(raw[k])))return null;
  if(raw.min_price<1||raw.max_price>99||raw.min_price>raw.max_price||raw.min_minutes<0||raw.max_minutes>1440||raw.min_minutes>=raw.max_minutes)return null;
  if(raw.report_id!=null&&(!Number.isSafeInteger(raw.report_id)||raw.report_id<1))return null;
  if(['expected_roi','loss_cents'].some(k=>raw[k]!=null&&!Number.isFinite(raw[k])))return null;
  for(const key of ['maximum_cents','loss_prevention_cents'])if(raw[key]!=null&&(!Number.isSafeInteger(raw[key])||raw[key]<1||raw[key]>99))return null;
  squares.push({...Object.fromEntries(squareFields.map(k=>[k,raw[k]??null])),...Object.fromEntries(['maximum_cents','loss_prevention_cents'].filter(k=>raw[k]!=null).map(k=>[k,raw[k]]))});
 }
 if(!Object.hasOwn(categories,fields.tableAsset)||!Object.hasOwn(categories,fields.squareAsset))return null;
 if(value.mode==='edit'&&(typeof value.botKey!=='string'||value.botKey.length>80||!Number.isSafeInteger(value.revision)||value.revision<1))return null;
 return {version:1,mode:value.mode,botKey:value.mode==='edit'?value.botKey:null,revision:value.mode==='edit'?value.revision:null,...(Number.isSafeInteger(value.settingsRevision)&&value.settingsRevision>0?{settingsRevision:value.settingsRevision}:{}),fields,squares,details:Array.isArray(value.details)?value.details.slice(0,2).map(Boolean):[]};
}
export function createBotDraftStore(storage){
 if(storage===undefined){try{storage=globalThis.localStorage}catch{storage=null}}
 let last=null;
 return {
  load(){try{const raw=storage?.getItem(BOT_DRAFT_KEY);if(!raw)return null;if(raw.length>65536)throw Error();const draft=cleanDraft(JSON.parse(raw));if(!draft)throw Error();last=JSON.stringify(draft);return draft}catch{try{storage?.removeItem(BOT_DRAFT_KEY)}catch{}return null}},
  save(value){try{const draft=cleanDraft(value);if(!draft||!storage)return false;const raw=JSON.stringify(draft);if(raw.length>65536)return false;if(raw!==last){storage.setItem(BOT_DRAFT_KEY,raw);last=raw}return true}catch{return false}},
  clear(){last=null;try{storage?.removeItem(BOT_DRAFT_KEY)}catch{}}
 };
}
const drafts=createBotDraftStore();
export function clearBotDraft(){drafts.clear()}
export function duplicateBotConfig(bot){
 const config=JSON.parse(JSON.stringify(bot.config));
 config.name=(config.name||'Bot').slice(0,73)+' · copy';
 return config;
}
export function resolveBotDraft(draft,bots=[]){
 const bot=draft.mode==='edit'?bots.find(b=>b.key===draft.botKey&&b.revision===draft.revision&&(b.settings_revision??b.revision)===(draft.settingsRevision??draft.revision)):null;
 return {bot:bot||null,draft,recoveredAsNew:draft.mode==='edit'&&!bot};
}
export function restoreBotDraft({bots,onSave}={}){
 if(activeDialog?.isConnected)return false;
 const draft=drafts.load();if(!draft||draft.mode==='edit'&&!bots)return false;
 const resolved=resolveBotDraft(draft,bots||[]);
 openBotBuilder({...resolved,onSave});return true;
}
export function openBotBuilder({selections=[],bot=null,initialConfig=null,draft=null,recoveredAsNew=false,onSave=()=>location.assign('/bots')}={}){
 activeCleanup?.();activeDialog?.remove();const dialog=document.createElement('dialog');activeDialog=dialog;dialog.id='botBuilder';
 const config=bot?.config||initialConfig||{};
 let squares=(draft?.squares||config.squares||selectedSquares(selections)).map(s=>({...s}));
 let tableAsset=squares[0]?.asset||'btc',tableReport=null,tableRequest=0,tableLoading=true;
 const loadOfferings=createOfferingLoader();
 dialog.innerHTML=`<form id="botEditor"><div class="dialog-head"><div><p class="eyebrow">KALSHI DEMO · ONE BOT, MANY CONDITIONS</p><h2>${bot?'Manage bot':initialConfig?'Duplicate bot':'New bot'}</h2></div><button type="button" id="closeBuilder" class="secondary" aria-label="Close">×</button></div><div class="dialog-body"><label>Bot name<input id="botName" required maxlength="80" value="${e(config.name||'') }" placeholder="e.g. Afternoon crypto"></label><label>Trading mode<select id="strategy"><option value="conditions">Price / time conditions</option><option value="buy_low_sell_high">Buy low, sell high</option></select></label><section id="cycleSettings" class="panel" hidden><h3>Buy low, sell high</h3><div class="field-grid"><label>Market category<select id="cycleAsset">${marketCategoryOptions()}</select></label><label>Low buy price · ¢ on YES and NO<input id="cycleBuy" type="number" min="1" max="49" step="1" required value="${config.cycle_buy_cents??10}"></label><label>Profit sell price · ¢<input id="cycleSell" type="number" min="2" max="99" step="1" required value="${config.cycle_sell_cents??20}"></label><label>Stop new buys · minutes before close<input id="cycleCutoff" type="number" min="0" max="1439" step="1" required value="${config.cycle_cutoff_minutes??3}"></label><p class="small">Unfilled low bids are automatically canceled with 3 minutes remaining. Filled positions and sell orders remain managed.</p><label>After a completed profit sale<select id="cycleRepeat"><option value="yes">Place a new low bid</option><option value="no">One cycle per side per market</option></select></label></div><p class="small">Places low maker-only bids on YES and NO when an open market is discovered. After one side fills, the opposite low bid is canceled and verified before posting a fixed profit sell for the held quantity, including partial fills. Both low bids can resume after the inventory is fully exited. Profit sells can take liquidity at the target or better. Repeat happens only after a confirmed full exit; protective stops do not restart a cycle. The cutoff expires unfilled low bids and prevents replacements, while sells continue. Cutoffs use the market end (Kalshi’s estimated finish for sports). Existing open markets before cutoff are included. Watches up to 100 markets within the next 24 hours; unavailable or unconfirmed markets wait. If opposite fills offset inventory, the app verifies and records that instead of selling nonexistent contracts. Fees can reduce or eliminate the price spread profit.</p></section><section id="conditionEntry"><h3>When to enter</h3><div class="field-grid"><label>Match square prices against<select id="qualification"><option value="ask">Current ASK</option><option value="bid">Current BID</option></select></label><label>Calculate entry price from<select id="priceReference"><option value="ask">Current ASK</option><option value="bid">Current BID</option></select></label><label>Price adjustment · ¢<input id="adjustment" type="number" required min="-99" max="99" value="${config.adjustment_cents??-1}"></label><label>Optional minimum bid · ¢<input id="minimum" type="number" min="1" max="99" placeholder="No minimum" value="${config.minimum_cents??''}"></label><label>Optional maximum bid · ¢<input id="maximum" type="number" min="1" max="99" placeholder="No ceiling" value="${config.maximum_cents??''}"></label></div><p class="small">Entry prices stay fixed. Orders are post-only, canceled when their conditions stop matching, and expire by the market’s end. The maximum caps the calculated bid; lower-price conditions keep their lower bids. For example, ASK 70¢ with −1¢ bids 69¢ even with a 96¢ maximum. Bids below the minimum are skipped, never raised to the minimum. Leave either limit blank to disable it. Prices that would cross the ask are skipped.</p></section><h3>Shared spending limits</h3><div class="field-grid three"><label>Per bid · % of account<input id="bidPercent" type="number" step="0.1" required min="0.1" max="100" value="${config.bid_percent??1}"></label><label>Per market · %<input id="marketPercent" type="number" step="0.1" required min="0.1" max="100" value="${config.market_percent??3}"></label><label>Per bot · %<input id="botPercent" type="number" step="0.1" required min="0.1" max="100" value="${config.bot_percent??10}"></label></div><p class="small">All bot settings can be saved while running or paused. New spending limits apply to future bids. Lowering a square maximum cancels any remaining entry bid above it; filled positions and protective exits stay intact. Changing entry rules or bot-wide exits starts a new revision: old unfilled bids are canceled, and existing positions use the current-time loss-prevention settings in their original price column. The bot stays running or paused as selected. Spending percentages can be set independently. Quantities still obey every remaining limit and available cash.</p><h3>Protective exits</h3><div class="field-grid"><label>Loss prevention<select id="lossMode"><option value="off">Off · hold to settlement</option><option value="research">Research recommendation</option><option value="manual">Manual threshold</option></select></label><label>Manual trigger · current ASK in ¢<input id="lossCents" type="number" min="1" max="99" value="${config.loss_cents??''}"></label></div><p class="small">New entries are skipped while current ASK is already at or below the selected protective threshold. Each entry is tracked separately. Triggered exits start maker-only at current ASK + 1¢. They lower as ASK falls and stay fixed when ASK rises, so the market can reach the resting exit. New entries wait while an exit is active.</p><details class="advanced"><summary>Optional daily cutoff</summary><p class="small">Disabled when blank. Uses net realized losses only.</p><label>Daily loss limit · %<input id="dailyLoss" type="number" step="0.1" min="0.1" max="100" value="${config.daily_loss_percent??''}" placeholder="Disabled"></label></details><section id="conditionTable" class="panel"><h3>Qualifying squares</h3><p class="small">Every selected square shares this bot’s settings. YES and NO are evaluated automatically, with one direction per market.</p><div class="field-grid"><label>Market category<select id="tableAsset">${marketCategoryOptions()}</select></label><div class="table-refresh"><button id="refreshBotTable" type="button" class="secondary">Refresh saved table</button></div></div><p id="botTableStatus" class="small" role="status"></p><div id="botTable" class="bot-table-scroll"></div><p class="small">Tap squares to select or deselect, then enter a maximum bid or loss-prevention trigger inside each selected square. A square value overrides the corresponding bot-wide value. Blank maximum uses the bot-wide maximum. Blank loss prevention uses the bot-wide setting; a value overrides it for that square, including when bot-wide loss prevention is off. Held positions follow the square for the market’s current time remaining in their original price column, never the purchase-time row. Blank uses the bot-wide setting; research mode uses the current-time recommendation. An exit already triggered keeps its downward-only limit. Price columns and time rows define entry conditions; ROI, win rate and sell thresholds use saved research. Squares without observations can be selected as manual conditions.</p><p id="selectedCount" class="small"></p><div id="builderSquares" class="square-list"></div><details class="advanced" open><summary>Add a condition manually</summary><div class="field-grid"><label>Category<select id="squareAsset">${marketCategoryOptions()}</select></label><span></span><label>Minimum price · ¢<input id="squareLow" type="number" min="1" max="99" value="60"></label><label>Maximum price · ¢<input id="squareHigh" type="number" min="1" max="99" value="69"></label><label>After · minutes to close<input id="squareAfter" type="number" min="0" max="1439" value="0"></label><label>Through · minutes to close<input id="squareThrough" type="number" min="1" max="1440" value="5"></label></div><button id="addSquare" type="button" class="secondary">Add condition</button></details><p class="small">Selections across categories stay in this single bot and share the settings below. Manual conditions have no research exit recommendation.</p></section><p id="draftStatus" class="small" role="status"></p><p class="message" id="builderMessage" role="status"></p></div><div class="dialog-actions">${bot?'<button id="archiveBot" class="secondary" type="button">Archive bot</button>':''}<button id="cancelBuilder" class="secondary" type="button">Cancel</button><button class="primary" id="saveBot" type="submit">${bot?'Save changes':'Save bot · paused'}</button></div></form>`;
 document.body.append(dialog);const $=id=>dialog.querySelector('#'+id);
 for(const id of ['squareLow','squareHigh','squareAfter','squareThrough'])$(id).setAttribute('form','unsubmittedCondition');
 for(const [id,value] of [['strategy',config.strategy||'conditions'],['cycleAsset',config.squares?.[0]?.asset||'crypto'],['cycleRepeat',config.cycle_repeat===false?'no':'yes'],['qualification',config.qualification],['priceReference',config.price_reference],['lossMode',config.loss_mode]])if(value)$(id).value=value;
 let draftTimer;
 function saveDraft(){
  if(!dialog.isConnected)return;
  clearTimeout(draftTimer);
  const saved=drafts.save({version:1,mode:bot?'edit':'new',botKey:bot?.key||null,revision:bot?.revision||null,settingsRevision:bot?.settings_revision??bot?.revision,fields:Object.fromEntries(draftFields.map(id=>[id,$(id).value])),squares,details:[...dialog.querySelectorAll('details.advanced')].map(d=>d.open)});
  $('draftStatus').textContent=saved?'Draft saved on this device.':'This browser could not save the draft. Keep this page open until you save the bot.';
 }
 const scheduleDraft=()=>{if(!dialog.isConnected)return;clearTimeout(draftTimer);draftTimer=setTimeout(saveDraft,200)};
 const hidden=()=>{if(document.hidden)saveDraft()};
 dialog.addEventListener('input',scheduleDraft);dialog.addEventListener('change',scheduleDraft);
 window.addEventListener('pagehide',saveDraft);document.addEventListener('visibilitychange',hidden);
 const cleanup=()=>{clearTimeout(draftTimer);window.removeEventListener('pagehide',saveDraft);document.removeEventListener('visibilitychange',hidden);if(activeCleanup===cleanup)activeCleanup=null};activeCleanup=cleanup;
 if(draft){
  for(const id of draftFields)if(draft.fields[id]!==undefined)$(id).value=draft.fields[id];
  tableAsset=draft.fields.tableAsset;
  [...dialog.querySelectorAll('details.advanced')].forEach((d,i)=>{if(i<draft.details.length)d.open=draft.details[i]});
  $('builderMessage').textContent=recoveredAsNew?'The original bot changed or was removed. Your draft is restored as a new bot.':'Your unfinished bot draft has been restored.';
 }
 for(const detail of dialog.querySelectorAll('details.advanced'))detail.addEventListener('toggle',scheduleDraft);
 function setSquareRisk(square,raw,field){
  const index=squares.findIndex(s=>conditionKey(s)===conditionKey(square));if(index<0)return;
  const value=raw===''?null:Number(raw);if(value!==null&&(!Number.isSafeInteger(value)||value<1||value>99))return;
  squares[index]={...squares[index]};if(value===null)delete squares[index][field];else squares[index][field]=value;
  for(const input of dialog.querySelectorAll('[data-square-key]'))if(input.dataset.squareKey===conditionKey(square)&&input.dataset.squareField===field)input.value=raw;
  saveDraft();
 }
 function draw(){
  saveDraft();
  if($('strategy').value==='buy_low_sell_high')return;
  $('selectedCount').textContent=`${squares.length} of 45 conditions selected · one bot`;
  renderOfferings($('botTable'),tableAsset,tableReport,squares,square=>{try{squares=toggleOffering(squares,square);$('builderMessage').textContent='';draw()}catch(error){$('builderMessage').textContent=error.message}},{loading:tableLoading,onMaximum:(s,v)=>setSquareRisk(s,v,'maximum_cents'),onLoss:(s,v)=>setSquareRisk(s,v,'loss_prevention_cents')});
  $('builderSquares').innerHTML=squares.length?squares.map((s,i)=>`<span class="square-chip">${e(categories[s.asset]||s.asset)} · ${s.min_price}–${s.max_price}¢ · ${s.min_minutes}–${s.max_minutes}m <label>Maximum bid · ¢<input data-square-key="${e(conditionKey(s))}" data-square-field="maximum_cents" type="number" min="1" max="99" step="1" placeholder="Use bot maximum" value="${s.maximum_cents??''}"></label><label>Loss prevention · ¢<input data-square-key="${e(conditionKey(s))}" data-square-field="loss_prevention_cents" type="number" min="1" max="99" step="1" placeholder="Use bot setting" value="${s.loss_prevention_cents??''}"></label><button type="button" data-remove="${i}" aria-label="Remove condition">×</button></span>`).join(''):'<p class="small">No conditions yet. Tap one or more squares in the table above.</p>';for(const input of $('builderSquares').querySelectorAll('[data-square-key]'))input.oninput=()=>{const square=squares.find(s=>conditionKey(s)===input.dataset.squareKey);if(square)setSquareRisk(square,input.value,input.dataset.squareField)};for(const button of dialog.querySelectorAll('[data-remove]'))button.onclick=()=>{squares.splice(Number(button.dataset.remove),1);draw()}}
 $('tableAsset').value=tableAsset;
 async function loadTable(refresh=false){
  const ticket=++tableRequest;tableAsset=$('tableAsset').value;tableReport=null;tableLoading=true;draw();
  $('botTableStatus').textContent='Loading saved statistics…';$('refreshBotTable').disabled=true;
  try{
   const {report,basis}=await loadOfferings(tableAsset,{refresh});
   if(ticket!==tableRequest||!dialog.isConnected)return;
   tableReport=report;
   $('botTableStatus').textContent=report?`${basis} · report #${report.id} · ${report.summary.observation_count.toLocaleString()} observations${report.summary.first_date?' · '+report.summary.first_date+' through '+report.summary.last_date:''}${report.sampled_preview?' · preliminary sample':''}`:'No saved statistics for this category. You can still select conditions; ROI and research exits are unavailable.';
   draw();
  }catch(error){if(ticket===tableRequest&&dialog.isConnected)$('botTableStatus').textContent=error.message+' You can still select manual conditions.'}
  finally{if(ticket===tableRequest&&dialog.isConnected){tableLoading=false;$('refreshBotTable').disabled=false;draw()}}
 }
 $('tableAsset').onchange=()=>loadTable();$('refreshBotTable').onclick=()=>loadTable(true);
 $('addSquare').onclick=()=>{
  if(['squareLow','squareHigh','squareAfter','squareThrough'].some(id=>!$(id).reportValidity()))return;
  const value=id=>Number($(id).value),square={asset:$('squareAsset').value,min_price:value('squareLow'),max_price:value('squareHigh'),min_minutes:value('squareAfter'),max_minutes:value('squareThrough'),report_id:null,expected_roi:null,loss_cents:null};
  if(square.min_price>square.max_price||square.min_minutes>=square.max_minutes||squares.length>=45){$('builderMessage').textContent='Choose increasing price/time bounds, up to 45 conditions.';return}
  squares.push(square);draw();
 };
 const close=()=>{cleanup();if(activeDialog===dialog){drafts.clear();activeDialog=null}dialog.close();dialog.remove()};dialog.addEventListener('cancel',event=>{event.preventDefault();close()});$('closeBuilder').onclick=close;$('cancelBuilder').onclick=close;if(bot)$('archiveBot').onclick=async()=>{try{await demoCall(`bots/${bot.key}/control`,{action:bot.archived?'restore':'archive',revision:bot.revision});close();onSave()}catch(error){$('builderMessage').textContent=error.message}};
 const exits=()=>{$('lossCents').disabled=$('lossMode').value!=='manual';$('lossCents').required=$('lossMode').value==='manual'};$('lossMode').onchange=exits;exits();draw();
 $('botEditor').onsubmit=async event=>{
  event.preventDefault();saveDraft();if($('strategy').value!=='buy_low_sell_high'&&!squares.length){$('builderMessage').textContent='Select at least one price/time condition.';return}
  const number=id=>Number($(id).value),optional=id=>$(id).value===''?null:number(id);
  const body={version:1,name:$('botName').value.trim(),squares:squares.map(s=>Object.fromEntries(Object.entries(s).filter(([k,v])=>!['maximum_cents','loss_prevention_cents'].includes(k)||v!=null))),qualification:$('qualification').value,price_reference:$('priceReference').value,adjustment_cents:number('adjustment'),maximum_cents:optional('maximum'),minimum_cents:optional('minimum'),bid_percent:number('bidPercent'),market_percent:number('marketPercent'),bot_percent:number('botPercent'),loss_mode:$('lossMode').value,loss_cents:$('lossMode').value==='manual'?optional('lossCents'):null,daily_loss_percent:optional('dailyLoss')};
  if($('strategy').value==='buy_low_sell_high'){
   body.strategy='buy_low_sell_high';body.cycle_buy_cents=number('cycleBuy');body.cycle_sell_cents=number('cycleSell');body.cycle_cutoff_minutes=number('cycleCutoff');body.cycle_repeat=$('cycleRepeat').value==='yes';body.squares=[cycleSquare($('cycleAsset').value)];body.minimum_cents=null;body.maximum_cents=null;body.adjustment_cents=-1;body.qualification='ask';body.price_reference='ask';
   if(body.cycle_sell_cents<=body.cycle_buy_cents){$('builderMessage').textContent='The profit sell price must be higher than the low buy price.';return}
  }
  if(body.minimum_cents!==null&&body.maximum_cents!==null&&body.minimum_cents>body.maximum_cents){$('builderMessage').textContent='Minimum bid must not exceed maximum bid.';return}
  if(Number.isSafeInteger(bot?.settings_revision))body.expected_settings_revision=bot.settings_revision;
  $('saveBot').disabled=true;try{await demoCall(bot?`bots/${bot.key}/configure`:'bots',body);close();onSave()}catch(error){$('builderMessage').textContent=error.message}finally{if($('saveBot'))$('saveBot').disabled=false}
 };
 function applyStrategy(){
  const cycle=$('strategy').value==='buy_low_sell_high';$('cycleSettings').hidden=!cycle;$('conditionEntry').hidden=cycle;$('conditionTable').hidden=cycle;
  for(const section of ['conditionEntry','conditionTable'])for(const input of $(section).querySelectorAll('input,select'))input.disabled=cycle;
  for(const input of $('cycleSettings').querySelectorAll('input,select'))input.disabled=!cycle;
  $('lossMode').querySelector('option[value="off"]').textContent=cycle?'Off · profit target only':'Off · hold to settlement';
  $('lossMode').querySelector('option[value="research"]').disabled=cycle;if(cycle&&$('lossMode').value==='research')$('lossMode').value='off';exits();
 }
 $('strategy').onchange=()=>{applyStrategy();if($('strategy').value==='conditions')void loadTable();saveDraft()};applyStrategy();
 dialog.showModal();$('botName').focus();if($('strategy').value==='conditions')void loadTable();
}

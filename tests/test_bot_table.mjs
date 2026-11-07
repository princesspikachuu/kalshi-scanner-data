import test from 'node:test';
import assert from 'node:assert/strict';
import {offeringRows,toggleOffering,conditionKey,createOfferingLoader,renderOfferings} from '../apps/web/bot-table.mjs';
const hold={minutes_before_close:5,price_band_cents:'60-70',sampled_markets:12,hypothetical_roi_percent:7.25,win_rate_percent:75};
const report={id:'123',asset:'btc',entry_minutes:[15,10,5,3,1],price_bands:['50-60','60-70','70-80','80-90','90-100'],cells:[{hold,loss_prevention:{sell_label:'Sell ≤ 45¢'}}]};
test('price/time offerings use exact saved square boundaries and leave absent data unverified',()=>{
 const rows=offeringRows('btc',report),known=rows[2].cells[1];
 assert.deepEqual(known.square,{asset:'btc',min_price:60,max_price:69,min_minutes:3,max_minutes:5,report_id:123,expected_roi:null,loss_cents:null});
 assert.equal(known.cell.hold.hypothetical_roi_percent,7.25);
 assert.equal(rows[0].cells[0].square.report_id,null);
 assert.equal(rows[0].cells[4].square.max_price,99);
 assert.equal(offeringRows('weather').flatMap(r=>r.cells).length,45);
});
test('many selected squares and categories remain conditions of one shared bot',()=>{
 const a=offeringRows('btc',report)[2].cells[1].square,b=offeringRows('eth')[0].cells[3].square;
 let selected=toggleOffering([],a);selected=toggleOffering(selected,b);
 assert.equal(selected.length,2);assert.equal(selected[0].asset,'btc');assert.equal(selected[1].asset,'eth');
 selected=toggleOffering(selected,{...a,report_id:999});assert.deepEqual(selected,[b]);
 const all=offeringRows('weather').flatMap(r=>r.cells.map(c=>c.square));
 assert.throws(()=>toggleOffering(all,a),/45 conditions/);
});
test('dialog cache deduplicates saved-report reads and refreshes only on request',async()=>{
 let calls=0;const load=createOfferingLoader({research:{category:async()=>{calls++;return report}},collection:{list:()=>assert.fail('No queue read needed for cumulative history')}});
 const [a,b]=await Promise.all([load('btc'),load('btc')]);assert.equal(calls,1);assert.equal(a.report,b.report);
 await load('btc');assert.equal(calls,1);await load('btc',{refresh:true});assert.equal(calls,2);
});
test('no cumulative history falls back to bounded saved collections without collection writes',async()=>{
 let pages=0;const load=createOfferingLoader({research:{category:async()=>null,result:async(id,version)=>{assert.equal(id,'collection');assert.equal(version,'123');return report}},collection:{list:async(asset,before,group,limit)=>{pages++;assert.equal(limit,10);return {items:group==='finished'?[{id:'collection',result_id:'123',created_at:'2026-10-29T01:00:00Z'}]:[]}}}});
 assert.equal((await load('btc')).basis,'Latest saved collection');assert.equal(pages,2);
});
class Element{
 constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners={};this.text=''}
 set textContent(value){this.text=String(value)} get textContent(){return this.text+' '+this.children.map(n=>n.textContent).join(' ')}
 append(...items){this.children.push(...items)}replaceChildren(...items){this.children=items}setAttribute(k,v){this.attrs[k]=v}addEventListener(k,v){this.listeners[k]=v}
}
test('inline table selects and deselects cells without opening another strategy or page',()=>{
 const doc={createElement:tag=>new Element(tag,doc)},container=doc.createElement('div');let selected=[];
 const draw=()=>renderOfferings(container,'btc',report,selected,square=>{selected=toggleOffering(selected,square);draw()});
 const button=()=>container.children[0].children[1].children[2].children[2].children[0];
 draw();assert.match(button().textContent,/7.25% ROI/);assert.match(button().textContent,/75.0% wins/);assert.match(button().textContent,/Sell ≤ 45¢/);
 assert.equal(button().attrs['aria-pressed'],'false');button().listeners.click();assert.equal(selected.length,1);assert.equal(button().attrs['aria-pressed'],'true');button().listeners.click();assert.equal(selected.length,0);
 renderOfferings(container,'btc',report,selected,()=>assert.fail('Not interactive during load'),{loading:true});assert.equal(button().disabled,true);
});

import {BOT_DRAFT_KEY,createBotDraftStore,duplicateBotConfig,resolveBotDraft,categoryGroups,categories,marketCategoryOptions} from '../apps/web/bot-builder.mjs';
function draft(){return {version:1,mode:'new',fields:{botName:'My unfinished bot',qualification:'ask',priceReference:'bid',adjustment:'',minimum:'60',maximum:'96',bidPercent:'1.5',marketPercent:'3',botPercent:'10',lossMode:'manual',lossCents:'55',dailyLoss:'',tableAsset:'weather',squareAsset:'sports',squareLow:'70',squareHigh:'79',squareAfter:'5',squareThrough:'30'},squares:[offeringRows('btc',report)[2].cells[1].square,offeringRows('weather')[0].cells[2].square],details:[true,true]}}
function storage(){const values=new Map();return {writes:0,getItem:key=>values.get(key)||null,setItem(key,value){this.writes++;values.set(key,value)},removeItem:key=>values.delete(key),values}}
test('duplicate copies conditions and every setting independently, without identity or execution state',()=>{
 const source={key:'existing',revision:7,desired:'running',config:{name:'Source',version:1,squares:[offeringRows('btc',report)[2].cells[1].square],minimum_cents:60,maximum_cents:96,loss_mode:'manual',loss_cents:55}};
 const copy=duplicateBotConfig(source);
 assert.equal(copy.name,'Source · copy');assert.equal(copy.minimum_cents,60);assert.equal(copy.maximum_cents,96);
 assert.equal(copy.loss_cents,55);assert.deepEqual(copy.squares,source.config.squares);
 for(const key of ['key','revision','desired','orders','stats'])assert.equal(copy[key],undefined);
 copy.squares[0].min_price=80;assert.equal(source.config.squares[0].min_price,60);
 assert.ok(duplicateBotConfig({config:{name:'x'.repeat(80),squares:[]}}).name.length<=80);
});
test('draft survives a fresh storage instance with raw blank fields and all condition inputs intact',()=>{
 const memory=storage(),first=createBotDraftStore(memory),input=draft();
 assert.equal(first.save(input),true);
 const restored=createBotDraftStore(memory).load();
 assert.deepEqual(restored.fields,input.fields);assert.deepEqual(restored.squares,input.squares);assert.deepEqual(restored.details,[true,true]);
 assert.equal(restored.fields.adjustment,'');assert.equal(restored.fields.dailyLoss,'');
 assert.equal(restored.fields.squareAsset,'sports');assert.equal(restored.fields.tableAsset,'weather');
 assert.equal(first.save(input),true);assert.equal(memory.writes,1);
 first.clear();assert.equal(createBotDraftStore(memory).load(),null);
});
test('draft stores only bounded builder inputs and tolerates disabled browser storage',()=>{
 const memory=storage(),store=createBotDraftStore(memory),input=draft();input.api_key='NEVER_SAVE_THIS';input.fields.private_key='NEVER_SAVE_THIS';
 assert.equal(store.save(input),true);assert.ok(!memory.getItem(BOT_DRAFT_KEY).includes('NEVER_SAVE_THIS'));
 assert.equal(store.save({...draft(),squares:Array(46).fill(draft().squares[0])}),false);
 memory.setItem(BOT_DRAFT_KEY,'broken JSON');assert.equal(store.load(),null);assert.equal(memory.getItem(BOT_DRAFT_KEY),null);
 const blocked=createBotDraftStore({getItem(){throw Error('blocked')},setItem(){throw Error('quota')},removeItem(){throw Error('blocked')}});
 assert.equal(blocked.save(draft()),false);assert.equal(blocked.load(),null);assert.doesNotThrow(()=>blocked.clear());
});
test('edit recovery binds only the same saved revision; changed or missing bots become new drafts',()=>{
 const input={...draft(),mode:'edit',botKey:'bot-one',revision:3},current={key:'bot-one',revision:3,config:{}};
 assert.equal(resolveBotDraft(input,[current]).bot,current);
 assert.equal(resolveBotDraft(input,[{...current,revision:4}]).bot,null);
 assert.equal(resolveBotDraft(input,[]).recoveredAsNew,true);
 assert.equal(resolveBotDraft(draft(),[current]).recoveredAsNew,false);
});

test('edit drafts preserve settings revision and cannot overwrite a newer allocation edit',()=>{
 const input={...draft(),mode:'edit',botKey:'one',revision:3,settingsRevision:5},memory=storage(),store=createBotDraftStore(memory);
 assert.equal(store.save(input),true);const restored=store.load();assert.equal(restored.settingsRevision,5);
 assert.equal(resolveBotDraft(restored,[{key:'one',revision:3,settings_revision:5}]).recoveredAsNew,false);
 assert.equal(resolveBotDraft(restored,[{key:'one',revision:3,settings_revision:6}]).recoveredAsNew,true);
});

test('selected table squares have independent editable maximums and preserve them through drafts and duplication',()=>{
 const doc={createElement:tag=>new Element(tag,doc)},container=doc.createElement('div');
 const first=offeringRows('btc')[0].cells[1].square,second=offeringRows('btc')[1].cells[1].square;
 const selected=[{...first,maximum_cents:63,loss_prevention_cents:55},{...second,maximum_cents:61}];let changed;
 renderOfferings(container,'btc',null,selected,()=>assert.fail('Editing a maximum must not toggle its square'),{onMaximum:(s,value)=>changed={s,value},onLoss:(s,value)=>changed={s,value}});
 const rows=container.children[0].children[1].children;
 const input=rows[0].children[2].children[1].children[0];assert.equal(input.value,63);input.value='59';input.listeners.input();
 assert.equal(changed.value,'59');assert.equal(changed.s.max_minutes,15);
 assert.equal(rows[1].children[2].children[1].children[0].value,61);
 const loss=rows[0].children[2].children[2].children[0];assert.equal(loss.value,55);loss.value='';loss.listeners.input();assert.equal(changed.value,'');
 const memory=storage(),store=createBotDraftStore(memory),value=draft();value.squares=selected;assert.equal(store.save(value),true);
 assert.equal(store.load().squares[1].maximum_cents,61);assert.equal(store.load().squares[0].loss_prevention_cents,55);
 const copy=duplicateBotConfig({config:{name:'Per square',squares:selected}});copy.squares[0].maximum_cents=55;assert.equal(selected[0].maximum_cents,63);
});

import {cycleSquare} from '../apps/web/bot-builder.mjs';
test('buy low sell high drafts and duplicate preserve prices, cutoff, repeat and chosen category',()=>{
 const memory=storage(),store=createBotDraftStore(memory),input=draft();Object.assign(input.fields,{strategy:'buy_low_sell_high',cycleBuy:'8',cycleSell:'18',cycleCutoff:'3',cycleRepeat:'no',cycleAsset:'weather'});
 input.squares=[cycleSquare('weather')];assert.equal(store.save(input),true);assert.deepEqual(store.load().fields,input.fields);
 const source={config:{name:'Cycles',strategy:'buy_low_sell_high',cycle_buy_cents:8,cycle_sell_cents:18,cycle_cutoff_minutes:3,cycle_repeat:false,squares:input.squares}};
 const copy=duplicateBotConfig(source);assert.equal(copy.cycle_sell_cents,18);assert.equal(copy.cycle_repeat,false);copy.squares[0].asset='btc';assert.equal(source.config.squares[0].asset,'weather');
});


test('all individual 15-minute categories have independently selectable price-time grids',()=>{
 const groups=Object.fromEntries(categoryGroups.map(g=>[g.name.split(' ·')[0],g.items]));
 assert.equal(Object.keys(groups.Crypto).length,10);
 assert.equal(Object.keys(groups.Commodities).length,9);
 assert.equal(Object.keys(groups.Finance).length,12);
 const instruments=['btc','eth','sol','xrp','doge','bnb','hype','zec','near',
  'gold_15m','silver_15m','platinum_15m','palladium_15m','copper_15m','wti_15m','natgas_15m','brent_15m',
  'usdcad_15m','audusd_15m','usdjpy_15m','gbpusd_15m','eurusd_15m',
  'rate2y_15m','rate5y_15m','rate10y_15m','rate30y_15m','sp500_15m','nasdaq100_15m'];
 assert.equal(instruments.length,28);
 const unique=new Set();
 for(const asset of instruments){
  assert.ok(categories[asset],asset);
  const rows=offeringRows(asset);
  assert.deepEqual(rows.map(r=>r.minutes),[15,10,5,3,1],asset);
  assert.equal(rows[0].cells[0].square.asset,asset);
  unique.add(conditionKey(rows[0].cells[0].square));
 }
 assert.equal(unique.size,instruments.length,'selections for different instruments never collapse');
 const options=marketCategoryOptions();
 for(const token of ['Crypto · 15-minute','Commodities · 15-minute','Finance · 15-minute',
  'value="sol"','value="gold_15m"','value="eurusd_15m"','value="sp500_15m"'])assert.ok(options.includes(token),token);
 for(const broad of ['crypto','commodities_15m','finance_15m'])assert.ok(categories[broad],'Existing broad-category bots remain editable');
});

test('new individual categories do not show invented aggregate research statistics',async()=>{
 let queried=false;
 const loader=createOfferingLoader({
  research:{category:()=>{queried=true;throw Error('Cannot use aggregate ROI for instrument')}},
  collection:{list:()=>{queried=true;throw Error('Cannot use aggregate historical runs')}}
 });
 for(const asset of ['sol','gold_15m','rate10y_15m','sp500_15m','commodities_15m','finance_15m']){
  const item=await loader(asset);
  assert.equal(item.report,null);
  assert.match(item.basis,/No instrument-specific historical research/);
 }
 assert.equal(queried,false);
});

import {accountMarkup,exposureMarkup,pendingLabel,pnlClass,valueBounds,accountPnl} from '../apps/web/shadow-view.mjs';
test('shadow totals show wallet losses even with zero verified cycles and label costs separately',()=>{
 const portfolio={total_pnl:'-3',equity:'97',realized_pnl:'-18.7',unrealized_pnl:'15.7',deposits:'100',
  cash:'70',available_cash:'60',unfilled_bids:'10',active_cost:'11',active_value:'20',pending_cost:'.3',
  pending_contracts:'10',pending_value:'7',pending_payout_state:'estimated',reconciliation_difference:'0'};
 const html=accountMarkup({portfolio,quality:{verified_cycles:0,gap_cycles:18},at:1000});
 for(const token of ['Total P/L','-$3.00','$97.00','-$18.70','$15.70','No verified completed cycles',
  'Unfilled buy bids','Active positions · cost','Awaiting settlement · cost','outcome unconfirmed'])assert.ok(html.includes(token),token);
 assert.equal(pnlClass('-3'),'negative');assert.equal(pnlClass(null),'');
 assert.ok(exposureMarkup(portfolio).includes('Cash reserved, not spent'));
});
test('pending payout labels distinguish confirmed returns, estimates and unavailable prices',()=>{
 assert.equal(pendingLabel({pending_contracts:'10',pending_payout_state:'confirmed',pending_value:'10'}),'Confirmed payout $10.00');
 assert.match(pendingLabel({pending_contracts:'10',pending_payout_state:'estimated',pending_value:'7'}),/Estimated payout \$7.00.*unconfirmed/);
 assert.equal(pendingLabel({pending_contracts:'10',pending_payout_state:'unknown',pending_max_payout:'10'}),'Outcome unconfirmed · up to $10.00');
 assert.equal(pendingLabel({pending_contracts:'0'}),'No payment pending');
});
test('missing marks retain known account values and bound only unpriced contracts',()=>{
 const portfolio={cash:'80',deposits:'100',position_cost:'20',active_contracts:'20',pending_contracts:'0',
  equity:null,total_pnl:null,unrealized_pnl:null,position_value:null,active_value:null,realized_pnl:'0'};
 const positions=[{quantity:'10',value:'12',state:'active'},{quantity:'10',value:null,state:'active'}];
 assert.deepEqual(valueBounds(portfolio,positions),{low:12,high:22,unpriced:10});
 const html=accountMarkup({portfolio,quality:{},at:1000},1000,positions);
 for(const token of ['$92.00 to $102.00','-$8.00 to $2.00','10 contracts have no usable bid quote','not predicted payouts'])assert.ok(html.includes(token),token);
 assert.ok(!html.includes('class="positive'));
 assert.deepEqual(valueBounds(portfolio,[]),{low:0,high:20,unpriced:20});
 const bot=accountPnl({...portfolio,realized_pnl:'-2',position_cost:'10',active_contracts:'10'},[{quantity:'10',value:null}]);
 assert.equal(bot.text,'-$12.00 to -$2.00');assert.equal(bot.className,'negative');assert.equal(bot.uncertain,true);
});
test('shadow accounting freshness is visible when the worker snapshot stops updating',()=>{
 const data={portfolio:{pending_contracts:'0'},quality:{},at:1000};
 assert.ok(!accountMarkup(data,1029).includes('may be stale'));
 assert.match(accountMarkup(data,1031),/31 seconds old/);
});

// Execute strategy-folder rendering checks in the existing frontend CI job.
await import('./test_strategy_folders.mjs');

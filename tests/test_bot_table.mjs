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

import {BOT_DRAFT_KEY,createBotDraftStore,duplicateBotConfig,resolveBotDraft} from '../apps/web/bot-builder.mjs';
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

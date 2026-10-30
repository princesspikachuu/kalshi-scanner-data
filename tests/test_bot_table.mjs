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

import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {folderOverviewMarkup,folderPeriods} from '../apps/web/shadow-view.mjs';
const source=fs.readFileSync(new URL('../apps/web/shadow.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'').replace(/\nload\(\);\n/,'\n');
function fixture(){
 const empty={gross_profit:'0',fees:'0',net_realized_pnl:'0',win_rate:null,cycles:0,excluded_cycles:0};
 const ids=['complete_set','sequential','favorites','convexity'];
 return {version:'latest',connection_configured:true,status:{positions:[],orders:[]},health:{},
  folders:ids.map((id,i)=>({id,name:['Complete-Set Arbitrage','Sequential Spread Trading','High-Probability Favorites','Convexity · Paused'][i],description:'Test strategy',accounting:{at:Date.now()/1000,portfolio:{cash:'1000'}}})),
  bots:ids.map(id=>({id,folder_id:id,strategy:id,series:id==='complete_set'?'ALL_SAME_DAY':'KXBTC15M',name:id,desired:id==='convexity'?'paused':'running',revision:1,contracts:10,changed_at:0,metrics:{all:empty},account:{},
   experiment:id==='convexity'?undefined:{attempts:0,completed:0,unmatched:0,message:'Collecting evidence',calibration:id==='favorites'?[{band:'70–79¢',contracts:'0',win_rate:null,breakeven:null,net:'0'}]:[]}}))};
}
function setup(data){
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:true,textContent:'',innerHTML:'',showModal(){this.open=true},close(){this.open=false},files:[]});return nodes.get(id)};
 const context={document:{getElementById:node,querySelectorAll:()=>[]},fixture:data,setTimeout:()=>0,clearTimeout:()=>{},Date,Number,String,JSON,crypto:{randomUUID:()=> 'test-request-unique'},
  demoCall:async()=>({}),e:s=>String(s??'').replaceAll('<','&lt;'),escapeHTML:s=>s,
  botSummaryPeriodPreferences:()=>({}),botSummaryPeriodMarkup:()=>'<p>Period controls</p>',dollars:x=>x===null?'—':'$'+x,
  folderOverviewMarkup,folderPeriods,accountMarkup:()=>'<p>Paper account $1,000</p>',exposureMarkup:()=>'<p>No exposure</p>',accountPnl:()=>({className:'',text:'$0',uncertain:false})};
 vm.createContext(context);vm.runInContext(source+'\ndata=fixture;draw();',context);return {context,nodes};
}
test('paper dashboard renders four strategy folders, isolated reset buttons and favorites calibration',()=>{
 const {nodes}=setup(fixture()),html=nodes.get('groups').innerHTML;
 for(const name of ['Complete-Set Arbitrage','Sequential Spread Trading','High-Probability Favorites','Convexity · Paused'])assert.ok(html.includes(name));
 assert.equal((html.match(/data-folder-reset=/g)||[]).length,4);
 assert.ok(html.includes('Outcome win rate'));assert.ok(html.includes('Current paper session'));
 assert.ok(!html.includes('Estimated completion: NaN'));
});
test('untrained sequential estimates are labeled exploration rather than fabricated probabilities',()=>{
 const data=fixture();data.bots.find(b=>b.id==='sequential').experiment.decision={yes:'.45',no:'.45',mode:'paper_exploration',estimate:{samples:0,completion_probability:null}};
 const {nodes}=setup(data);assert.ok(nodes.get('groups').innerHTML.includes('Exploration: probabilities not established'));
});
test('frontend upgrade hides unsupported folder controls until the worker migration is present',()=>{
 const data=fixture();data.folders=[];data.bots=data.bots.filter(b=>b.id==='convexity');
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('waiting for the paper worker upgrade'));
 assert.ok(!html.includes('data-folder-reset='));assert.ok(!html.includes('data-folder-pause='));
});

test('top overview lists every folder with one shared set of period buttons',()=>{
 const data=fixture();for(const f of data.folders){f.accounting.portfolio.equity='1000';f.accounting.portfolio.total_pnl='0'}
 const {nodes}=setup(data),html=nodes.get('accountSummary').innerHTML;
 assert.equal((html.match(/data-folder-period=/g)||[]).length,6);
 for(const f of data.folders)assert.ok(html.includes(f.name));
 assert.ok(html.includes('Balance now'));assert.ok(html.includes('P/L · All'));
});
test('period overview uses deposit-adjusted history and labels incomplete coverage',()=>{
 const data=fixture();data.folders[0].performance={'1H':{pnl:'-2.50',partial:true,since:1700000000}};
 const html=folderOverviewMarkup(data.folders,'1H');
 assert.ok(html.includes('≈ -$2.50'));assert.ok(html.includes('Tracked since'));
 assert.ok(html.includes('Waiting for balance history'));
 assert.ok(html.includes('data-folder-period="1H" aria-pressed="true"'));
});
test('unpriced balances remain ranges rather than silently becoming zero',()=>{
 const html=folderOverviewMarkup([{id:'favorites',name:'Favorites',accounting:{at:Date.now()/1000,portfolio:{equity:null,cash:'900',deposits:'1000',total_pnl:null,realized_pnl:'0',position_cost:'100',active_contracts:'200',pending_contracts:'0',position_value:null},positions:[]}}]);
 assert.ok(html.includes('$900.00 to $1,100.00'));assert.ok(html.includes('-$100.00 to $100.00'));
});

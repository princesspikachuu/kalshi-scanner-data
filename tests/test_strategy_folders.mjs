import {scalperMarkup} from '../apps/web/scalper-view.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {marketTypeSummaryValues,marketTypeSummaryMarkup,marketTypeGroups,summaryExposure,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,favoriteTimingMarkup,favoriteCategoryRows,favoriteResearchMarkup,favoriteCategoryResearchMarkup} from '../apps/web/shadow-view.mjs';
import {proxyAuth} from '../apps/gateway/index.mjs';
const source=fs.readFileSync(new URL('../apps/web/shadow.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'').replace(/\nload\(\);\n/,'\n');
function fixture(){
 const empty={gross_profit:'0',fees:'0',net_realized_pnl:'0',win_rate:null,cycles:0,excluded_cycles:0};
 const ids=['complete_set','sequential','favorites','convexity'];
 return {version:'latest',connection_configured:true,status:{positions:[],orders:[]},health:{},
  folders:ids.map((id,i)=>({id,name:['Complete-Set Arbitrage','Sequential Spread Trading','High-Probability Favorites','Convexity · Paused'][i],description:'Test strategy',accounting:{at:Date.now()/1000,portfolio:{cash:'1000'}}})),
  bots:ids.map(id=>({id,folder_id:id,strategy:id,series:id==='complete_set'?'ALL_SAME_DAY':'KXBTC15M',name:id,desired:id==='convexity'?'paused':'running',revision:1,contracts:10,changed_at:0,metrics:{all:empty},account:{},
   experiment:id==='convexity'?undefined:{attempts:0,completed:0,unmatched:0,message:'Collecting evidence',calibration:id==='favorites'?[{band:'70–79¢',contracts:'0',win_rate:null,breakeven:null,net:'0'}]:[]}}))};
}
function setup(data,{storage=new Map(),queries={}}={}){
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:true,textContent:'',innerHTML:'',showModal(){this.open=true},close(){this.open=false},files:[]});return nodes.get(id)};
 const context={document:{getElementById:node,querySelectorAll:selector=>queries[selector]||[]},fixture:data,setTimeout:()=>0,clearTimeout:()=>{},Date,Number,String,JSON,crypto:{randomUUID:()=> 'test-request-unique'},
  demoCall:async()=>({}),e:s=>String(s??'').replaceAll('<','&lt;'),escapeHTML:s=>s,
  botSummaryPeriodPreferences:()=>({}),botSummaryPeriodMarkup:()=>'<p>Period controls</p>',dollars:x=>x===null?'—':'$'+x,
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
  scalperMarkup,marketTypeGroups,marketTypeSummaryMarkup,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,favoriteTimingMarkup,favoriteCategoryRows,favoriteResearchMarkup,favoriteCategoryResearchMarkup,accountMarkup:()=>'<p>Paper account $1,000</p>',exposureMarkup:()=>'<p>No exposure</p>',accountPnl:()=>({className:'',text:'$0',uncertain:false})};
 vm.createContext(context);vm.runInContext(source+'\ndata=fixture;draw();',context);return {context,nodes};
}
test('paper dashboard renders four strategy folders, isolated reset buttons and favorites calibration',()=>{
 const {nodes}=setup(fixture()),html=nodes.get('groups').innerHTML;
 for(const name of ['Complete-Set Arbitrage','Sequential Spread Trading','High-Probability Favorites','Convexity · Paused'])assert.ok(html.includes(name));
 assert.equal((html.match(/data-folder-reset=/g)||[]).length,4);
 assert.ok(html.includes('Outcome win rate'));assert.ok(html.includes('Current session'));
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
 assert.ok(html.includes('Open bids'));assert.ok(html.includes('Open/pending positions'));assert.ok(html.includes('P/L · All'));
});
test('period overview uses deposit-adjusted history and labels incomplete coverage',()=>{
 const data=fixture();data.folders[0].performance={'1H':{pnl:'-2.50',partial:true,since:1700000000}};
 const html=folderOverviewMarkup(data.folders,'1H');
 assert.ok(html.includes('≈ -$2.50'));assert.ok(html.includes('Tracked since'));
 assert.ok(html.includes('Waiting for balance history'));
 assert.ok(html.includes('data-folder-period="1H" aria-pressed="true"'));
});
test('unpriced current P/L uses cost fallback while committed position cost stays known',()=>{
 const html=folderOverviewMarkup([{id:'favorites',name:'Favorites',accounting:{at:Date.now()/1000,portfolio:{equity:null,cash:'900',deposits:'1000',total_pnl:null,realized_pnl:'0',position_cost:'100',active_contracts:'200',pending_contracts:'0',position_value:null},positions:[]}}]);
 assert.ok(html.includes('Open/pending positions'));assert.ok(html.includes('$100.00'));assert.ok(html.includes('$0.00'));assert.ok(!/\$[\d,.]+ to /.test(html));assert.ok(!html.includes('$900.00 to $1,100.00'));
});

test('retired fifteen-minute favorites are collapsed and cannot be resumed from their card',()=>{
 const data=fixture();const old={...data.bots.find(b=>b.id==='favorites'),id:'fav_old',name:'Old 15m favorite',retired:true,desired:'paused'};data.bots.push(old);
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('Retired 15-minute bots · 1'));
 assert.ok(html.includes('history and remaining exits'));
 assert.ok(!html.includes('data-toggle="fav_old"'));assert.ok(!html.includes('data-save="fav_old"'));
});
test('dashboard load renders the expanded workspace through the actual gateway contract',async()=>{
 const data={...fixture(),contract:'demo-v1',environment:'demo',installed:true};
 data.bots=Array.from({length:254},(_,i)=>({...data.bots[i%4],id:'bot-'+i,retired:i<28}));
 const {context,nodes}=setup(data);nodes.get('groups').innerHTML='';
 const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)};
 context.demoCall=async path=>{
  const response=await proxyAuth(new Request('https://app.test/api/demo/'+path),env,{fetcher:async()=>new Response(JSON.stringify(path.startsWith('shadow/events')?{contract:'demo-v1',items:[]}:data),{headers:{'content-type':'application/json'}})});
  const body=await response.json();if(!response.ok)throw Error(body.detail);return body;
 };
 await vm.runInContext('load()',context);
 for(const folder of data.folders)assert.ok(nodes.get('groups').innerHTML.includes(folder.name));
 assert.ok(nodes.get('accountSummary').innerHTML.includes('At a glance'));
 assert.equal(nodes.get('message')?.textContent||'','');
});
test('sequential comparison renders independent metrics and missing quote labels without a wide table',()=>{
 const comparison={started_at:100,attempts:10,first_fills:8,completed:7,completion_rate:7/8,realized_pnl:.2,net_pnl:null,unmatched_losses:.5,
  average_completion_seconds:120,dollar_hours:2,profit_per_dollar_hour:null,max_drawdown:.5,drawdown_incomplete:true,open_attempts:1,unpriced:true};
 const html=sequentialComparisonMarkup(['Baseline','Flexible','Adaptive'].map(name=>({name,comparison})));
 for(const name of ['Baseline','Flexible','Adaptive','earlier baseline history is excluded','quotes missing','unmatched attempts','dollar-hours'])assert.ok(html.includes(name),name);
 assert.ok(!html.includes('<table'));assert.ok(!html.includes('NaN'));assert.ok(!html.includes('Infinity'));
});

test('folders start closed with money and time controls in every summary',()=>{
 const data=fixture();for(const f of data.folders)f.accounting.portfolio={cash:'1000',equity:'1000',total_pnl:'0'};
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 assert.equal((html.match(/data-folder-summary-period=/g)||[]).length,24);
 for(const f of data.folders){assert.ok(html.includes('id="folder-'+f.id+'"'));assert.ok(!html.includes('id="folder-'+f.id+'" open'));}
 assert.ok(html.includes('folder-card-values'));assert.ok(html.includes('Open bids'));assert.ok(html.includes('Open/pending positions'));
});
test('folder open state survives polling and subsequent page initialization',()=>{
 const storage=new Map(),detail={dataset:{folder:'favorites'},open:false,isConnected:true};
 const data=fixture(),{context,nodes}=setup(data,{storage,queries:{'details[data-folder]':[detail]}});
 detail.open=true;detail.ontoggle();vm.runInContext('draw()',context);
 assert.match(nodes.get('groups').innerHTML,/id="folder-favorites" open data-folder/);
 assert.match(setup(data,{storage}).nodes.get('groups').innerHTML,/id="folder-favorites" open data-folder/);
 detail.open=false;detail.ontoggle();vm.runInContext('draw()',context);
 assert.doesNotMatch(nodes.get('groups').innerHTML,/id="folder-favorites" open data-folder/);
});
test('per-folder time controls do not open the folder and master controls reset all periods',()=>{
 const button={dataset:{summaryFolder:'favorites',folderSummaryPeriod:'1H'}},master={dataset:{folderPeriod:'6H'}},storage=new Map();
 const {context,nodes}=setup(fixture(),{storage,queries:{'[data-folder-summary-period]':[button],'[data-folder-period]':[master]}});
 let prevented=false,stopped=false;button.onclick({preventDefault(){prevented=true},stopPropagation(){stopped=true}});
 assert.ok(prevented&&stopped);assert.equal(JSON.parse(storage.get('moneytree-folder-views')).periods.favorites,'1H');
 assert.doesNotMatch(nodes.get('groups').innerHTML,/id="folder-favorites" open data-folder/);
 assert.ok(nodes.get('groups').innerHTML.includes('P/L · 1h'));
 assert.ok(nodes.get('accountSummary').innerHTML.includes('P/L · All'));
 master.onclick();assert.deepEqual(JSON.parse(storage.get('moneytree-folder-views')).periods,{});
 assert.ok(nodes.get('groups').innerHTML.includes('P/L · 6h'));
});
test('short-period P/L shows the best estimate and labels partial history',()=>{
 const data=fixture();data.folders[0].performance={'1H':{pnl:'2.65',pnl_low:'-4.25',pnl_high:'8.50',unpriced:true,realized_pnl:'2.10',partial:true,since:1700000000}};
 const html=folderOverviewMarkup(data.folders,'1H');
 assert.ok(html.includes('$2.65'));assert.ok(!html.includes(' to $'));assert.ok(html.includes('Realized $2.10'));
 assert.ok(!html.includes('range includes unpriced positions'));assert.ok(html.includes('Tracked since'));
 assert.ok(html.includes('data-label="Open bids"'));assert.ok(html.includes('data-label="Total P/L · 1h"'));
});

test('monitoring status distinguishes protected subscriptions, entry search and overload',()=>{
 const html=monitoringMarkup({subscribed_markets:20,position_and_exit_markets:12,entry_markets:8,total:32,entry_candidates:12,per_category:2,backlog:300,lag_p95_seconds:2.2,rotated_markets:5,categories:{hourly:2},reason:'Discovery paused: processing lag or read cooldown'});
 for(const text of ['20 watched','8 entry candidates','Protected monitoring','Discovery paused','2.20s','positions stay monitored','5 candidates rotated'])assert.ok(html.toLowerCase().includes(text.toLowerCase()),text);
 assert.ok(!html.includes('<table'));assert.ok(!html.includes('NaN'));
});

test('execution quality shows actual recovery receipts and missing legacy coverage honestly',()=>{
 assert.ok(executionMarkup(null).includes('next worker snapshot'));
 assert.ok(executionMarkup({measured:false}).includes('next worker snapshot'));
 const html=executionMarkup({measured:true,scope:'<script>bad</script>',data_valid:false,latency_ms:150,
  maker_fill_rate:'12.5',maker_filled:'25',maker_requested:'200',rejections:1,orders:3,
  partial_iocs:1,ioc_attempts:2,ioc_unfilled:'17',profit_contracts:'27',profit_net_proceeds:'10.3464',
  cycle_fees:'.4536',cycle_taker_slippage:'.01',partial_profit_price:'.40'});
 assert.ok(html.includes('25 / 200 · 12.5%'));
 assert.ok(html.includes('$10.35'));
 assert.ok(html.includes('data gap'));
 assert.ok(html.includes('cash receipts, not profit'));
 assert.ok(!html.includes('<script>'));
});

test('individual market cards start collapsed with name, P/L and state in their summary',()=>{
 const {nodes}=setup(fixture()),html=nodes.get('groups').innerHTML;
 assert.equal((html.match(/class="bot-card market-card"/g)||[]).length,4);
 assert.ok(html.includes('data-market="sequential" ><summary class="bot-top">'));
 assert.ok(html.includes('market-disclosure'));
 assert.ok(html.includes('Total P/L'));
 assert.ok(html.includes('data-toggle="sequential"')); // Controls remain available inside the expanded body.
});
test('each bot including experiments has six P/L windows visible while collapsed',()=>{
 const {nodes}=setup(fixture()),html=nodes.get('groups').innerHTML;
 for(const id of ['complete_set','sequential','favorites','convexity']){
  for(const p of ['all','1H','6H','24H','7D','30D'])assert.ok(html.includes(`data-bot-summary="${id}" data-summary-period="${p}"`),`${id} ${p}`);
 }
});
test('favorite timing research combines contract sides using percentage tiers',()=>{
 const row={series:'KXNBAGAME',market_type:'sports',side:'yes',price:'.90',horizon:'10–15m',clock:'estimated_game_end',contracts:'10',closed:'10',resolved:'10',winners:'9',cost:'9',net:'1',holding_seconds:'6000'};
 const html=favoriteTimingMarkup([row,{...row,side:'no',contracts:'5',closed:'5',resolved:'5',winners:'3',cost:'4.5',net:'-.5',holding_seconds:'3000'}]);
 for(const text of ['90–99%','10–15m','estimated game end','80.0%','$0.50','15'])assert.ok(html.includes(text),text);
 assert.equal((html.match(/<tbody><tr>/g)||[]).length,1);
 assert.ok(!html.includes(' · YES'));assert.ok(!html.includes(' · NO'));assert.ok(!html.includes('NaN'));
});
test('bot P/L separates total, realized and unrealized changes with honest coverage',()=>{
 const bot={id:'fav',account:{},performance:{'1H':{pnl:'2.5',realized_pnl:'1',partial:true,since:100}}};
 const html=botPnlMarkup(bot,'1H');
 for(const text of ['Total P/L change','Realized P/L change','Change in unrealized P/L','$2.50','$1.00','$1.50','Partial window'])assert.ok(html.includes(text),text);
 const missing=botPnlMarkup(bot,'7D');assert.ok(missing.includes('Waiting for balance history'));assert.ok(!missing.includes('NaN'));
});
test('experiment bot time selection changes its summary without opening its market',()=>{
 const button={dataset:{botSummary:'favorites',summaryPeriod:'6H'}},data=fixture();
 data.bots.find(b=>b.id==='favorites').performance={'6H':{pnl:'3',realized_pnl:'2',partial:false}};
 const {context,nodes}=setup(data,{queries:{'[data-bot-summary]':[button]}});let prevented=false,stopped=false;
 button.onclick({preventDefault(){prevented=true},stopPropagation(){stopped=true}});
 assert.ok(prevented&&stopped);assert.equal(vm.runInContext('periods.favorites',context),'6H');
 assert.ok(nodes.get('groups').innerHTML.includes('Last 6h'));assert.ok(nodes.get('groups').innerHTML.includes('$3.00'));
 assert.ok(nodes.get('groups').innerHTML.includes('data-market="favorites" ><summary'));
});
test('individual market state persists across polling and refresh, independently of its folder',()=>{
 const storage=new Map(),card={dataset:{market:'sequential'},open:true,isConnected:true};
 const {context}=setup(fixture(),{storage,queries:{'details[data-market]':[card]}});
 card.ontoggle({target:card});
 assert.deepEqual(JSON.parse(storage.get('moneytree-market-views')),['sequential']);
 assert.equal(storage.has('moneytree-folder-views'),false);
 vm.runInContext('draw()',context);
 const refreshed=setup(fixture(),{storage});
 assert.ok(refreshed.nodes.get('groups').innerHTML.includes('data-market="sequential" open'));
 assert.ok(refreshed.nodes.get('groups').innerHTML.includes('data-market="favorites" >'));
 card.open=false;card.ontoggle({target:card});
 assert.deepEqual(JSON.parse(storage.get('moneytree-market-views')),[]);
 card.open=true;card.isConnected=false;card.ontoggle({target:card});
 assert.deepEqual(JSON.parse(storage.get('moneytree-market-views')),[]);
});

test('closed folder summaries offer pause for running bots and resume for paused folders',()=>{
 const folder=fixture().folders.find(f=>f.id==='sequential');
 const running=folderCardSummaryMarkup(folder,'all',{bots:3,running:1});
 assert.ok(running.includes('data-folder-pause="sequential"'));
 assert.ok(running.includes('Pause all bots in Sequential Spread Trading'));
 assert.ok(folderCardSummaryMarkup(folder,'all',{bots:3,running:0}).includes('data-folder-resume="sequential"'));
 assert.ok(folderCardSummaryMarkup(folder,'all',{bots:3,running:1,pending:true}).includes('disabled>Saving…'));
 assert.ok(!folderCardSummaryMarkup(folder,'all',{bots:3,running:1,controls:false}).includes('data-folder-pause'));
});
test('summary pause targets only its folder without toggling it and reports preserved position management',async()=>{
 const button={dataset:{folderPause:'sequential'},disabled:false},storage=new Map(),calls=[];
 const {context,nodes}=setup(fixture(),{storage,queries:{'[data-folder-pause]':[button]}});
 context.demoCall=async(path,body)=>{
  calls.push({path,body});
  if(path==='shadow/bulk')return {saved:true};
  if(path.startsWith('shadow/workspace')){const next=fixture();next.installed=true;next.bots.find(b=>b.id==='sequential').desired='paused';return next}
  return {items:[]};
 };
 let prevented=0,stopped=0;
 await button.onclick({preventDefault(){prevented++},stopPropagation(){stopped++}});
 const mutations=calls.filter(c=>c.body);
 assert.equal(mutations.length,1);
 assert.deepEqual(JSON.parse(JSON.stringify(mutations[0])),{path:'shadow/bulk',body:{action:'pause',folder_id:'sequential'}});
 assert.equal(prevented,1);assert.equal(stopped,1);
 assert.equal(storage.has('moneytree-folder-views'),false);
 assert.ok(nodes.get('message').textContent.includes('continues managing existing positions'));
 assert.ok(nodes.get('groups').innerHTML.includes('data-folder-resume="sequential"'));
});


test('overview, folder and bot headers separate current reserved bids from committed position costs',()=>{
 const account={equity:'1000',cash:'993.5',total_pnl:'3',realized_pnl:'1',unrealized_pnl:'2',
  unfilled_bids:'2',active_cost:'3',pending_cost:'1.5',position_cost:'4.5',active_value:'500',pending_value:'500'};
 const folder={id:'favorites',name:'Favorites',accounting:{at:Date.now()/1000,portfolio:account},performance:{'1H':{pnl:'1',partial:false}}};
 for(const html of [folderOverviewMarkup([folder],'1H'),folderCardSummaryMarkup(folder,'1H',{bots:1,running:1}),
  botPnlMarkup({id:'fav',account,performance:{'1H':{pnl:'1',realized_pnl:'.5'}}},'1H')]){
  for(const text of ['Total P/L','Open bids','Open/pending positions','$2.00','$4.50','Open $3.00 · pending $1.50','includes entry fees'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('$1,000.00'));assert.ok(!html.includes('$500.00'));
 }
 assert.deepEqual(summaryExposure(account),{bids:2,active:3,pending:1.5,positions:4.5});
});
test('exposure summaries distinguish unknown amounts from known zero and support combined cost snapshots',()=>{
 assert.deepEqual(summaryExposure(null),{bids:null,active:null,pending:null,positions:null});
 assert.deepEqual(summaryExposure({unfilled_bids:'0',active_cost:'0',pending_cost:'0'}),{bids:0,active:0,pending:0,positions:0});
 assert.equal(summaryExposure({position_cost:'7'}).positions,7);
 const html=botPnlMarkup({id:'test',account:{unfilled_bids:'0'},performance:{}},'1H');
 assert.ok(html.includes('$0.00'));assert.ok(html.includes('Waiting for balance history'));assert.ok(!html.includes('NaN'));
});

test('market type grouping partitions the full legacy registry and keeps hourly, weather and sports separate',()=>{
 const legacy=JSON.parse(fs.readFileSync(new URL('../services/paper_demo/shadow/market_profiles.json',import.meta.url),'utf8'));
 const extra=[{id:'hourbtc',series:'KXBTCD',asset:'hourly'},{id:'hourfx',series:'KXUSDCADAH',asset:'hourly'},
  {id:'hourmetal',series:'KXGOLDH',asset:'hourly'},{id:'weather',asset:'weather'},
  {id:'daily',asset:'weather_daily'},{id:'sports',asset:'sports'},
  {id:'scanner',strategy:'complete_set',series:'ALL_SAME_DAY'},{id:'unknown',series:'NEW_TYPE'}];
 const groups=marketTypeGroups([...legacy,...extra]);
 assert.deepEqual(groups.filter(g=>g.id.endsWith('-15m')).map(g=>[g.id,g.bots.length]),[
  ['crypto-15m',9],['commodities-15m',8],['finance-15m',11]]);
 for(const id of ['crypto-hourly','commodities-hourly','finance-hourly','weather-hourly','weather-daily','sports','complete-sets','other'])assert.ok(groups.some(g=>g.id===id),id);
 const ids=groups.flatMap(g=>g.bots.map(b=>b.id));assert.equal(ids.length,legacy.length+extra.length);
 assert.equal(new Set(ids).size,ids.length);
});
test('market type subfolders remember state independently per strategy and search does not overwrite preferences',()=>{
 const storage=new Map(),detail={dataset:{marketType:'favorites::crypto-15m'},open:true,isConnected:true};
 const data=fixture(),{context,nodes}=setup(data,{storage,queries:{'details[data-market-type]':[detail]}});
 assert.ok(nodes.get('groups').innerHTML.includes('data-market-type="favorites::crypto-15m" >'));
 detail.ontoggle({target:detail});
 assert.deepEqual(JSON.parse(storage.get('moneytree-market-type-views')),['favorites::crypto-15m']);
 const html=setup(data,{storage}).nodes.get('groups').innerHTML;
 assert.ok(html.includes('data-market-type="favorites::crypto-15m" open'));
 assert.ok(html.includes('data-market-type="sequential::crypto-15m" >'));
 assert.equal(storage.has('moneytree-folder-views'),false);assert.equal(storage.has('moneytree-market-views'),false);
 detail.open=false;detail.ontoggle({target:detail});
 nodes.get('find').value='btc';vm.runInContext('draw()',context);
 assert.ok(nodes.get('groups').innerHTML.includes('data-market-type="sequential::crypto-15m" open'));
 detail.open=true;detail.ontoggle({target:detail});
 assert.deepEqual(JSON.parse(storage.get('moneytree-market-type-views')),[]);
 nodes.get('find').value='';vm.runInContext('draw()',context);
 assert.ok(nodes.get('groups').innerHTML.includes('data-market-type="favorites::crypto-15m" >'));
});

test('subfolder totals combine bot P/L and current exposure across the selected window',()=>{
 const bots=[{id:'a',desired:'running',account:{total_pnl:'5',unfilled_bids:'1',active_cost:'2',pending_cost:'1'},performance:{'1H':{pnl:'1',partial:true}}},
  {id:'b',desired:'paused',account:{total_pnl:'-2',unfilled_bids:'2',active_cost:'3',pending_cost:'4'},performance:{'1H':{pnl:'-.5'}}}];
 const all=marketTypeSummaryValues(bots),hour=marketTypeSummaryValues(bots,'1H');
 assert.equal(all.pnl.low,3);assert.equal(all.pnl.high,3);
 assert.equal(hour.pnl.low,.5);assert.equal(hour.partial,true);
 assert.deepEqual(hour.account,{unfilled_bids:3,active_cost:5,pending_cost:5,position_cost:10});
 const html=marketTypeSummaryMarkup({label:'Crypto',bots},'1H');
 for(const token of ['Total P/L · 1h','$0.50','Open bids','$3.00','Open/pending positions','$10.00','Partial P/L history'])assert.ok(html.includes(token),token);
});
test('subfolder P/L uses single estimates and does not silently omit missing bots',()=>{
 const bots=[{id:'a',account:{},performance:{'6H':{pnl:'.5',pnl_low:'-1',pnl_high:'2'}}},
  {id:'b',account:{},performance:{'6H':{pnl:'1'}}}];
 assert.deepEqual(marketTypeSummaryValues(bots,'6H').pnl,{low:1.5,high:1.5,unpriced:false});
 bots[1].performance={};
 const v=marketTypeSummaryValues(bots,'6H');assert.equal(v.pnl,null);assert.equal(v.missing,1);
 assert.equal(v.account.unfilled_bids,null);
 const html=marketTypeSummaryMarkup({label:'Crypto',bots},'6H');
 assert.ok(html.includes('1 bot missing P/L history'));assert.ok(!html.includes('NaN'));
});
test('search keeps full market-type totals and subfolders follow their parent P/L window',()=>{
 const data=fixture(),btc=data.bots.find(b=>b.id==='favorites');
 btc.account={total_pnl:'3',unfilled_bids:'1',active_cost:'1',pending_cost:'0'};
 btc.performance={'1H':{pnl:'1'}};
 data.bots.push({...btc,id:'eth-fav',series:'KXETH15M',name:'Ethereum',account:{...btc.account,total_pnl:'7'},performance:{'1H':{pnl:'2'}}});
 const {context,nodes}=setup(data);nodes.get('find').value='KXBTC';vm.runInContext('draw()',context);
 const header=()=>{const html=nodes.get('groups').innerHTML,start=html.indexOf('data-market-type="favorites::crypto-15m"');return html.slice(start,html.indexOf('<div class="bot-list">',start))};
 assert.ok(header().includes('$10.00'));assert.ok(header().includes('2 bots · 2 running · 1 shown'));
 vm.runInContext("folderSummaryPeriods.favorites='1H';draw()",context);
 assert.ok(header().includes('Total P/L · 1h'));assert.ok(header().includes('$3.00'));
});

test('balances and folders render before a stalled activity request finishes',async()=>{
 const {context,nodes}=setup(fixture());
 nodes.get('groups').innerHTML='';let finishActivity;
 const next=fixture();next.installed=true;next.folders[0].name='Freshly loaded folder';
 context.demoCall=async path=>path.startsWith('shadow/workspace')?next:new Promise(resolve=>{finishActivity=resolve});
 const pending=vm.runInContext('load()',context);
 await new Promise(setImmediate);
 assert.ok(nodes.get('groups').innerHTML.includes('Freshly loaded folder'));
 finishActivity({items:[]});await pending;
});
test('failed initial requests replace the checking status and remain retryable',async()=>{
 const {context,nodes}=setup(fixture());vm.runInContext('data=undefined',context);
 context.demoCall=async()=>{throw Error('Demo data request timed out. Please retry.')};
 await vm.runInContext('load()',context);
 assert.equal(nodes.get('health').textContent,'Dashboard data unavailable');
 assert.ok(nodes.get('accountSummary').innerHTML.includes('Retrying automatically'));
 assert.ok(nodes.get('message').textContent.includes('timed out'));
});


test('category research pools series and both sides while keeping price and time tiers distinct',()=>{
 const base={series:'KXBTCD',market_type:'hourly_price',side:'yes',clock:'market_close',horizon:'5–10m',price:'.90',contracts:'10',closed:'10',resolved:'10',winners:'9',cost:'9.1',net:'-.1'};
 const input=[base,{...base,series:'KXETHD',side:'no',price:'.95',contracts:'2',closed:'2',resolved:'2',winners:'2',cost:'1.9',net:'.1'},{...base,horizon:'1–2h'}];
 const rows=favoriteCategoryRows(input,true);assert.equal(rows.length,2);
 const r=rows.find(r=>r.horizon==='5–10m');assert.equal(r.band,'90–99%');assert.equal(r.contracts,12);assert.equal(r.winners,11);assert.equal(r.cost,11);assert.equal(r.net,0);
 const html=favoriteCategoryResearchMarkup({id:'crypto-hourly',label:'Crypto · 1 hour',bots:input.map((r,i)=>({id:String(i),experiment:{entry_timing:[r]}}))});
 assert.ok(html.includes('91.7%'));assert.ok(!html.includes('KXBTCD'));assert.ok(!html.includes('KXETHD'));assert.ok(!html.includes(' · YES'));assert.ok(!html.includes(' · NO'));
 assert.equal(favoriteCategoryResearchMarkup({id:'sports',bots:[]}), '');
});
test('Favorites research sits within each non-sports category and keeps pending outcomes honest',()=>{
 const d=fixture(),bot=d.bots.find(b=>b.id==='favorites');bot.name='<img onerror=x>';
 bot.experiment.entry_timing=[{series:bot.series,market_type:'15m_price',side:'yes',clock:'market_close',horizon:'10–15m',price:'.90',contracts:'4',closed:'0',resolved:'0',winners:'0',cost:'3.6',net:'0'}];
 const {nodes}=setup(d),html=nodes.get('groups').innerHTML;
 for(const text of ['Combined data · time × percentage tier','90–99%','10–15m left','no closed contracts','Bids are still gathering data','independent of the P/L time selector'])assert.ok(html.includes(text),text);
 assert.ok(!html.includes('<img onerror'));assert.ok(!html.includes('NaN'));
 const group=html.indexOf('data-market-type="favorites::crypto-15m"'),research=html.indexOf('Combined data',group),card=html.indexOf('data-market="favorites"',group);
 assert.ok(group<research&&research<card);
});
test('category research expansion survives refresh and reload',()=>{
 const key='favorites-category-crypto-15m',detail={dataset:{research:key},open:true,isConnected:true},storage=new Map();
 const {context}=setup(fixture(),{storage,queries:{'details[data-research]':[detail]}});
 detail.ontoggle({target:detail});vm.runInContext('draw()',context);
 assert.equal(storage.get('moneytree-research-views'),JSON.stringify([key]));
 const {nodes}=setup(fixture(),{storage});assert.match(nodes.get('groups').innerHTML,/data-research="favorites-category-crypto-15m" open/);
});

test('scalper folders render research with escaped records and existing period controls',()=>{
 const data=fixture(),base=data.bots[1];
 data.folders.push({id:'volatility_scalper',name:'Volatility Scalper',description:'Paper only'});
 data.bots.push({...base,id:'scalper_btc',series:'KXBTC15M',name:'BTC',folder_id:'volatility_scalper',strategy:'volatility_scalper',experiment:{message:'Paper entry submitted',scalper:{totals:{completed:2,win_rate:50,average_net:.01,rejections:{spread_or_depth:2}},config:{approach:'mean_reversion'},cells:[],recent:[{ticker:'<script>bad</script>',side:'yes',entered_at:100,exit_at:200,net:.02,verified:true}]}}});
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 for(const value of ['Volatility Scalper','Completed round trips','Candidate observations','data-folder-summary-period=']){
   assert.ok(html.includes(value),value);
 }
 assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));assert.ok(!html.includes('<script>bad'));
 assert.ok(!html.includes('NaN'));assert.ok(!html.includes('Infinity'));
});

test('a recovered workspace read clears its stale transport error without removing action messages',async()=>{
 const {context,nodes}=setup(fixture());
 context.demoCall=async()=>{throw Error('Dashboard response was interrupted or changed in transit. Please use Reload data.')};
 await vm.runInContext('load()',context);assert.match(nodes.get('message').textContent,/interrupted/);
 const next={...fixture(),installed:true};
 context.demoCall=async path=>path.startsWith('shadow/workspace')?next:{items:[]};
 await vm.runInContext('load()',context);assert.equal(nodes.get('message').textContent,'');
 vm.runInContext("note('Saved bot settings')",context);
 await vm.runInContext('load()',context);assert.equal(nodes.get('message').textContent,'Saved bot settings');
});

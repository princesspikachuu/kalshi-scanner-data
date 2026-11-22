import {scalperMarkup} from '../apps/web/scalper-view.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {marketTypeSummaryValues,marketTypeSummaryMarkup,marketTypeGroups,summaryExposure,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,botPnlDetailsMarkup,favoriteTimingMarkup,favoriteCategoryRows,favoriteResearchMarkup,favoriteCategoryResearchMarkup,favoriteStatisticsMatrixMarkup,favoriteCollectorOverviewMarkup,favoriteProfitLegendMarkup,favoriteTableSettingsMarkup,favoriteForwardValidationMarkup,favoriteWideOverviewMarkup,favoriteSingleOverviewMarkup,favoriteSingleCellMarkup,favoriteBucketKey,favoriteBucketStarMarkup,winConfidence90,favoriteEvidenceTier,learningDiagnosticsMarkup,filledEventsSmall} from '../apps/web/shadow-view.mjs';
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
 const listeners=new Map();
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:true,textContent:'',innerHTML:'',showModal(){this.open=true},close(){this.open=false},files:[]});return nodes.get(id)};
 const context={document:{getElementById:node,querySelectorAll:selector=>queries[selector]||[],addEventListener:(type,callback)=>listeners.set(type,callback)},fixture:data,setTimeout:()=>0,clearTimeout:()=>{},Date,Number,String,JSON,crypto:{randomUUID:()=> 'test-request-unique'},
  demoCall:async()=>({}),e:s=>String(s??'').replaceAll('<','&lt;'),escapeHTML:s=>s,
  botSummaryPeriodPreferences:()=>({}),botSummaryPeriodMarkup:()=>'<p>Period controls</p>',dollars:x=>x===null?'—':'$'+x,
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
  scalperMarkup,marketTypeGroups,marketTypeSummaryMarkup,executionMarkup,folderOverviewMarkup,folderPeriods,folderCardSummaryMarkup,sequentialComparisonMarkup,monitoringMarkup,botPnlMarkup,botPnlDetailsMarkup,favoriteTimingMarkup,favoriteCategoryRows,favoriteResearchMarkup,favoriteCategoryResearchMarkup,favoriteStatisticsMatrixMarkup,favoriteCollectorOverviewMarkup,favoriteProfitLegendMarkup,favoriteTableSettingsMarkup,favoriteForwardValidationMarkup,favoriteWideOverviewMarkup,favoriteSingleOverviewMarkup,favoriteSingleCellMarkup,favoriteBucketKey,favoriteBucketStarMarkup,winConfidence90,favoriteEvidenceTier,learningDiagnosticsMarkup,accountMarkup:()=>'<p>Paper account $1,000</p>',exposureMarkup:()=>'<p>No exposure</p>',accountPnl:()=>({className:'',text:'$0',uncertain:false})};
 vm.createContext(context);vm.runInContext(source+'\ndata=fixture;draw();',context);return {context,nodes,listeners};
}
test('historical query degradation still renders Favorites portfolio and research notice',async()=>{
 const d=fixture();
 d.installed=true;
 d.historical_metrics_delayed=true;
 d.health={message:'Current worker ready'};
 const {context,nodes}=setup(d);
 context.demoCall=async path=>{
  if(path.startsWith('shadow/workspace'))return d;
  if(path==='shadow/events')return {items:[]};
  if(path==='shadow/research-folder/favorites')return {bots:{}};
  return {tracked:false};
 };
 vm.runInContext('lastRestartRefresh=Date.now()',context);
 await vm.runInContext('load()',context);
 assert.match(nodes.get('groups').innerHTML,/High-Probability Favorites/);
 assert.match(nodes.get('accountSummary').innerHTML,/At a glance/);
 assert.match(nodes.get('health').textContent,/historical reports delayed/);
 assert.match(nodes.get('message').textContent,/Current portfolio balances and Favorites research are available/);
});

test('collapsed recent activity does not issue costly history requests during Favorites polling',async()=>{
 const d=fixture();d.installed=true;
 const calls=[],{context,nodes}=setup(d);
 context.demoCall=async path=>{
  calls.push(path);
  if(path.startsWith('shadow/workspace'))return d;
  if(path==='shadow/research-folder/favorites')return {bots:{}};
  if(path==='shadow/events')return {items:[]};
  return {tracked:false};
 };
 vm.runInContext('lastRestartRefresh=Date.now()',context);
 await vm.runInContext('load()',context);
 assert.equal(calls.filter(path=>path==='shadow/events').length,0);
 const activity=nodes.get('activity');
 activity.open=true;await activity.ontoggle();
 assert.equal(calls.filter(path=>path==='shadow/events').length,1);
 await vm.runInContext('refreshRecentActivity()',context);
 assert.equal(calls.filter(path=>path==='shadow/events').length,1,'an open panel is throttled');
 activity.open=false;await vm.runInContext('refreshRecentActivity(true)',context);
 assert.equal(calls.filter(path=>path==='shadow/events').length,1,'closed activity never queries history');
});

test('Data Learning panel distinguishes active learning from diagnostics-only and operational strategies',()=>{
 const data=fixture();
 data.folders[0].learning={classification:'operational_only',state:'not_learning',observations:4,settled_observations:2,open_observations:2,bot_count:1,decisions:'No historical model currently changes set execution',segments:'event/set execution records',minimum:'Not applicable',fallback:'Current executable-cost and coverage rules',features:['executable set cost','fees']};
 data.folders[1].learning={classification:'data_learning',state:'using_statistics_now',observations:22,settled_observations:15,open_observations:7,bot_count:1,decisions:'Entry pair selection, completion likelihood and expected net return',segments:'series × time bucket × prices',minimum:'20 matching settled attempts',fallback:'1-contract paper exploration',features:['entry leg prices','pair completion']};
 data.folders[2].learning={classification:'data_learning',state:'using_statistics_now',observations:9,settled_observations:4,open_observations:5,bot_count:1,decisions:'Entry value ceiling',segments:'market type × price × time',minimum:'settled evidence',fallback:'paper-data collection',features:['entry price','time remaining']};
 data.folders[3].learning={classification:'future_learning_candidate',state:'paused_history',observations:0,settled_observations:0,open_observations:0,bot_count:1,decisions:'Historical results preserved',segments:'legacy history',minimum:'No active learning threshold',fallback:'Paused; history only',features:['P/L']};
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('Data / Learning · Operational-only strategy'));
 assert.ok(html.includes('Data / Learning · Data-learning strategy'));
 assert.ok(html.includes('Data / Learning · Future-learning candidate'));
 assert.ok(html.includes('20 matching settled attempts'));
 assert.ok(html.includes('Using collected evidence now'));
});

test('paper dashboard renders four strategy folders, isolated reset buttons and favorites calibration',()=>{
 const {nodes}=setup(fixture()),html=nodes.get('groups').innerHTML;
 assert.equal((html.match(/class="small favorite-profit-legend"/g)||[]).length,1);
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

test('top overview lists only running folders with one shared set of period buttons',()=>{
 const data=fixture();for(const f of data.folders){f.accounting.portfolio.equity='1000';f.accounting.portfolio.total_pnl='0'}
 const {nodes}=setup(data),html=nodes.get('accountSummary').innerHTML;
 assert.equal((html.match(/data-folder-period=/g)||[]).length,6);
 for(const f of data.folders.filter(f=>f.id!=='convexity'))assert.ok(html.includes(f.name));
 assert.ok(!html.includes('Convexity · Paused'));
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
  const response=await proxyAuth(new Request('https://app.test/api/demo/'+path),env,{fetcher:async()=>new Response(JSON.stringify(path.startsWith('shadow/events')?{contract:'demo-v1',items:[]}:path.startsWith('shadow/research-folder/')?{contract:'demo-v1',bots:{}}:data),{headers:{'content-type':'application/json'}})});
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
 assert.ok(html.includes('folder-card-values'));assert.ok(html.includes('>Bids</span>'));assert.ok(html.includes('Positions · cost'));
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
test('favorite timing research counts outcomes by event rather than contract quantity',()=>{
 const row={series:'KXNBAGAME',market_type:'sports',side:'yes',price:'.90',horizon:'10–15m',clock:'estimated_game_end',contracts:'10',closed:'10',resolved:'10',winners:'10',cost:'9',net:'1',holding_seconds:'6000',events:1,event_win_rate:100};
 const html=favoriteTimingMarkup([row,{...row,side:'no',contracts:'5',closed:'5',resolved:'5',winners:'5',cost:'4.5',net:'.5',holding_seconds:'3000'}]);
 for(const text of ['90–94¢','10–15m','estimated game end','n=2','100.0%'])assert.ok(html.includes(text),text);
 assert.equal((html.match(/<tbody><tr(?:\s[^>]*)?>/g)||[]).length,1);
 assert.match(html,/n=2/);
 assert.ok(!html.includes(' · YES'));assert.ok(!html.includes(' · NO'));assert.ok(!html.includes('NaN'));
});
test('bot P/L separates total, realized and unrealized changes with honest coverage',()=>{
 const bot={id:'fav',account:{},performance:{'1H':{pnl:'2.5',realized_pnl:'1',partial:true,since:100}}};
 const html=botPnlDetailsMarkup(bot,'1H');
 for(const text of ['Total P/L change','Realized P/L change','Change in unrealized P/L','$2.50','$1.00','$1.50','Partial window'])assert.ok(html.includes(text),text);
 const missing=botPnlDetailsMarkup(bot,'7D');assert.ok(missing.includes('Waiting for balance history'));assert.ok(!missing.includes('NaN'));
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
test('expanded account, diagnostics and market panels survive redraw and stay scoped',()=>{
  const panels=[
    {dataset:{uiPanel:'market:favorites:money'},open:true},
    {dataset:{uiPanel:'market:sequential:money'},open:false},
    {dataset:{uiPanel:'folder:favorites:research'},open:true},
    {dataset:{uiPanel:'global:diagnostics'},open:true},
    {dataset:{uiPanel:'market:favorites:timing'},open:true}
  ];
  const {context}=setup(fixture(),{queries:{'details[data-ui-panel]':panels}});
  const expanded=vm.runInContext('expandedDashboardPanels()',context);
  assert.equal(expanded.size,4);
  context.savedExpandedPanels=expanded;
  panels.forEach(p=>p.open=false);
  vm.runInContext('restoreDashboardPanels(savedExpandedPanels)',context);
  assert.equal(panels[0].open,true);
  assert.equal(panels[1].open,false,'another market stays closed');
  assert.equal(panels[2].open,true);
  assert.equal(panels[3].open,true);
  assert.equal(panels[4].open,true);
  vm.runInContext('draw()',context);
  assert.equal(panels[4].open,true);
});

test('all key second-level panels have stable market and folder identities',()=>{
  const data=fixture();
  data.bots.find(bot=>bot.id==='favorites').experiment.entry_timing=[
    {series:'KXBTC15M',market_type:'15m_price',clock:'market_close',
     price:'.8',horizon:'5–10m',events:1,event_wins:1,
     contracts:1,cost:.8,return_sum:.25,return_observations:1}
  ];
  const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
  for(const key of ['folder:favorites:account','folder:favorites:research',
   'folder:favorites:diagnostics','market:favorites:money',
   'market:favorites:stats','market:favorites:lots',
   'market:favorites:timing','market:sequential:money']){
    assert.ok(html.includes('data-ui-panel="'+key+'"'),key);
  }
  assert.ok(nodes.get('diagnostics').innerHTML.includes('data-ui-panel="global:diagnostics"'));
});

test('all three Favorites modes retain the market timing panel identity',()=>{
  const sample={resolved_events:2,event_wins:1,return_observations:2,
    average_return_pct:'4',uncertainty90_pct:'1',ci90_low_pct:'3',
    ci90_high_pct:'5',incomplete_events:0};
  const rows=[{series:'KXBTC15M',market_type:'15m_price',clock:'market_close',
    price:'.8',horizon:'5–10m',events:2,event_wins:1,
    contracts:2,cost:1.6,return_sum:.08,return_observations:2}];
  const wideRows=[{...rows[0],band:'78–<86¢',time_slot:1}];
  for(const mode of ['detailed','wide','single']){
    const html=favoriteTimingMarkup(rows,mode==='wide'?wideRows:null,
      {mode,single:sample,panelKey:'market:btc:timing'});
    assert.match(html,/data-ui-panel="market:btc:timing"/);
    if(mode==='single')assert.match(html,/favorite-single-matrix/);
    else assert.match(html,/favorite-stat-matrix/);
  }
  const escaped=favoriteTimingMarkup(rows,null,{panelKey:'bad" onfocus="x'});
  assert.doesNotMatch(escaped,/data-ui-panel="bad" onfocus/);
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
  if(path==='shadow/research-folder/favorites')return {bots:{}};
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
  botPnlDetailsMarkup({id:'fav',account,performance:{'1H':{pnl:'1',realized_pnl:'.5'}}},'1H')]){
  for(const text of ['Total P/L','$2.00','$4.50','Open $3.00 · pending $1.50'])assert.ok(html.includes(text),text); assert.ok(html.includes('Bids')||html.includes('Open bids'));
  // Current portfolio value is intentionally visible; exposure remains cost-based.
  if(html.includes('Estimated portfolio value'))assert.ok(html.includes('$1,000.00'));
  assert.ok(!html.includes('Open $500.00'));
 }
 assert.deepEqual(summaryExposure(account),{bids:2,active:3,pending:1.5,positions:4.5});
});
test('event monitoring counts each underlying event once per exposure status',()=>{
 const a={equity:'1000',cash:'990',total_pnl:'0',unfilled_bids:'2',active_cost:'3',pending_cost:'1.5',
  unfilled_bid_events:2,active_events:1,pending_events:1,position_cost:'4.5'};
 const f={id:'favorites',name:'Favorites',accounting:{at:Date.now()/1000,portfolio:a}};
 const htmls=[folderOverviewMarkup([f]),folderCardSummaryMarkup(f,'all',{bots:1,running:1}),
  botPnlDetailsMarkup({id:'b',account:a,performance:{}},'all')];
 for(const html of htmls){
  assert.ok(html.includes('$2.00 (2 events)'),html);
  assert.ok(html.includes('Open $3.00 (1 event) · pending $1.50 (1 event)'),html);
 }
 const typeBots=[{id:'b',desired:'running',account:a,performance:{}},
  {id:'c',desired:'running',account:{unfilled_bids:'1',active_cost:'2',pending_cost:'0'},performance:{}}];
 const positions=[{ticker:'S-A',bot_id:'b',event_ticker:'EVENT-ONE',state:'active'},
  {ticker:'S-B',bot_id:'c',event_ticker:'EVENT-ONE',state:'active'},
  {ticker:'S-C',bot_id:'b',event_ticker:'EVENT-TWO',state:'pending'}];
 const orders=[{ticker:'S-A',bot_id:'b',event_ticker:'EVENT-ONE',action:'buy',status:'resting'},
  {ticker:'S-D',bot_id:'c',event_ticker:'EVENT-ONE',action:'buy',status:'pending'},
  {ticker:'S-E',bot_id:'c',event_ticker:'EVENT-THREE',action:'sell',status:'resting'}];
 const typeHtml=marketTypeSummaryMarkup({label:'Crypto',bots:typeBots},'all',positions,null,orders);
 assert.ok(typeHtml.includes('$3.00 (1 event)'),typeHtml);
 assert.ok(typeHtml.includes('Open $5.00 (1 event) · pending $1.50 (1 event)'),typeHtml);
});
test('older worker snapshots derive visible event counts without a backend deploy',()=>{
 const d=fixture();
 const f=d.folders.find(x=>x.id==='favorites'),bot=d.bots.find(x=>x.folder_id==='favorites');
 f.accounting.portfolio={cash:'992',equity:'1000',total_pnl:'0',
  unfilled_bids:'2',active_cost:'3',pending_cost:'1.5'};
 f.accounting.positions=[
  {ticker:'KXFED-26NOV21-YES',bot_id:bot.id,state:'active',side:'yes',quantity:1,cost:'1',value:'1',phase_origin:1},
  {ticker:'KXFED-26NOV21-NO',bot_id:bot.id,state:'active',side:'no',quantity:1,cost:'2',value:'2',phase_origin:1},
  {ticker:'KXJOB-26NOV21-YES',bot_id:bot.id,state:'pending',side:'yes',quantity:1,cost:'1.5',value:'1',phase_origin:1}];
 f.accounting.orders=[
  {ticker:'KXFED-26NOV21-YES',bot_id:bot.id,side:'yes',action:'buy',status:'resting',maker:true,quantity:1,price:'.7',reserved:'.7'},
  {ticker:'KXFED-26NOV21-NO',bot_id:bot.id,side:'no',action:'buy',status:'pending',maker:true,quantity:1,price:'.8',reserved:'.8'},
  {ticker:'KXJOB-26NOV21-YES',bot_id:bot.id,side:'yes',action:'sell',status:'resting',maker:true,quantity:1,price:'.9',reserved:'0'}];
 bot.account={unfilled_bids:'2',active_cost:'3',pending_cost:'1.5'};
 const {context,nodes}=setup(d);
 context.hydrateEventCounts(d);
 context.draw();
 assert.equal(f.accounting.portfolio.unfilled_bid_events,1);
 assert.equal(f.accounting.portfolio.active_events,1);
 assert.equal(f.accounting.portfolio.pending_events,1);
 assert.equal(bot.account.unfilled_bid_events,1);
 const overview=nodes.get('accountSummary').innerHTML;
 assert.ok(overview.includes('$2.00 (1 event)'),overview);
 assert.ok(overview.includes('Open $3.00 (1 event) · pending $1.50 (1 event)'),overview);
 const group=nodes.get('groups').innerHTML;
 assert.ok(group.includes('$2.00 (1 event)'),group);
});
test('event hydration respects true provider counts, removes invalid zero guesses, and uses current snapshot fallback',()=>{
 const d=fixture(),f=d.folders.find(x=>x.id==='favorites');
 f.accounting.portfolio={unfilled_bids:'3',active_cost:'0',pending_cost:'5',unfilled_bid_events:9};
 f.accounting.orders=[{ticker:'KXTEMP-26NOV21-70',bot_id:'favorites',side:'yes',quantity:1,price:'.7',reserved:'.7',maker:true,action:'buy',status:'resting'}];
 const {context}=setup(d);
 context.hydrateEventCounts(d);
 assert.equal(f.accounting.portfolio.unfilled_bid_events,9);
 assert.equal(f.accounting.portfolio.active_events,0);
 assert.equal(f.accounting.portfolio.pending_events,undefined);
 const fallback={folders:[{id:'favorites',accounting:{portfolio:{unfilled_bids:'2',active_cost:'0',pending_cost:'0'},
  positions:[],orders:[{ticker:'KXTEMP-26NOV21-70',action:'buy',status:'resting'},{ticker:'KXTEMP-26NOV21-65',action:'buy',status:'resting'}]}}]};
 context.hydrateEventCounts(fallback);
 assert.equal(fallback.folders[0].accounting.portfolio.unfilled_bid_events,1);
 assert.equal(fallback.folders[0].accounting.portfolio.pending_events,0);
});
test('exposure summaries distinguish unknown amounts from known zero and support combined cost snapshots',()=>{
 assert.deepEqual(summaryExposure(null),{bids:null,active:null,pending:null,positions:null});
 assert.deepEqual(summaryExposure({unfilled_bids:'0',active_cost:'0',pending_cost:'0'}),{bids:0,active:0,pending:0,positions:0});
 assert.equal(summaryExposure({position_cost:'7'}).positions,7);
 const html=botPnlDetailsMarkup({id:'test',account:{unfilled_bids:'0'},performance:{}},'1H');
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
test('paused-only market types trail active types without changing priority within each group',()=>{
 const bots=[
  {id:'paused-maker',strategy:'market_maker',series:'MM_POLITICS',market_category:'politics',name:'Politics',desired:'paused'},
  {id:'paused-crypto',series:'KXBTC15M',name:'Alpha paused',desired:'paused'},
  {id:'retired-crypto',series:'KXSOL15M',name:'Beta retired',desired:'running',retired:true},
  {id:'active-crypto',series:'KXETH15M',name:'Zulu active',desired:'running'},
  {id:'paused-weather',series:'KXRAIN',asset:'weather',name:'Weather',desired:'paused'},
  {id:'active-sports',series:'KXSPORT',asset:'sports',name:'Sports',desired:'running'},
  {id:'paused-sports',series:'KXSPORT2',asset:'sports',name:'A paused',desired:'paused'}
 ];
 const original=bots.map(b=>b.id),groups=marketTypeGroups(bots);
 assert.deepEqual(groups.map(g=>g.id),['crypto-15m','sports','maker-politics','weather-hourly']);
 assert.deepEqual(groups[0].bots.map(b=>b.id),['active-crypto','paused-crypto','retired-crypto']);
 assert.deepEqual(groups[1].bots.map(b=>b.id),['active-sports','paused-sports']);
 assert.deepEqual(bots.map(b=>b.id),original,'sorting must not mutate the worker snapshot');
 bots.find(b=>b.id==='active-sports').desired='paused';
 bots.find(b=>b.id==='paused-weather').desired='running';
 assert.deepEqual(marketTypeGroups(bots).map(g=>g.id),['crypto-15m','weather-hourly','maker-politics','sports']);
});
test('paused folders move below active folders without losing expanded cards or settling positions',()=>{
 const data=fixture();
 data.folders=[data.folders[3],data.folders[2],data.folders[0],data.folders[1]];
 const sequential=data.bots.find(b=>b.id==='sequential'),convexity=data.bots.find(b=>b.id==='convexity');
 const held={ticker:'KXBTC15M-26NOV21-YES',bot_id:'sequential',state:'pending',side:'yes',quantity:'2',
  cost:'1.20',value:'2.00',phase_origin:1,is_armed:false};
 data.folders.find(f=>f.id==='sequential').accounting.positions=[held];
 const storage=new Map([['moneytree-folder-views',JSON.stringify({open:['sequential'],periods:{}})],
  ['moneytree-market-views',JSON.stringify(['sequential'])]]);
 const {nodes,context}=setup(data,{storage});
 const html=()=>nodes.get('groups').innerHTML;
 const ids=()=>[...html().matchAll(/id="folder-([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual(ids(),['favorites','complete_set','sequential','convexity']);
 sequential.desired='paused';convexity.desired='running';vm.runInContext('draw()',context);
 assert.deepEqual(ids(),['convexity','favorites','complete_set','sequential']);
 assert.ok(html().includes('id="folder-sequential" open'));
 assert.ok(html().includes('data-market="sequential" open'));
 assert.ok(html().includes('Position · awaiting settlement'));
 assert.deepEqual(data.folders.find(f=>f.id==='sequential').accounting.positions,[held]);
 sequential.desired='running';convexity.desired='paused';vm.runInContext('draw()',context);
 assert.deepEqual(ids(),['favorites','complete_set','sequential','convexity']);
 assert.ok(html().includes('data-market="sequential" open'));
});
test('dashboard categories and Maker market cards put paused entries last',()=>{
 const data=fixture(),base=data.bots.find(b=>b.id==='favorites');
 data.bots.push({...base,id:'sports-active',series:'KXSPORT',asset:'sports',name:'Sports active',desired:'running'});
 data.bots.push({...base,id:'weather-paused',series:'KXRAIN',asset:'weather',name:'Weather paused',desired:'paused'});
 const html=setup(data).nodes.get('groups').innerHTML;
 const crypto=html.indexOf('data-market-type="favorites::crypto-15m"');
 const sports=html.indexOf('data-market-type="favorites::sports"');
 const weather=html.indexOf('data-market-type="favorites::weather-hourly"');
 assert.ok(crypto>=0&&sports>crypto&&weather>sports,'active sports should precede paused weather');
 const maker=scalperMarkup({market_maker:true,totals:{},markets:[
  {ticker:'KXM-PAUSED',title:'Alpha paused',paused:true,position:1,orders:0,trades_24h:1,schedule_source:'verified',incentives:[]},
  {ticker:'KXM-ACTIVE',title:'Zulu active',paused:false,position:2,orders:1,trades_24h:3,schedule_source:'verified',incentives:[]}
 ]},'maker');
 assert.ok(maker.indexOf('Zulu active')<maker.indexOf('Alpha paused'));
 assert.ok(maker.includes('1 held contracts'));
 assert.ok(maker.includes('data-desired="running"'));
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
 for(const token of ['Total P/L · 1h','$0.50','Bids','$3.00','Positions · cost','$10.00'])assert.ok(html.includes(token),token);
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
 assert.ok(header().includes('$10.00'));assert.ok(header().includes('2/2 running · 1 shown'));
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


test('category research pools independent event observations by price and time tier',()=>{
 const base={series:'KXBTCD',market_type:'hourly_price',side:'yes',clock:'market_close',horizon:'5–10m',price:'.90',contracts:'10',closed:'10',resolved:'10',winners:'10',cost:'9.1',net:'-.1',events:1,event_win_rate:100};
 const input=[base,{...base,series:'KXETHD',side:'no',price:'.95',contracts:'2',closed:'2',resolved:'2',winners:'2',cost:'1.9',net:'.1'},{...base,horizon:'1–2h'}];
 const rows=favoriteCategoryRows(input,true);
 assert.equal(rows.length,3);
 const r=rows.find(r=>r.horizon==='5–10m'&&r.low===90);
 assert.equal(r.band,'90–94¢');assert.equal(r.contracts,10);assert.equal(r.events,1);assert.equal(r.event_wins,1);
 assert.equal(rows.find(r=>r.low===95).band,'95–95¢');
 const html=favoriteCategoryResearchMarkup({id:'crypto-hourly',label:'Crypto · 1 hour',bots:input.map((item,i)=>({id:String(i),experiment:{entry_timing:[item]}}))});
 assert.match(html,/favorite-stat-matrix/);assert.match(html,/100.0%/);
 assert.ok(!html.includes('KXBTCD'));assert.ok(!html.includes('KXETHD'));assert.ok(!html.includes(' · YES'));assert.ok(!html.includes(' · NO'));
});

test('Favorites displays distinct resolved market events and keeps money returns separate',()=>{
 const row={series:'KXBTC15M',market_type:'15m_price',clock:'market_close',horizon:'5–10m',
  price:'.80',contracts:'10',closed:'10',resolved:'10',winners:'10',profitable_closed:'1',
  profit_classified_closed:'10',cost:'8',net:'-.3',events:1,event_win_rate:100,return_events:{event:{cost:'8',net:'-.3'}}};
 const html=favoriteCategoryResearchMarkup({id:'crypto-15m',label:'Crypto · 15 minutes',bots:[{id:'btc',experiment:{entry_timing:[row]}}]});
 assert.match(html,/favorite-stat-matrix/);assert.match(html,/n=1/);assert.match(html,/100.0%/);assert.match(html,/-3\.75%/);
 assert.doesNotMatch(html,/Purchased<\/th>/);
 const collector=favoriteCollectorOverviewMarkup([{id:'btc',name:'BTC',series:'KXBTC15M',experiment:{entry_timing:[row]}}]);
 assert.match(collector,/n=1/);assert.doesNotMatch(collector,/Exit\/fee drag/);
 const historic={...row,events:undefined,event_win_rate:undefined};
 const legacy=favoriteCollectorOverviewMarkup([{id:'btc',name:'BTC',series:'KXBTC15M',experiment:{entry_timing:[historic]}}]);
 assert.match(legacy,/No verified resolved timed events/);
 assert.doesNotMatch(legacy,/n=10/);
});
test('Favorites research sits within each non-sports category and keeps pending outcomes honest',()=>{
 const d=fixture(),bot=d.bots.find(b=>b.id==='favorites');bot.name='<img onerror=x>';
 bot.experiment.entry_timing=[{series:bot.series,market_type:'15m_price',side:'yes',clock:'market_close',horizon:'10–15m',price:'.90',contracts:'4',closed:'0',resolved:'0',winners:'0',cost:'3.6',net:'0'}];
 const {nodes}=setup(d),html=nodes.get('groups').innerHTML;
 for(const text of ['High-Probability Favorites · price × time matrix','No verified resolved timed observations yet','Entry percentage × time remaining'])assert.ok(html.includes(text),text);
 assert.ok(!html.includes('<img onerror'));assert.ok(!html.includes('NaN'));
 const research=html.indexOf('High-Probability Favorites · price × time matrix'),group=html.indexOf('data-market-type="favorites::crypto-15m"'),card=html.indexOf('data-market="favorites"',group);
 assert.ok(research>=0&&research<group&&group<card); assert.ok(!html.includes('data-research="favorites-category-crypto-15m"'));
});
test('category research expansion survives refresh and reload',()=>{
 const key='favorites-collector-crypto-15m',detail={dataset:{research:key},open:true,isConnected:true},storage=new Map();
 const {context}=setup(fixture(),{storage,queries:{'details[data-research]':[detail]}});
 detail.ontoggle({target:detail});vm.runInContext('draw()',context);
 assert.equal(storage.get('moneytree-research-views'),JSON.stringify([key]));
 const {nodes}=setup(fixture(),{storage});assert.match(nodes.get('groups').innerHTML,/data-research="favorites-collector-crypto-15m" open/);
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
 context.demoCall=async path=>path.startsWith('shadow/workspace')?next:path==='shadow/research-folder/favorites'?{bots:{}}:{items:[]};
 await vm.runInContext('load()',context);assert.equal(nodes.get('message').textContent,'');
 vm.runInContext("note('Saved bot settings')",context);
 await vm.runInContext('load()',context);assert.equal(nodes.get('message').textContent,'Saved bot settings');
});

test('market maker renders category and individual controls, isolated experiments, and selected statistics',()=>{
 const data=fixture(),base=data.bots[0];
 data.folders.push({id:'market_maker',name:'Market Maker',description:'Paper only'});
 data.bots.push({...base,id:'market_maker_politics',series:'MM_POLITICS',name:'Politics',folder_id:'market_maker',strategy:'market_maker',market_category:'politics',experiment:{message:'Monitoring',scalper:{market_maker:true,totals:{completed:3,maker_fill_rate:.5},periods:{'1H':{completed:1,win_rate:100}},config:{approach:'market_maker',min_spread:.03},cells:[],recent:[],markets:[{ticker:'POL-X',title:'<bad>',position:'2',orders:1,trades_24h:30,schedule_source:'unavailable',incentives:[]}]}}});
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 for(const text of ['Market Maker','Politics','Pause category','data-maker-market="market_maker_politics"','data-experiment-save="market_maker_politics"','Pause market','&lt;bad&gt;'])assert.ok(html.includes(text),text);
 const recent=scalperMarkup(data.bots.at(-1).experiment.scalper,'market_maker_politics','1H');
 assert.match(recent,/1 \/ 100.0%/);assert.match(recent,/selected 1H window/);assert.doesNotMatch(recent,/3 \/ —%/);
 assert.match(scalperMarkup(data.bots.at(-1).experiment.scalper,'','30D'),/collecting a baseline/);
});

test('new scalper modes and market maker use existing gateway paper controls',async()=>{
 for(const folder of ['scalper_momentum','scalper_dislocation','market_maker','maker_competitive']){
  let forwarded=false;
  const result=await proxyAuth(new Request('https://app.test/api/demo/shadow/bulk',{method:'POST',headers:{origin:'https://app.test','content-type':'application/json','x-csrf-token':'token'},body:JSON.stringify({action:'pause',folder_id:folder})}),{APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)},{fetcher:async request=>{forwarded=true;return new Response(JSON.stringify({contract:'demo-v1',saved:true,real_orders_enabled:false}),{headers:{'content-type':'application/json'}})}});
  assert.equal(result.status,200);assert.ok(forwarded);
 }
});

test('maker discovery displays ranked candidates and actual admission rejection reasons',()=>{
 const data=fixture(),base=data.bots[0];
 data.folders.push({id:'market_maker',name:'Market Maker',strategy:'market_maker',scanner:{state:'Candidate inspection complete',reads:5,ranked:[{ticker:'<candidate>',category:'politics',score:.12345,reason:'insufficient_executed_trade_frequency'}]}});
 data.bots.push({...base,id:'market_maker_politics',name:'Politics',series:'MM_POLITICS',strategy:'market_maker',market_category:'politics',folder_id:'market_maker'});
 const {nodes}=setup(data),html=nodes.get('groups').innerHTML;
 for(const value of ['Market Maker discovery','1 ranked candidates','5 shared-budget data reads','insufficient executed trade frequency','&lt;candidate','0.1235'])assert.ok(html.includes(value),value);
 assert.ok(!html.includes('<candidate>'));
});

test('Favorites collector and statistics category tables respect persisted closed state',()=>{
 const d=fixture(),bot=d.bots.find(b=>b.id==='favorites');
 bot.experiment.entry_timing=[{series:bot.series,market_type:'15m_price',clock:'market_close',horizon:'5–10m',price:'.80',contracts:'2',closed:'2',resolved:'2',winners:'2',cost:'1.6',net:'.4'}];
 const collectorClosed=favoriteCollectorOverviewMarkup([bot],new Set());
 assert.match(collectorClosed,/data-research="favorites-collector-crypto-15m"/);
 assert.doesNotMatch(collectorClosed,/data-research="favorites-collector-crypto-15m" open/);
 const collectorOpen=favoriteCollectorOverviewMarkup([bot],new Set(['favorites-collector-crypto-15m']));
 assert.match(collectorOpen,/data-research="favorites-collector-crypto-15m" open/);
 const stats={min_samples:20,matrix:[{market_type:'weather_daily',price_buckets:['70-74'],time_buckets:['5–10m'],cells:[]}]};
 assert.doesNotMatch(favoriteStatisticsMatrixMarkup(stats,new Set()),/data-research="favorites-stat-weather_daily" open/);
 assert.match(favoriteStatisticsMatrixMarkup(stats,new Set(['favorites-stat-weather_daily'])),/data-research="favorites-stat-weather_daily" open/);
});

test('Favorites rollups show observations across categories and per-sport breakdowns',()=>{
 const bot=(id,series,asset)=>({id,name:id,series,asset,experiment:{entry_timing:[]}});
 const bots=[bot('sport1','KXNBAGAME','sports'),bot('sport2','KXMLBGAME','sports'),
  bot('weather','KXHIGHNY','weather'),bot('daily','KXHIGHTEMP','weather_daily'),
  bot('oil','KXWTIH','hourly'),bot('gold','KXGOLD15M','commodity'),bot('fx','KXUSDCAD15M','finance')];
 const row=(contracts,kind,events=1)=>({series:'combined',market_type:kind,clock:'market_close',
  horizon:'5–10m',price:'.80',contracts:String(contracts),closed:String(contracts),
  resolved:String(contracts),winners:String(contracts),cost:'1',net:'0.2',events,event_wins:events});
 const summary={rows:{sports:[row(7,'sports',2)],'weather-hourly':[row(2,'weather')],
  'weather-daily':[row(3,'weather_daily')],'commodities-hourly':[row(4,'hourly_price')],
  'commodities-15m':[row(5,'15m_price')],'finance-15m':[row(6,'15m_price')]},
  coverage:{sports:{bots_total:2,bots_with_rows:2}},
  sports_by_bot:{sport1:[row(3,'sports')],sport2:[row(4,'sports')]}};
 const html=favoriteCollectorOverviewMarkup(bots,new Set(),{timedSummary:summary});
 for(const label of ['Sports','Hourly weather','Daily weather','Commodities','Finance'])assert.ok(html.includes(label),label);
 assert.match(html,/n=2/);assert.match(html,/n=1/);
 assert.doesNotMatch(html,/Purchased 7 · settled 7/);
 const category=favoriteCategoryResearchMarkup({id:'sports',label:'Sports',bots:bots.slice(0,2),
   aggregated_entry_timing:summary.rows.sports});
 assert.match(category,/favorite-stat-matrix/);
 assert.match(category,/n=2/);
});

test('Favorites preserves 15-minute versus hourly event observations and retired history',()=>{
 const observation=(series,contracts,retired=false)=>({
  id:series,name:series,series,asset:series.endsWith('15M')?'15m':'hourly',retired,
  experiment:{entry_timing:[{series,market_type:'crypto',clock:'market_close',horizon:'5–10m',
    price:'.80',contracts:String(contracts),closed:String(contracts),resolved:String(contracts),
    winners:String(contracts),cost:String(contracts*.8),net:String(contracts*.2),events:1,event_win_rate:100}]}});
 const bots=[observation('KXBTC15M',2),observation('KXBTCH',3),observation('KXETH15M',4,true)];
 const html=favoriteCollectorOverviewMarkup(bots,new Set(['favorites-collector-crypto-15m']));
 assert.match(html,/data-research="favorites-collector-crypto-15m" open/);
 assert.match(html,/data-research="favorites-collector-crypto-hourly"/);
 assert.match(html,/Verified resolved event observations: 2/);
 assert.match(html,/Verified resolved event observations: 1/);
 assert.match(html,/n=2/);
 assert.doesNotMatch(html,/Purchased 6 · settled 6/);
 const category=favoriteCategoryResearchMarkup({id:'crypto-15m',label:'Crypto · 15 minutes',
  bots:bots.filter(b=>b.series.endsWith('15M'))});
 assert.match(category,/favorite-stat-matrix/);
 assert.match(category,/n=2/);
});

test('Favorites price tiers show independent samples without importing hourly cohorts',()=>{
 const make=(id,series,price,contracts)=>({
  id,series,name:id,asset:series.endsWith('15M')?'15m':'hourly',
  experiment:{entry_timing:[{series,market_type:'15m_price',clock:'market_close',horizon:'5–10m',
    price:String(price),contracts:String(contracts),closed:String(contracts),
    resolved:String(contracts),winners:String(contracts),net:'0',cost:'0',events:1,event_win_rate:100}]}});
 const bots=[make('btc','KXBTC15M',.80,2),make('eth','KXETH15M',.65,7),
  make('sol','KXSOL15M',.95,3),make('hour','KXBTCD',.65,4)];
 const html=favoriteCollectorOverviewMarkup(bots);
 const fifteen=html.split('data-research="favorites-collector-crypto-15m"')[1].split('data-research="favorites-collector-crypto-hourly"')[0];
 const hourly=html.split('data-research="favorites-collector-crypto-hourly"')[1];
 assert.match(fifteen,/65–69¢/);assert.match(fifteen,/90–95¢|95–95¢/);
 assert.match(fifteen,/Verified resolved event observations: 3/);
 assert.match(hourly,/Verified resolved event observations: 1/);
 assert.doesNotMatch(fifteen,/Purchased 7 · settled 7/);
});

test('Favorites pending-only cohorts never turn contract quantity into fake observations',()=>{
 const bot=(id,series,count)=>({id,name:id,series,experiment:{entry_timing:count?[{
  price:'.80',horizon:'5–10m',clock:'market_close',market_type:'15m_price',
  contracts:String(count),closed:'0',resolved:'0',winners:'0'
 }]:[]}});
 const html=favoriteCollectorOverviewMarkup([bot('btc','KXBTC15M',10),bot('eth','KXETH15M',0),
  bot('hour','KXBTCD',2)],new Set(),{loaded:true});
 assert.match(html,/Verified resolved event observations: 0/);
 assert.doesNotMatch(html,/n=10/);
 const unavailable=favoriteCollectorOverviewMarkup([bot('btc','KXBTC15M',0)],new Set(),{error:'Research unavailable'});
 assert.match(unavailable,/Favorites research could not load: Research unavailable/);
 const loading=favoriteCollectorOverviewMarkup([bot('btc','KXBTC15M',0)],new Set(),{loading:true});
 assert.match(loading,/Detailed Favorites research is loading/);
});

test('workspace rollup event samples are visible without loading per-currency research',()=>{
 const bot=(id,series,asset)=>({id,name:id,series,asset,experiment:{entry_timing:[]}});
 const bots=[bot('btc','KXBTC15M','crypto'),bot('eth','KXETH15M','crypto'),bot('hour','KXBTCD','hourly')];
 const row=(contracts,kind,events)=>({series:'combined',market_type:kind,clock:'market_close',
  horizon:'5–10m',price:'.80',contracts:String(contracts),closed:String(contracts),
  resolved:String(contracts),winners:String(contracts),cost:'1',net:'.2',events,event_wins:events});
 const timedSummary={rows:{'crypto-15m':[row(6,'15m_price',2)],'crypto-hourly':[row(3,'hourly_price',1)]},
  coverage:{'crypto-15m':{bots_total:2,bots_with_rows:2},'crypto-hourly':{bots_total:1,bots_with_rows:1}}};
 const html=favoriteCollectorOverviewMarkup(bots,new Set(),{timedSummary});
 assert.match(html,/Verified resolved event observations: 2/);
 assert.match(html,/Verified resolved event observations: 1/);
 assert.doesNotMatch(html,/n=6/);assert.doesNotMatch(html,/n=3/);
 assert.match(html,/calculated from the complete saved Favorites evidence/);
 const category=favoriteCategoryResearchMarkup({id:'crypto-15m',label:'Crypto · 15 minutes',
  bots:bots.slice(0,2),aggregated_entry_timing:timedSummary.rows['crypto-15m']});
 assert.match(category,/n=2/);
});

test('Favorites shows populated late time windows using event observations',()=>{
 const rows=[{series:'KXBTC15M',market_type:'15m_price',clock:'market_close',
  horizon:'10–15m',price:'.80',contracts:'7',closed:'4',resolved:'3',
  winners:'2',cost:'5.6',net:'.2',events:1,event_win_rate:100}];
 const bot={id:'btc',series:'KXBTC15M',name:'Bitcoin',experiment:{entry_timing:rows}};
 const html=favoriteCollectorOverviewMarkup([bot]);
 assert.match(html,/Observed time windows: 10–15m/);
 assert.match(html,/resolved observations/);
 assert.match(html,/n=1/);
 assert.doesNotMatch(html,/7 purchased/);
 assert.match(html,/Scroll the table horizontally for the other time columns/);
});

test('opening Favorites lazily restores event-based research without bloating initial workspace',async()=>{
 const d=fixture(),bot=d.bots.find(b=>b.id==='favorites');bot.experiment.entry_timing=[];
 const detail={dataset:{folder:'favorites'},open:false,isConnected:true},storage=new Map();
 const {context,nodes}=setup(d,{storage,queries:{'details[data-folder]':[detail]}});
 let calls=0;context.demoCall=async path=>{
  if(path==='shadow/research-folder/favorites'){calls++;return {contract:'demo-v1',folder_id:'favorites',at:123,bots:{favorites:{entry_timing:[
   {series:bot.series,market_type:'15m_price',clock:'market_close',horizon:'5–10m',
    price:'.80',contracts:'5',closed:'4',resolved:'4',winners:'3',cost:'4',net:'.2',events:1,event_win_rate:100}
  ]}}};}
  return {};
 };
 detail.open=true;detail.ontoggle();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls,1);
 const html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('80–84¢'));assert.ok(html.includes('n=1'));
 assert.ok(html.includes('High-Probability Favorites · price × time matrix'));
});

test('statistics-backed Favorites renders a category-separated 5-cent by time matrix with sparse and fallback labels',()=>{
 const stats={min_samples:20,matrix:[{market_type:'weather_daily',price_buckets:['70-74','75-79','95-95'],time_buckets:['5–10m','10–15m'],cells:[
  {price_bucket:'70-74',horizon:'5–10m',samples:32,win_rate:.9,realized_roi:.08,realized_net:'4',lower:.79,level:'market_type_price_time',fallback_level:'market_type_price_time',fallback_samples:32,eligibility:'evidence_candidate'},
  {price_bucket:'75-79',horizon:'10–15m',samples:3,win_rate:1,realized_roi:.3,realized_net:'1',lower:.4,level:'market_type_price_time',fallback_level:'market_type_price',fallback_samples:44,eligibility:'insufficient_samples'}
 ]}]};
 const html=favoriteStatisticsMatrixMarkup(stats);
 for(const phrase of ['weather_daily','70–74¢','75–79¢','95–95¢','5–10m','10–15m','n=32','n=3','Evidence candidate','Under-sampled','Fallback available','44'])assert.ok(html.includes(phrase),phrase);
 assert.ok(!html.includes('n=0'));assert.ok(html.includes('No settled events'));
});

test('statistics-backed Favorites shows distinct event hold ROI and 90% uncertainty alongside outcome evidence',()=>{
  const stats={min_samples:20,matrix:[{
    market_type:'15m_price',price_buckets:['80-84','85-89'],
    time_buckets:['10–15m','5–10m'],cells:[{
      price_bucket:'80-84',horizon:'10–15m',samples:20,win_rate:.85,
      realized_roi:-.9,realized_net:'-999',lower:.7,level:'market_type_price_time',
      fallback_level:'market_type_price_time',fallback_samples:20,
      eligibility:'evidence_candidate'
    },{
      price_bucket:'85-89',horizon:'5–10m',samples:3,win_rate:1,
      realized_roi:4,realized_net:'999',lower:.4,level:'market_type_price_time',
      fallback_level:'market_type_price',fallback_samples:20,
      eligibility:'insufficient_samples'
    }]
  }]};
  const sample={resolved_events:20,event_wins:17,return_observations:12,
    average_return_pct:'12.345',uncertainty90_pct:'4.567',
    ci90_low_pct:'7.778',ci90_high_pct:'16.912',
    estimated_return_observations:2,incomplete_events:8};
  const hold={basis:'verified_hold_only',
    by_market_type:{'15m_price':sample},
    by_cell:{'15m_price':{'80-84|10–15m':sample}}};
  const html=favoriteStatisticsMatrixMarkup(stats,new Set(),hold);
  const summary=html.slice(html.indexOf('<summary>'),html.indexOf('</summary>'));
  assert.match(summary,/Hold P\/L \+12\.35%/);
  assert.match(summary,/90% ±4\.57 points/);
  assert.match(summary,/n=12/);
  assert.match(html,/n=20/,'settled outcome sample stays intact');
  assert.match(html,/n=12 held/,'hold return sample remains separate');
  assert.match(html,/2 historical returns estimated/);
  assert.match(html,/8 resolved events without complete held return attribution/);
  assert.match(html,/Evidence candidate/);
  assert.match(html,/Under-sampled/);
  assert.doesNotMatch(html,/Hold P\/L -90|Hold P\/L \+400|NaN|undefined/);
  assert.doesNotMatch(html,/profit-positive|profit-negative/,
    'statistics trading eligibility colors must not be overwritten by held ROI');
  assert.match(html,/Hold P\/L — · 90% uncertainty — · n=0 held/);
});

test('statistics-backed Favorites does not invent ROI when only realized exits or outcomes exist',()=>{
  const stats={matrix:[{market_type:'15m_price',price_buckets:['80-84'],
    time_buckets:['10–15m'],cells:[{price_bucket:'80-84',horizon:'10–15m',
      samples:25,win_rate:.9,realized_roi:9,realized_net:'10000',
      eligibility:'evidence_rejected',lower:.7,level:'exact',
      fallback_level:'exact',fallback_samples:25}]}]};
  const noHold=favoriteStatisticsMatrixMarkup(stats);
  assert.match(noHold,/Hold P\/L —/);
  assert.doesNotMatch(noHold,/Hold P\/L \+900%/);
  const sparse={by_market_type:{'15m_price':{resolved_events:1,return_observations:1,
      average_return_pct:'-20',uncertainty90_pct:null}},
    by_cell:{'15m_price':{'80-84|10–15m':{resolved_events:1,return_observations:1,
      average_return_pct:'-20',uncertainty90_pct:null}}}};
  const html=favoriteStatisticsMatrixMarkup(stats,new Set(),sparse);
  assert.match(html,/Hold P\/L -20\.00%/);
  assert.match(html,/90% uncertainty —/);
  assert.doesNotMatch(html,/90% ±0\.00/);
});

test('statistical Favorites decision cannot erase all detailed bot panels',()=>{
 const d=fixture();
 d.folders.push({id:'favorites_statistics',name:'Favorites · Statistics-Backed',description:'Independent statistical paper strategy',accounting:{at:Date.now()/1000,portfolio:{cash:'1000'}}});
 d.bots.push({...d.bots.find(b=>b.id==='favorites'),id:'stats-bot',name:'Statistical BTC',folder_id:'favorites_statistics',strategy:'favorites_statistics',
  experiment:{attempts:2,completed:1,unmatched:0,message:'Collecting',calibration:[],entry_timing:[],
   decision:{reason:'insufficient_samples',samples:5,level:'global',expected_roi:null}}});
 const {nodes}=setup(d),html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('Statistical BTC'));
 assert.ok(html.includes('Last statistical decision'));
 assert.ok(html.includes('insufficient_samples'));
 assert.ok(html.includes('Profit & exposure'));
 assert.ok(html.includes('data-market="favorites"'), 'other bot details remain accessible');
});
test('paused-only portfolios are excluded from overview, not erased from strategy history',()=>{
 const d=fixture();
 d.folders.push({id:'favorites_statistics',name:'Paused statistics history',description:'Historical data',accounting:{at:Date.now()/1000,portfolio:{cash:'1000'}}});
 d.bots.push({...d.bots[0],id:'stat-paused',folder_id:'favorites_statistics',desired:'paused',name:'Stat history',strategy:'favorites_statistics',experiment:{message:'Paused'}});
 const {nodes}=setup(d);
 assert.ok(!nodes.get('accountSummary').innerHTML.includes('Paused statistics history'));
 assert.ok(!nodes.get('accountSummary').innerHTML.includes('Convexity · Paused'));
 assert.ok(nodes.get('groups').innerHTML.includes('Paused statistics history'));
 assert.ok(nodes.get('groups').innerHTML.includes('Stat history'));
});
test('large collapsed folders defer detailed cards and render them when expanded',()=>{
 const d=fixture(),base=d.bots.find(b=>b.id==='favorites');
 for(let i=0;i<40;i++)d.bots.push({...base,id:'favorite-extra-'+i,name:'Extra '+i});
 const storage=new Map(),detail={dataset:{folder:'favorites'},open:false,isConnected:true};
 const {nodes}=setup(d,{storage,queries:{'details[data-folder]':[detail]}});
 assert.ok(nodes.get('groups').innerHTML.includes('id="folder-favorites"'));
 assert.ok(!nodes.get('groups').innerHTML.includes('data-market="favorite-extra-25"'));
 detail.open=true;detail.ontoggle();
 assert.ok(nodes.get('groups').innerHTML.includes('data-market="favorite-extra-25"'));
 assert.equal(JSON.parse(storage.get('moneytree-folder-views')).open.includes('favorites'),true);
});

test('high-probability collector matrices display event observations not contracts',()=>{
 const d=fixture();
 d.bots.find(b=>b.id==='favorites').experiment.entry_timing=[
  {series:'KXBTC15M',market_type:'15m_price',side:'yes',clock:'market_close',
   horizon:'10–15m',price:'.80',contracts:'5',closed:'4',resolved:'4',winners:'3',
   cost:'4',net:'-.2',holding_seconds:'1200',events:1,event_win_rate:100},
  {series:'KXBTC15M',market_type:'15m_price',side:'no',clock:'market_close',
   horizon:'10–15m',price:'.85',contracts:'6',closed:'5',resolved:'5',winners:'4',
   cost:'5',net:'.2',holding_seconds:'1500',events:1,event_win_rate:100}
 ];
 const html=setup(d).nodes.get('groups').innerHTML;
 const root=html.indexOf('id="folder-favorites"');
 const table=html.indexOf('High-Probability Favorites · price × time matrix',root);
 const category=html.indexOf('data-market-type="favorites::crypto-15m"',root);
 assert.ok(root>=0&&table>root&&category>table);
 for(const phrase of ['80–84¢','85–89¢','10–15m','n=1','P/L'])assert.ok(html.includes(phrase),phrase);
 assert.doesNotMatch(html,/n=5 settled|n=4 settled/);
});

test('large collector folder restores one observation for a multi-contract trade',()=>{
 const d=fixture(),base=d.bots.find(b=>b.id==='favorites');
 base.experiment.entry_timing=[{series:base.series,market_type:'15m_price',side:'yes',
  clock:'market_close',horizon:'5–10m',price:'.75',contracts:'7',closed:'5',
  resolved:'5',winners:'4',cost:'5.25',net:'.4',events:1,event_win_rate:100}];
 for(let i=0;i<24;i++)d.bots.push({...base,id:'fav-extra-'+i,name:'Favorite '+i,experiment:{...base.experiment,entry_timing:[]}});
 d.bots.find(b=>b.id==='fav-extra-3').desired='paused';
 const detail={dataset:{folder:'favorites'},open:false,isConnected:true};
 const {nodes}=setup(d,{queries:{'details[data-folder]':[detail]}});
 assert.ok(!nodes.get('groups').innerHTML.includes('High-Probability Favorites · price × time matrix'));
 detail.open=true;detail.ontoggle();
 const html=nodes.get('groups').innerHTML;
 assert.ok(html.includes('High-Probability Favorites · price × time matrix'));
 assert.ok(html.includes('75–79¢'));
 assert.ok(html.includes('n=1'),'seven contracts do not become seven event observations');
});

test('collector matrix preserves category research and does not invent pending observations',()=>{
 const d=fixture(),bot=d.bots.find(b=>b.id==='favorites');
 bot.experiment.entry_timing=[
  {series:bot.series,market_type:'15m_price',side:'yes',clock:'market_close',
   horizon:'5–10m',price:'.70',contracts:'10',closed:'5',resolved:'5',winners:'4',
   cost:'7',net:'.2',events:1,event_win_rate:100},
  {series:bot.series,market_type:'15m_price',side:'no',clock:'market_close',
   horizon:'5–10m',price:'.72',contracts:'3',closed:'0',resolved:'0',winners:'0',cost:'2.16',net:'0'}
 ];
 const html=setup(d).nodes.get('groups').innerHTML;
 assert.ok(html.includes('High-Probability Favorites · price × time matrix'));
 assert.ok(!html.includes('data-research="favorites-category-crypto-15m"'),'no duplicate combined table');
 assert.ok(html.includes('70–74¢'));
 assert.ok(html.includes('n=1'));
 assert.doesNotMatch(html,/Purchased 13|n=13 settled/);
});


test('Favorites bucket stars have stable coordinates and accessible pressed state',()=>{
 const key=favoriteBucketKey('collector:crypto-15m','detailed','80–84¢','5–10m');
 const stars=new Set([key]);
 assert.notEqual(key,favoriteBucketKey('collector:crypto-hourly','detailed','80–84¢','5–10m'));
 assert.notEqual(key,favoriteBucketKey('market:btc','detailed','80–84¢','5–10m'));
 assert.notEqual(key,favoriteBucketKey('collector:crypto-15m','wide','80–84¢','5–10m'));
 assert.notEqual(key,favoriteBucketKey('collector:crypto-15m','detailed','80–84¢','10–15m'));
 const selected=favoriteBucketStarMarkup('collector:crypto-15m','detailed','80–84¢','5–10m',stars);
 assert.match(selected,/data-favorite-star="/);
 assert.match(selected,/aria-pressed="true"/);
 assert.match(selected,/class="favorite-bucket-star is-starred"/);
 assert.match(selected,/★/);
 assert.match(selected,/80–84¢/);
 const normal=favoriteBucketStarMarkup('collector:crypto-15m','detailed','80–84¢','10–15m',stars);
 assert.match(normal,/aria-pressed="false"/);
 assert.match(normal,/☆/);
 assert.equal(favoriteBucketStarMarkup('', 'detailed','80–84¢','5–10m',stars),'');
});

test('stars appear on filled and empty Detailed, Wider, Single and Statistics favorites cells',()=>{
 const row={series:'KXBTC15M',market_type:'15m_price',clock:'market_close',
   horizon:'5–10m',price:'.80',contracts:1,closed:1,resolved:1,winners:1,
   events:1,event_wins:1,cost:'.80',return_sum:'.20',return_observations:1};
 const bot={id:'btc',name:'Bitcoin',asset:'crypto',series:'KXBTC15M',experiment:{entry_timing:[row]}};
 const a=favoriteBucketKey('collector:crypto-15m','detailed','80–84¢','5–10m');
 const b=favoriteBucketKey('collector:crypto-15m','wide','78–<86¢','1');
 const c=favoriteBucketKey('collector:crypto-15m','single','all','all');
 const d=favoriteBucketKey('statistics:15m_price','statistics','85-89','5–10m');
 const e=favoriteBucketKey('market:btc','detailed','80–84¢','5–10m');
 const stars=new Set([a,b,c,d,e]);
 const collector=favoriteCollectorOverviewMarkup([bot],new Set(),{starredBuckets:stars});
 assert.match(collector,/favorite-bucket-star is-starred/);
 assert.match(collector,/stat-empty/);
 assert.ok(collector.includes('data-favorite-star="'+a+'"'));
 const wide=favoriteWideOverviewMarkup([bot],{
   price_buckets:['70–<78¢','78–<86¢','86–95¢'],
   coverage:{'crypto-15m':{time_buckets:['Early','Middle','Late']}},
   rows:{'crypto-15m':[{band:'78–<86¢',time_slot:1,events:1,event_wins:1,
      contracts:1,cost:'.80',return_sum:'.20',return_observations:1}]}
 },new Set(),stars);
 assert.ok(wide.includes('data-favorite-star="'+b+'"'));
 assert.match(wide,/favorite-bucket-star is-starred/);
 assert.match(wide,/stat-empty/);
 const sample={resolved_events:1,event_wins:1,return_observations:1,
   average_return_pct:'25',uncertainty90_pct:null};
 const single=favoriteSingleOverviewMarkup([bot],{rows:{'crypto-15m':sample},by_bot:{}},new Set(),stars);
 assert.ok(single.includes('data-favorite-star="'+c+'"'));
 assert.match(single,/favorite-bucket-star is-starred/);
 const timing=favoriteTimingMarkup([row],null,{mode:'detailed',starScope:'market:btc',starredBuckets:stars});
 assert.ok(timing.includes('data-favorite-star="'+e+'"'));
 const stat=favoriteStatisticsMatrixMarkup({min_samples:20,matrix:[{
   market_type:'15m_price',price_buckets:['80-84','85-89'],time_buckets:['5–10m'],
   cells:[{price_bucket:'80-84',horizon:'5–10m',samples:2,win_rate:.5,lower:.1,
     level:'market_type_price_time',fallback_level:'insufficient_samples',
     eligibility:'insufficient_samples'}]
 }]},new Set(),null,stars);
 assert.ok(stat.includes('data-favorite-star="'+d+'"'));
 assert.match(stat,/No settled events/);
 assert.match(stat,/favorite-bucket-star is-starred/);
});

test('star toggles persist across redraw, reload and switching Favorites table settings',()=>{
 const d=fixture(),key=favoriteBucketKey('collector:crypto-15m','single','all','all');
 const storage=new Map([['moneytree-favorite-table-mode','single']]);
 const updates=[],button={dataset:{favoriteStar:key,favoriteStarLabel:'all prices · all times research bucket'},
   setAttribute:(name,value)=>updates.push([name,value]),
   classList:{toggle(name,on){updates.push([name,on])}}};
 const {nodes,context}=setup(d,{storage,queries:{'[data-favorite-star]':[button]}});
 assert.match(nodes.get('groups').innerHTML,/Single bucket/);
 let prevented=false,stopped=false;
 const click={preventDefault(){prevented=true},stopPropagation(){stopped=true}};
 button.onclick(click);
 assert.equal(prevented,true);assert.equal(stopped,true);
 assert.equal(button.textContent,'★');
 assert.equal(storage.get('moneytree-favorites-starred-v1'),JSON.stringify([key]));
 assert.ok(updates.some(([name,value])=>name==='aria-pressed'&&value==='true'));
 assert.match(setup(d,{storage}).nodes.get('groups').innerHTML,/favorite-bucket-star is-starred/);
 storage.set('moneytree-favorite-table-mode','detailed');
 vm.runInContext('draw()',context);
 storage.set('moneytree-favorite-table-mode','single');
 const restored=setup(d,{storage}).nodes.get('groups').innerHTML;
 assert.match(restored,/favorite-bucket-star is-starred/);
 button.onclick(click);
 assert.equal(button.textContent,'☆');
 assert.equal(storage.get('moneytree-favorites-starred-v1'),'[]');
 assert.ok(updates.some(([name,value])=>name==='aria-pressed'&&value==='false'));
});
test('Favorites table setting switches views and persists across reload without changing trading controls',()=>{
 const d=fixture(),folder=d.folders.find(f=>f.id==='favorites');
 folder.collector_wide_summary={price_buckets:['70–<78¢','78–<86¢','86–95¢'],
  rows:{'crypto-15m':[{band:'70–<78¢',horizon:'0m–5m',time_slot:0,events:100,event_wins:90,contracts:'100',cost:'75',return_observations:100,return_sum:'20'}]},
  coverage:{'crypto-15m':{time_buckets:['0m–5m','5m–10m','10m–15m'],time_basis:'market_duration'}},by_bot:{}};
 const button={dataset:{favoriteTable:'wide'}},storage=new Map();
 const {nodes}=setup(d,{storage,queries:{'[data-favorite-table]':[button]}});
 assert.match(nodes.get('groups').innerHTML,/Table settings/);
 button.onclick();assert.equal(storage.get('moneytree-favorite-table-mode'),'wide');
 assert.match(nodes.get('groups').innerHTML,/wider 3 × 3/);
 assert.match(nodes.get('groups').innerHTML,/70–&lt;78¢/);
 assert.match(nodes.get('groups').innerHTML,/90% win-rate interval/);
 assert.match(nodes.get('groups').innerHTML,/favorite-wide-matrix/);
 const lower=favoriteCategoryResearchMarkup({id:'crypto-15m',label:'Crypto · 15 minutes',bots:[{id:'btc',experiment:{entry_timing:[]}}]},new Set(),{mode:'wide',summary:folder.collector_wide_summary});
 assert.match(lower,/favorite-stat-matrix favorite-wide-matrix/);
 assert.match(lower,/n=100/);
 assert.doesNotMatch(nodes.get('groups').innerHTML,/\bpp\b/);
 assert.doesNotMatch(nodes.get('groups').innerHTML,/NaN|undefined/);
 assert.match(setup(d,{storage}).nodes.get('groups').innerHTML,/wider 3 × 3/);
 button.dataset.favoriteTable='detailed';button.onclick();
 assert.equal(storage.get('moneytree-favorite-table-mode'),'detailed');
 assert.doesNotMatch(nodes.get('groups').innerHTML,/<h3>High-Probability Favorites · wider/);
});

test('single bucket combines resolved-event hold P/L and 90% ROI uncertainty without changing other views',()=>{
  const d=fixture(),folder=d.folders.find(f=>f.id==='favorites');
  folder.collector_single_summary={rows:{'crypto-15m':{
    resolved_events:52,event_wins:45,return_observations:50,
    average_return_pct:'4.2',uncertainty90_pct:'1.8',ci90_low_pct:'2.4',
    ci90_high_pct:'6.0',incomplete_events:2,estimated_return_observations:0
  }},by_bot:{favorites:{
    resolved_events:52,event_wins:45,return_observations:50,
    average_return_pct:'4.2',uncertainty90_pct:'1.8',ci90_low_pct:'2.4',
    ci90_high_pct:'6.0',incomplete_events:2,estimated_return_observations:0
  }}};
  const button={dataset:{favoriteTable:'single'}},storage=new Map();
  const {nodes}=setup(d,{storage,queries:{'[data-favorite-table]':[button]}});
  assert.match(nodes.get('groups').innerHTML,/Wider · 3 × 3/);
  assert.match(nodes.get('groups').innerHTML,/Single bucket/);
  button.onclick();
  assert.equal(storage.get('moneytree-favorite-table-mode'),'single');
  const html=nodes.get('groups').innerHTML;
  assert.match(html,/favorite-single-matrix/);
  assert.match(html,/\+4\.20% Hold P\/L/);
  assert.match(html,/90% P\/L uncertainty: ±1\.80 percentage points/);
  assert.match(html,/n=50 distinct event returns/);
  assert.match(html,/90% interval 2\.40% to 6\.00%/);
  assert.match(html,/All entries · single bucket/,'market-level research follows mode');
  assert.doesNotMatch(html,/NaN|undefined/);
  assert.match(setup(d,{storage}).nodes.get('groups').innerHTML,/favorite-single-matrix/);
  button.dataset.favoriteTable='wide';button.onclick();
  assert.equal(storage.get('moneytree-favorite-table-mode'),'wide');
  assert.match(nodes.get('groups').innerHTML,/favorite-wide-matrix|wider 3 × 3/);
});

test('regular Favorites evidence brackets retain their meanings at 50/100/300/1000 events',()=>{
 const checkpoints=new Map([
  [0,'No evidence'],[1,'Early'],[49,'Early'],[50,'Early'],[99,'Early'],
  [100,'Preliminary'],[299,'Preliminary'],[300,'Developing'],
  [999,'Developing'],[1000,'Stronger'],[10000,'Stronger']
 ]);
 for(const [n,tier] of checkpoints)assert.equal(favoriteEvidenceTier(n),tier,'evidence tier n='+n);
});

test('regular Favorites win-rate uncertainty is pending below 50 in detailed and wider buckets',()=>{
 const row=n=>({
   series:'KXBTC15M',market_type:'15m_price',side:'yes',clock:'market_close',
   horizon:'5–10m',price:'.80',events:n,event_wins:n-4,
   contracts:n,cost:.80*n,resolved:n,closed:n,winners:n-4,
   return_observations:n,return_sum:.1*n
 });
 const bot={id:'btc',name:'Bitcoin',asset:'crypto',series:'KXBTC15M',experiment:{entry_timing:[row(49)]}};
 const detail49=favoriteCollectorOverviewMarkup([bot]);
 assert.match(detail49,/n=49 · Early/);
 assert.match(detail49,/Win margin/);
 assert.match(detail49,/win-rate error Pending · 49\/50 events/);
 assert.match(detail49,/90% win-rate error Pending · 49\/50 events/);
 assert.doesNotMatch(detail49,/win-rate error ±/);
 const market49=favoriteTimingMarkup([row(49)]);
 assert.match(market49,/n=49 · Early/);
 assert.match(market49,/win-rate error Pending · 49\/50 events/);
 bot.experiment.entry_timing=[row(50)];
 const detail50=favoriteCollectorOverviewMarkup([bot]);
 assert.match(detail50,/n=50 · Early/);
 assert.match(detail50,/win-rate error ±/);
 assert.doesNotMatch(detail50,/win-rate error Pending/);
 const wide=n=>favoriteWideOverviewMarkup([bot],{
   price_buckets:['78–<86¢'],coverage:{'crypto-15m':{time_buckets:['Early','Middle','Late']}},
   rows:{'crypto-15m':[{band:'78–<86¢',time_slot:1,events:n,
     event_wins:n-4,contracts:n,cost:.8*n,return_observations:n,return_sum:.1*n}]}
 });
 const wider49=wide(49),wider50=wide(50);
 assert.match(wider49,/n=49 · Early/);
 assert.match(wider49,/Win-rate error Pending · 49\/50 events/);
 assert.doesNotMatch(wider49,/90% win-rate interval [0-9]/);
 assert.match(wider50,/n=50 · Early/);
 assert.match(wider50,/Win-rate error ±/);
 assert.match(wider50,/90% win-rate interval [0-9]/);
});

test('regular Favorites never trusts a stale 20-event P/L uncertainty threshold',()=>{
 const report={
   resolved_events:49,event_wins:46,return_observations:49,
   uncertainty_min_samples:20,average_return_pct:'22.0',
   uncertainty90_pct:'1.1',ci90_low_pct:'20.9',ci90_high_pct:'23.1'
 };
 const cell=favoriteSingleCellMarkup(report);
 assert.match(cell,/\+22\.00% Hold P\/L/);
 assert.match(cell,/Pending · 49\/50 held-event returns/);
 assert.doesNotMatch(cell,/±1\.10|90% interval 20\.90/);
 const bot={id:'btc',name:'Bitcoin',asset:'crypto',series:'KXBTC15M',experiment:{entry_timing:[]}};
 const overview=favoriteSingleOverviewMarkup([bot],{rows:{'crypto-15m':report}});
 assert.match(overview,/90% P\/L uncertainty pending 49\/50/);
 assert.match(overview,/Early/);
});

test('low held event counts never display a misleading numeric P/L confidence interval',()=>{
 const tooSmall=favoriteSingleCellMarkup({
   resolved_events:7,event_wins:6,return_observations:7,
   average_return_pct:'17.5',uncertainty90_pct:'5.5',
   ci90_low_pct:'12.0',ci90_high_pct:'23.0',
   estimated_return_observations:0,incomplete_events:0
 });
 assert.match(tooSmall,/\+17\.50% Hold P\/L/);
 assert.match(tooSmall,/90% P\/L uncertainty: Pending · 7\/50 held-event returns/);
 assert.doesNotMatch(tooSmall,/±5\.50|90% interval 12/);
 const stillSmall=favoriteSingleCellMarkup({
   resolved_events:50,event_wins:47,return_observations:49,
   average_return_pct:'19',uncertainty90_pct:'3.5',
   ci90_low_pct:'15.5',ci90_high_pct:'22.5'
 });
 assert.match(stillSmall,/Pending · 49\/50 held-event returns/);
 const ready=favoriteSingleCellMarkup({
   resolved_events:50,event_wins:48,return_observations:50,
   average_return_pct:'12',uncertainty90_pct:'8',
   ci90_low_pct:'4',ci90_high_pct:'20'
 });
 assert.match(ready,/90% P\/L uncertainty: ±8\.00 percentage points/);
 assert.match(ready,/90% interval 4\.00% to 20\.00%/);
 const custom=favoriteSingleCellMarkup({
   resolved_events:50,event_wins:48,return_observations:50,
   uncertainty_min_samples:60,
   average_return_pct:'12',uncertainty90_pct:'8'
 });
 assert.match(custom,/Pending · 50\/60 held-event returns/);
});

test('single bucket reports insufficient ROI observations without inventing uncertainty',()=>{
  const unknown=favoriteSingleCellMarkup(null);
  assert.match(unknown,/Event-level combined evidence is not available/);
  const one=favoriteSingleCellMarkup({resolved_events:1,event_wins:1,
    return_observations:1,average_return_pct:'33.3',uncertainty90_pct:null,
    ci90_low_pct:null,ci90_high_pct:null,incomplete_events:0,estimated_return_observations:0});
  assert.match(one,/\+33\.30% Hold P\/L/);
  assert.match(one,/Pending · 1\/50 held-event returns/);
  assert.doesNotMatch(one,/±0\.00|NaN|undefined/);
  const empty=favoriteSingleCellMarkup({resolved_events:0,event_wins:0,
    return_observations:0,average_return_pct:null,uncertainty90_pct:null,
    ci90_low_pct:null,ci90_high_pct:null});
  assert.match(empty,/n=0 distinct event returns/);
  assert.doesNotMatch(empty,/0\.00% Hold P\/L/);
});

test('single bucket can appear in combined category, sports market and market research',()=>{
  const summary={resolved_events:2,event_wins:1,return_observations:2,
    average_return_pct:'-12.5',uncertainty90_pct:'22',
    ci90_low_pct:'-34.5',ci90_high_pct:'9.5'};
  const sports={id:'sports',label:'Sports',bots:[{id:'sport-a',name:'Sports market',
    series:'KXNBAGAME',asset:'sports',experiment:{entry_timing:[]}}]};
  const overview=favoriteSingleOverviewMarkup(sports.bots,
    {rows:{sports:summary},by_bot:{'sport-a':summary}},new Set(['favorites-collector-sports']));
  assert.match(overview,/Sports market/);
  assert.match(overview,/\-12\.50% Hold P\/L/);
  assert.equal((overview.match(/favorite-single-matrix/g)||[]).length,2);
  const category=favoriteCategoryResearchMarkup(sports,new Set(),{mode:'single',singleSummary:{rows:{sports:summary}}});
  assert.match(category,/favorite-single-matrix/);
  assert.doesNotMatch(category,/favorite-wide-matrix/);
  const bot=favoriteResearchMarkup(sports.bots,new Set(),{mode:'single',singleSummary:{by_bot:{'sport-a':summary}}});
  assert.match(bot,/favorite-single-matrix/);
});

test('single bucket displays P/L, 90% uncertainty and event n directly on collapsed category headers',()=>{
  const bots=[{id:'btc',name:'Bitcoin',series:'KXBTC15M',asset:'crypto',
    experiment:{entry_timing:[]}}];
  const summary={rows:{'crypto-15m':{
    resolved_events:53,event_wins:48,return_observations:51,
    average_return_pct:'3.456',uncertainty90_pct:'2.345',
    ci90_low_pct:'1.111',ci90_high_pct:'5.801',incomplete_events:2
  }},by_bot:{}};
  const html=favoriteSingleOverviewMarkup(bots,summary);
  const head=html.slice(html.indexOf('<summary>'),html.indexOf('</summary>')+10);
  assert.match(head,/favorite-single-headline/);
  assert.match(head,/Hold P\/L \+3\.46%/);
  assert.match(head,/90% ±2\.35 points/);
  assert.match(head,/n=51/);
  assert.doesNotMatch(head,/NaN|undefined/);
  assert.match(html,/favorite-single-matrix/,'full evidence remains available when expanded');
  const sparse=favoriteSingleOverviewMarkup(bots,{rows:{'crypto-15m':{
    resolved_events:1,return_observations:1,average_return_pct:'-10',
    uncertainty90_pct:null
  }}});
  assert.match(sparse,/Hold P\/L -10\.00%/);
  assert.match(sparse,/90% P\/L uncertainty pending 1\/50/);
  assert.doesNotMatch(sparse,/90% ±0\.00 points/);
});

test('90 percent Wilson uncertainty remains nonzero at perfect accuracy and decreases with independent sample size',()=>{
 assert.equal(winConfidence90(0,0,.8),null);
 const c=winConfidence90(90,100,.8),larger=winConfidence90(360,400,.8);
 assert.ok(c.low<.9&&c.high>.9);assert.ok(c.error>larger.error);
 assert.ok(Math.abs(c.margin-.1)<1e-12);
 const perfect=winConfidence90(10,10,.9);assert.ok(perfect.error>0&&perfect.low<1);
 const html=favoriteCategoryResearchMarkup({id:'crypto-15m',label:'Crypto',bots:[{experiment:{entry_timing:[{
  series:'KXBTC15M',market_type:'15m_price',price:'.8',horizon:'5–10m',clock:'market_close',
  contracts:100,cost:80,closed:100,net:10,events:100,event_win_rate:90}]}}]});
 assert.match(html,/90% win-rate interval/);assert.match(html,/\+10\.0 points/);
});

test('Add funds opens the selected folder dialog through the stable click handler',()=>{
 const {nodes,listeners}=setup(fixture());
 const button={dataset:{folderRefill:'favorites'}};
 let stopped=false,prevented=false;
 listeners.get('click')({
  target:{closest:selector=>selector==='[data-folder-refill]'?button:null},
  preventDefault(){prevented=true},stopPropagation(){stopped=true}
 });
 assert.equal(nodes.get('refillDialog').open,true);
 assert.equal(nodes.get('refillName').textContent,'High-Probability Favorites');
 assert.ok(prevented&&stopped);
});

test('collapsed folder and at-a-glance summaries display current estimated balance',()=>{
 const folder=fixture().folders[2];
 folder.accounting.portfolio={cash:'975',equity:'1005',deposits:'1000',total_pnl:'5',position_cost:'30'};
 const collapsed=folderCardSummaryMarkup(folder);
 const overview=folderOverviewMarkup([folder]);
 for(const html of [collapsed,overview]){
  assert.ok(html.includes('Estimated portfolio value'));
  assert.ok(html.includes('$1,005.00'));
  assert.ok(html.includes('Total P/L'));
 }
});

test('strategy header places estimated portfolio value ahead of P/L, exposure and bot count',()=>{
 const folder=fixture().folders[2];
 folder.accounting.portfolio={cash:'1025',equity:'1050',deposits:'1000',total_pnl:'50',position_cost:'25'};
 const header=folderCardSummaryMarkup(folder,'all',{bots:2,running:2});
 const overview=folderOverviewMarkup([folder]);
 assert.ok(header.includes('Estimated portfolio value'));
 assert.ok(header.indexOf('Estimated portfolio value')<header.indexOf('Total P/L'));
 assert.ok(header.indexOf('Estimated portfolio value')<header.indexOf('2/2 running'));
 assert.ok(overview.indexOf('<th>Estimated portfolio value</th>')<overview.indexOf('<th>Total P/L'));
 assert.ok(overview.includes('$1,050.00'));
});
test('invalid folder refill never silently falls back to legacy Convexity account',()=>{
 const source=fs.readFileSync(new URL('../apps/web/shadow.mjs',import.meta.url),'utf8');
 assert.match(source,/folder_id:folder,request_id:refillRequest/);
 assert.match(source,/No funds were added/);
 assert.match(source,/Never retry as an unscoped refill/);
});


test('Daily Weather wider view retains its verified table when three-way timing is unobservable',()=>{
 const bots=[{id:'weather',name:'New York',series:'KXHIGHNY',asset:'weather_daily',
   desired:'running',experiment:{entry_timing:[]}}];
 const aggregate={series:'combined',market_type:'weather_daily',
   clock:'weather_local_day_end',price:'.80',horizon:'>=2h',
   events:19,event_wins:15,contracts:'19',cost:'15.20',
   return_observations:19,return_sum:'1.4'};
 const original={rows:{'weather-daily':[aggregate]},coverage:{'weather-daily':{
   bots_total:1,bots_with_rows:1}}};
 const single={rows:{'weather-daily':{
   resolved_events:19,event_wins:15,return_observations:19,
   average_return_pct:'7.3',uncertainty90_pct:null}}};
 const wide={rows:{'weather-daily':[]},coverage:{'weather-daily':{
   reason:'Waiting for an observed betting window with distinct entry times',
   time_basis:'observed_entry_window',excluded_legacy_observations:0}}};
 const rendered=favoriteWideOverviewMarkup(bots,wide,new Set(),new Set(),
   {timed:original,single});
 assert.match(rendered,/Daily weather/);
 assert.match(rendered,/Three equal entry-time thirds are not verifiable/);
 assert.match(rendered,/favorite-stat-matrix/);
 assert.match(rendered,/n=19/);
 assert.match(rendered,/&gt;=2h/);
 assert.doesNotMatch(rendered,/Waiting for exact entry times to establish the betting window/);
 const market=favoriteTimingMarkup([aggregate],[],{mode:'wide',single:single.rows['weather-daily']});
 assert.match(market,/Exact time thirds unavailable/);
 assert.match(market,/favorite-stat-matrix/);
 assert.match(market,/n=19/);
 const stillWide=favoriteWideOverviewMarkup(bots,{
   rows:{'weather-daily':[{band:'70–<78¢',time_slot:0,events:1,event_wins:1,
     cost:'.7',contracts:'1',return_observations:1,return_sum:'.42'}]},
   coverage:{'weather-daily':{time_buckets:['1m–2m','2m–3m','3m–4m']}}},new Set(),
   new Set(),{timed:original,single});
 assert.match(stillWide,/favorite-wide-matrix/);
 assert.doesNotMatch(stillWide,/Three equal entry-time thirds are not verifiable/);
});

test('period-specific filled-event subtitles follow P/L headings and never count contracts',()=>{
 const filled={all:{count:19,complete:false},'1H':{count:2,complete:true},
   '6H':{count:5,complete:true},'24H':{count:8,complete:false},
   '7D':{count:10,complete:false},'30D':{count:12,complete:false}};
 assert.match(filledEventsSmall(filled,'all'),/≥19 filled events · partial history/);
 assert.match(filledEventsSmall(filled,'1H'),/>2 filled events</);
 assert.doesNotMatch(filledEventsSmall(filled,'1H'),/partial history/);
 assert.equal(filledEventsSmall({},'1H'),'');
 const d=fixture(),folder=d.folders.find(f=>f.id==='favorites');
 folder.filled_events=filled;folder.accounting.portfolio={
   cash:'1000',equity:'1002',total_pnl:'2',deposits:'1000',position_cost:'0'};
 const bot=d.bots.find(b=>b.id==='favorites');
 bot.experiment.filled_events=filled;
 bot.account={total_pnl:'2',realized_pnl:'2',unrealized_pnl:'0'};
 bot.performance={'1H':{pnl:'1'},'24H':{pnl:'2'}};
 const group={id:'crypto-15m',label:'Crypto · 15 minutes',bots:[bot]};
 for(const html of [
   folderOverviewMarkup([folder],'1H'),
   folderCardSummaryMarkup(folder,'1H'),
   marketTypeSummaryMarkup(group,'1H',[],null,[],filled),
   botPnlMarkup(bot,'1H'),
   botPnlDetailsMarkup(bot,'1H')
 ])assert.match(html,/2 filled events/,html.slice(0,180));
 for(const html of [
   folderOverviewMarkup([folder],'all'),
   folderCardSummaryMarkup(folder,'all'),
   marketTypeSummaryMarkup(group,'all',[],null,[],filled),
   botPnlMarkup(bot,'all')
 ])assert.match(html,/≥19 filled events · partial history/);
 assert.match(folderCardSummaryMarkup(folder,'24H'),/≥8 filled events · partial history/);
 const noFill=fixture().folders[2];
 assert.doesNotMatch(folderCardSummaryMarkup(noFill),/filled events/);
});

test('actual folder time selector updates filled-event number beneath P/L',()=>{
 const d=fixture(),f=d.folders[2];f.filled_events={
   all:{count:19,complete:false},'1H':{count:2,complete:true},
   '6H':{count:4,complete:true}};
 const select={dataset:{summaryFolder:'favorites',folderSummaryPeriod:'1H'}};
 const {nodes}=setup(d,{queries:{'[data-folder-summary-period]':[select]}});
 assert.match(nodes.get('groups').innerHTML,/≥19 filled events/);
 select.onclick({preventDefault(){},stopPropagation(){}});
 assert.match(nodes.get('groups').innerHTML,/2 filled events/);
 assert.doesNotMatch(nodes.get('groups').innerHTML,/≥19 filled events/);
});

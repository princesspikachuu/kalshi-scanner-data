"""Independent paper maker portfolios with covered inventory and bounded screening."""
import asyncio,json,re,time,math
from decimal import Decimal as D
from uuid import uuid4
from .scalper import VolatilityScalper,CONFIGS,EXECUTION_DEFAULTS
from .storage import entry
from .runner import ts

MM_FOLDERS=('market_maker','maker_competitive')
CATEGORIES={'politics':'Politics','economics':'Economics / Finance','sports_futures':'Sports Futures','entertainment':'Entertainment / Culture'}
MM_CONFIG=dict(approach='market_maker',adaptive=True,mixed=False,maker_profit_exits=True,take_profit=.01,
    stop_loss=.08,min_hold=0,max_hold=14400,liquidate=3600,reduce_hold=21600,restrict_entries=86400,
    order_ttl=300,exit_ttl=120,reprice_seconds=30,reprice_ticks=2,eval_seconds=5,
    min_remaining=86400,min_price=.20,max_price=.80,min_spread=.03,min_trades_24h=30,
    max_sigma=.025,depth_fraction=.20,market_exposure=.04,event_exposure=.08,category_exposure=.15,
    portfolio_exposure=.40,pre_event=900,post_event=300,category_phases={})

def category(event):
    primary=str(event.get('category','')).lower();text=(event.get('series_ticker','')+' '+event.get('title','')).lower()
    if re.search(r'bitcoin|ethereum|crypto|weather|temperature|rainfall|snowfall|15m|hourly',text+' '+primary):return None
    if primary in ('politics','elections'):return 'politics'
    if primary in ('economics','financials','finance','economy'):return 'economics'
    if primary in ('entertainment','culture','awards','social'):return 'entertainment'
    if primary=='sports' and not re.search(r'game|match|spread|total points',text) and re.search(r'champion|division|season|playoff|award|mvp|winner|cup|title',text):return 'sports_futures'
    return None

def profiles():
    for folder in MM_FOLDERS:
        for key,label in CATEGORIES.items():
            yield dict(id=folder+'_'+key,series='MM_'+key.upper(),name=label,asset='market_maker',market_category=key,
                underlying=label,folder_id=folder,strategy='market_maker',contracts=5,live_enabled=False,
                version='maker-1',config=dict(MM_CONFIG,**(dict(min_spread=.02,reprice_ticks=1) if folder=='maker_competitive' else {})))

def initialize_market_maker(store,guard):
    marker='shadow/market-maker-v1'
    if store.get(marker):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        def add(key,p,s):
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",entry(key,p,s))
        for i,folder in enumerate(MM_FOLDERS):
            add('demo/shadow/folder/'+folder,dict(id=folder,name='Market Maker'+(' · Competitive quotes' if i else ''),strategy='market_maker',order=6+i/10,
                description='Maker-first paper spread capture. Stable, actively traded long-duration markets; independent virtual capital; incentives excluded from P/L.'),dict(session=str(uuid4()),created_at=now))
        for p in profiles():add('demo/shadow/bot/'+p['id'],dict(p,key=str(uuid4()),revision=1,changed_at=now),dict(desired='running'))
        add('demo/'+marker,{},dict(at=now,real_orders_enabled=False))

class MarketMaker(VolatilityScalper):
    def __init__(self,engine,profile):
        super().__init__(engine,dict(profile,config=dict(MM_CONFIG,**profile.get('config',{}))))
        self.profile=profile;self.config=dict(EXECUTION_DEFAULTS,**MM_CONFIG);self.config.update(profile.get('config',{}))
    def refresh_config(self):
        self.config=dict(EXECUTION_DEFAULTS,**MM_CONFIG);self.config.update(self.profile.get('config',{}))
    def phase(self,ticker):
        c=dict(self.config);c['restrict_entries']=max(c['liquidate']+60,c['min_remaining']);return c
    def matches(self,ticker,market):return market.get('market_maker') and market.get('market_category')==self.profile['market_category']
    def decision(self,f):
        c=self.config
        signal=(c['min_price']<=f['bid']<=c['max_price'] and f['spread']>=c['min_spread'] and f['sigma']<=c['max_sigma'])
        adverse=(f['trend']<-max(.025,2*f['sigma']) or f.get('trade_pressure',0)<-.7 or f.get('depth_withdrawal',0)>.5)
        return signal,adverse,max(.01,f['spread']-.02)
    def step(self,changed_ticker=None):
        # Announcements are sourced from linked exchange milestones only.
        # Unknown schedules use observed liquidity/momentum protection.
        now=self.e.now
        for t,m in self.e.markets.items():
            if not self.matches(t,m):continue
            paused=t in self.profile.get('paused_markets',[])
            quiet=now-m.get('discovered_at',now)>300 and not any(now-print[0]<120 for print in self.e.tape.state(t)['trades'])
            window=any(at-self.config['pre_event']<=now<=at+self.config['post_event'] for at in m.get('scheduled_events',[]))
            if paused or window or quiet:
                for o in self.active_orders(t):
                    if o.action=='buy':self.e.cancel(o.id)
            m['maker_entry_blocked']=paused or window or quiet;m['maker_event_window']=window
        super().step(changed_ticker)
    def research_snapshot(self):
        result=super().research_snapshot()
        result['market_maker']=True;result['incentive_profit']='0';result['reward_estimates_enabled']=False
        result['markets']=[dict(ticker=t,title=m.get('title',t),category=m['market_category'],close=m['close'],
            paused=t in self.profile.get('paused_markets',[]),schedule_source=m.get('schedule_source','unavailable'),
            incentives=m.get('incentives',[]),score=m.get('maker_score'),trades_24h=m.get('trades_24h'),
            entry_blocked=m.get('maker_entry_blocked',False),position=str(sum((l.quantity for l in self.e.wallet.lots if l.ticker==t),D(0))),
            orders=sum(o.ticker==t and o.status in ('pending','resting') for o in self.e.orders.values()))
            for t,m in self.e.markets.items() if self.matches(t,m) and not m.get('paid')][:20]
        return result

def schedule_times(milestones,event):
    result=[]
    for m in milestones:
        linked=event in (m.get('related_event_tickers',[])+m.get('primary_event_tickers',[]))
        if not linked:continue
        try:result.append(ts(m['start_date']))
        except (KeyError,ValueError,TypeError):pass
    return sorted(set(result))[:20]

async def maker_once(host):
    suite=host.experiments;now=time.time()
    if not hasattr(suite,'maker_discovery'):
        suite.maker_discovery=dict(cursor='',candidates={},reads=0,next_at=0,incentive_at=0,incentives={},settlement_at={},rejected={})
    s=suite.maker_discovery
    if now<s['next_at']:return
    s['next_at']=now+30
    # Settlement is independent of discovery/admission and survives closed books.
    held={t:m for folder,(e,_,_) in suite.portfolios.items() if folder in MM_FOLDERS for t,m in e.markets.items() if not m.get('paid')}
    for ticker,m in [(t,m) for t,m in held.items() if m['close']<=now and now>=s['settlement_at'].get(t,0)][:4]:
        if m['close']>now or now<s['settlement_at'].get(ticker,0):continue
        s['settlement_at'][ticker]=now+60
        raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market'];s['reads']+=1
        if raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
            await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))
    choices=suite.enabled_profiles('market_maker')
    if not choices:return
    limits=suite.monitoring_snapshot(now)
    if not limits['admitting']:
        s['state']='Discovery waits for healthy processing';return
    if now>=s['incentive_at']:
        s['incentive_at']=now+3600
        try:
            programs=await asyncio.to_thread(host.verified_data.call,'GET','/incentive_programs',dict(limit=100));s['reads']+=1
            known={}
            for p in programs.get('incentive_programs',[]):
                if p.get('incentive_type')!='liquidity' or p.get('paid_out'):continue
                if ts(p['start_date'])<=now<ts(p['end_date']):
                    known.setdefault(p['market_ticker'],[]).append({k:p.get(k) for k in ('id','incentive_description','description','start_date','end_date','period_reward','target_size_fp','discount_factor_bps')})
            s['incentives']=known
        except Exception:s['incentives']={};s['incentive_status']='unavailable; estimates disabled'
    minimum=max(21600,min(p.get('config',{}).get('min_remaining',86400) for p in choices))
    result=await asyncio.to_thread(host.verified_data.call,'GET','/events',dict(status='open',limit=50,with_nested_markets='true',with_milestones='true',min_close_ts=int(now+minimum),cursor=s['cursor']));s['reads']+=1
    s['cursor']=result.get('cursor','')
    for event in result.get('events',[]):
        group=category(event)
        if not group:continue
        for raw in event.get('markets',[]):
            try:
                if raw.get('status')!='active' or ts(raw['open_time'])>now or ts(raw['close_time'])-now<minimum:continue
                bid=float(raw.get('yes_bid_dollars') or float(raw.get('yes_bid',0))/100);no=float(raw.get('no_bid_dollars') or float(raw.get('no_bid',0))/100)
                spread=1-bid-no;volume=float(raw.get('volume_24h_fp') or raw.get('volume_24h') or 0)
                if not (.1<=bid<=.9 and 0.019<=spread<=.25 and volume>=30):continue
                score=spread*math.log1p(volume)/(max(.1,bid)*max(1,math.sqrt((ts(raw['close_time'])-now)/86400)))
                s['candidates'][raw['ticker']]=dict(raw=raw,event={k:event[k] for k in ('series_ticker','title','category') if k in event},category=group,score=score,at=now,milestones=result.get('milestones',[]))
            except (KeyError,TypeError,ValueError):continue
            if len(s['candidates'])>120:s['candidates']=dict(sorted(s['candidates'].items(),key=lambda x:-x[1]['score'])[:100])
    # Keep a broad, bounded near-miss pool; inspect only one ranked candidate per pass.
    s['candidates']={t:r for t,r in sorted(s['candidates'].items(),key=lambda x:-x[1]['score']) if now-r['at']<3600 and ts(r['raw']['close_time'])>now}
    s['candidates']=dict(list(s['candidates'].items())[:100])
    active=set(suite.feed_markets());maker_active={t for t,m in suite.feed_markets().items() if m.get('market_maker')}
    s['ranked']=[dict(ticker=t,category=r['category'],score=r['score'],reason=r.get('reason','awaiting trade-frequency verification')) for t,r in list(s['candidates'].items())[:20]]
    if len(maker_active)>=2 or not suite.search_capacity('market_maker',time.time()):s['state']='Shared capacity occupied; existing strategies preserved';return
    checked=0;s['state']='Inspecting candidates'
    for ticker,row in s['candidates'].items():
        if ticker in active or now<row.get('retry_at',0):continue
        ps=[p for p in choices if p['market_category']==row['category']]
        if not ps:continue
        if checked>=1:break
        checked+=1
        row['retry_at']=now+300;raw=row['raw']
        trades=await asyncio.to_thread(host.verified_data.call,'GET','/markets/trades',dict(ticker=ticker,min_ts=int(now-86400),limit=100));s['reads']+=1
        prints=[t for t in trades.get('trades',[]) if not t.get('is_block_trade') and now-86400<=ts(t['created_time'])<=now]
        prices=[float(t['yes_price_dollars']) for t in prints]
        count=len(prints);required=min(p.get('config',{}).get('min_trades_24h',30) for p in ps)
        if count<required:row['reason']='insufficient_executed_trade_frequency';continue
        if len(prices)>1 and max(prices)-min(prices)>.20:row['reason']='recent_trade_prices_unstable';continue
        book=await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker+'/orderbook',dict(depth=3));s['reads']+=1
        levels=book.get('orderbook_fp',{});depth=min(sum(float(x[1]) for x in levels.get(side+'_dollars',levels.get(side+'_dollars_fp',[]))) for side in ('yes','no'))
        if depth<max(p['contracts'] for p in ps)*4:row['reason']='insufficient_displayed_depth';continue
        fee=await host.fee_policy(raw,{});schedule=schedule_times(row['milestones'],raw['event_ticker'])
        await host.put('maker_market',dict(market=dict(ticker=ticker,event_ticker=raw['event_ticker'],series_ticker=row['event']['series_ticker'],title=raw.get('title',ticker),
            open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,market_maker=True,market_category=row['category'],
            maker_score=row['score'],trades_24h=count,scheduled_events=schedule,schedule_source='Kalshi linked milestones' if schedule else 'unavailable; market-data protections active',
            incentives=s['incentives'].get(ticker,[]),price_ranges=raw.get('price_ranges',[])),taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
        row['reason']='submitted_for_shared_monitoring';s['state']='Verified candidate submitted';break
    s['ranked']=[dict(ticker=t,category=r['category'],score=r['score'],reason=r.get('reason','awaiting trade-frequency verification')) for t,r in list(s['candidates'].items())[:20]]
    if s.get('state')!='Verified candidate submitted':s['state']='Candidate inspection complete' if s['candidates'] else 'No eligible candidates in the current event page'
    print(json.dumps(dict(event='market_maker_scan',at=now,listed_events=len(result.get('events',[])),candidate_count=len(s['candidates']),state=s.get('state'),reads=s['reads'],ranked=s.get('ranked',[]),shared_active=len(maker_active),reward_estimates_enabled=False,real_orders_enabled=False)),flush=True)

async def discover_maker(host):
    while not host.done.is_set():
        try:await maker_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:print(json.dumps(dict(event='market_maker_retry',error=type(exc).__name__,code=getattr(exc,'code',None),real_orders_enabled=False)),flush=True)
        await asyncio.sleep(15)

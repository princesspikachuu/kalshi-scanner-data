"""Hourly/daily weather favorites on the shared, read-only production feed."""
import asyncio,json,time
from uuid import uuid4
from .runner import ts
from .storage import put
from services.research.reports import SERIES

WEATHER_DESCRIPTION='Tests 70–95¢ maker purchases in 15-minute, hourly weather and daily weather markets with evidence-based exits. Favorite bias remains a hypothesis.'

def weather_profiles():
    return [dict(id='fav_'+s.lower(),series=s,name=('Hourly weather · ' if category=='weather' else 'Daily weather · ')+s,
                 asset=category,contracts=10,folder_id='favorites',strategy='favorites',version='favorites-weather-1')
            for category in ('weather','weather_daily') for s in sorted(SERIES[category])]

def initialize_weather(store,guard):
    if store.get('shadow/weather-layout'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/weather-layout'").fetchone():return
        # Preserve the folder session, balance, evidence and existing controls.
        existing=c.execute("SELECT progress FROM research_job WHERE idempotency_key='demo/shadow/bot/fav_btc'").fetchone()
        desired=existing['progress'].get('desired','running') if existing else 'running'
        for p in weather_profiles():
            key='demo/shadow/bot/'+p['id']
            if not c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(key,)).fetchone():
                put(c,key,dict(p,key=str(uuid4()),revision=1,changed_at=now),dict(desired=desired))
        c.execute("UPDATE research_job SET parameters=jsonb_set(parameters,'{description}',to_jsonb(%s::text)) WHERE idempotency_key='demo/shadow/folder/favorites'",(WEATHER_DESCRIPTION,))
        put(c,'demo/shadow/weather-layout',{},dict(at=now,series=len(weather_profiles())))
    print(json.dumps(dict(event='paper_weather_initialized',hourly_bots=len(SERIES['weather']),daily_bots=len(SERIES['weather_daily']),real_orders_enabled=False)),flush=True)

def candidates(rows,series,now):
    """Each contract is independent; never infer exclusivity from thresholds."""
    found=[m for m in rows if m.get('ticker','').startswith(series+'-') and m.get('status')=='active'
           and ts(m['open_time'])<=now and 60<ts(m['close_time'])-now<=86400]
    # Prefer usable favorites, then nearest close and executable-looking volume.
    def rank(m):
        bids=[float(m.get(k) or 0) for k in ('yes_bid_dollars','no_bid_dollars')]
        if not any(bids):bids=[float(m.get(k) or 0)/100 for k in ('yes_bid','no_bid')]
        return (not any(.69<=b<=.95 for b in bids),ts(m['close_time']),-float(m.get('volume_fp') or m.get('volume') or 0),m['ticker'])
    return sorted(found,key=rank)

async def weather_once(host):
    suite=host.experiments;e,f,ps=suite.portfolios['favorites'];now=time.time()
    profiles=[p for p in ps if p.get('asset') in ('weather','weather_daily')]
    # Two slots per category, within ten total extra subscriptions and twenty-two
    # total warm fee policies. Filled inventory always keeps its subscription.
    cap=max(0,min(10,22-sum(m['close']>now for m in host.engine.markets.values())))
    for category in ('weather','weather_daily'):
        active=[t for t,m in e.markets.items() if m.get('weather_category')==category and not m.get('paid')]
        if len(active)>=2 or len(suite.extra)>=cap:continue
        choices=[p for p in profiles if p['asset']==category and f.bots[p['series']].enabled]
        if not choices:continue
        index=suite.weather_cursor.get(category,0)%len(choices);p=choices[index]
        suite.weather_cursor[category]=index+1
        result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=p['series'],
            min_close_ts=int(now+60),max_close_ts=int(now+86400),limit=1000,cursor=suite.weather_pages.get(p['series'],'')))
        suite.weather_pages[p['series']]=result.get('cursor','')
        for m in candidates(result.get('markets',[]),p['series'],now):
            if m['ticker'] in e.markets:continue
            fee=await host.fee_policy(m,{})
            await host.put('weather_market',dict(market=dict(ticker=m['ticker'],event_ticker=m['event_ticker'],
                series_ticker=p['series'],close=ts(m['close_time']),open=ts(m['open_time']),discovered_at=now,weather_category=category),
                taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
            break
    # Settlement requires the exchange result, even after the daily close.
    due=[t for t,m in e.markets.items() if m.get('weather_category') and not m.get('paid') and m['close']<=now]
    for ticker in due[:4]:
        raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
        if raw.get('ticker')==ticker and raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
            await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))

async def discover_weather(host):
    while not host.done.is_set():
        try:await weather_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:
            print(json.dumps(dict(event='paper_weather_retry',error=type(exc).__name__,real_orders_enabled=False)),flush=True)
        await asyncio.sleep(15)

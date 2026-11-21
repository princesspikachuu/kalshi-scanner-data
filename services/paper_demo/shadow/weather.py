"""Hourly/daily weather favorites on the shared, read-only production feed."""
import asyncio,json,time
from uuid import uuid4
from .runner import ts
from .storage import put
from .discovery_budget import candidate_markets,next_profile
from .hourly import favorite_bid
from .weather_window import CITY_ZONES,entry_allowed
from .settlement_recovery import due_for_confirmation
from services.research.reports import SERIES

WEATHER_DESCRIPTION='Tests 70–95¢ maker purchases in 15-minute, hourly weather and daily weather markets and holds until authoritative settlement. Daily entries are limited to the city’s final two hours. Favorite bias remains a hypothesis.'

def weather_profiles():
    return [dict(id='fav_'+s.lower(),series=s,name=('Hourly weather · ' if category=='weather' else 'Daily weather · ')+s,
                 asset=category,contracts=1,folder_id='favorites',strategy='favorites',version='favorites-weather-1')
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
           and ts(m['open_time'])<=now and 60<ts(m['close_time'])-now<=86400
           and (series not in CITY_ZONES or entry_allowed(dict(m,close=ts(m['close_time'])),now))]
    # Prefer usable favorites, then nearest close and executable-looking volume.
    def rank(m):
        return (favorite_bid(m) is None,ts(m['close_time']),-float(m.get('volume_fp') or m.get('volume') or 0),m['ticker'])
    return sorted(found,key=rank)

async def weather_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    scan=dict(at=now,categories={})
    for category in ('weather_daily','weather'):
        # Daily contracts have a single closing opportunity. Give them first
        # consideration within the existing shared capacity and fee checks.
        row=scan['categories'].setdefault(category,dict(reason='not_scanned',eligible=0,closing_within_hour=0,subscribed=0))
        if not suite.search_capacity(category,now):
            row['reason']='shared_monitoring_capacity_paused'
            continue
        choices=suite.enabled_profiles(category)
        if not choices:
            row['reason']='no_enabled_profiles'
            continue
        active=candidate_markets(suite,markets,category,now)
        p,cursor=next_profile(suite,choices,active,suite.weather_cursor.get(category,0))
        if not p:
            row['reason']='each_series_already_has_candidate'
            continue
        row['series']=p['series']
        suite.weather_cursor[category]=cursor
        result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=p['series'],
            min_close_ts=int(now+60),max_close_ts=int(now+86400),limit=1000,cursor=suite.weather_pages.get(p['series'],'')))
        suite.weather_pages[p['series']]=result.get('cursor','')
        listed=candidates(result.get('markets',[]),p['series'],now)
        row['eligible']=len(listed)
        row['closing_within_hour']=sum(ts(m['close_time'])-now<3600 for m in listed)
        row['reason']='no_active_eligible_market' if not listed else 'candidate_unavailable_or_excluded'
        for m in listed:
            if m['ticker'] in markets or not suite.candidate_allowed(m['ticker'],now):continue
            fee=await host.fee_policy(m,{})
            if fee.maker_multiplier!=0 or not host.verified_fees.zero_maker_fees_until(
                    m['ticker'],now,ts(m['close_time'])):
                row['reason']='nonzero_or_unverified_maker_fee'
                break
            await host.put('weather_market',dict(market=dict(ticker=m['ticker'],event_ticker=m['event_ticker'],
                series_ticker=p['series'],close=ts(m['close_time']),open=ts(m['open_time']),discovered_at=now,weather_category=category),
                taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
            row['subscribed']=1
            row['reason']='submitted_to_monitoring'
            break
    suite.weather_scan=scan
    if now>=getattr(suite,'weather_scan_log_at',0):
        suite.weather_scan_log_at=now+60
        print(json.dumps(dict(event='paper_weather_scan',**scan,real_orders_enabled=False)),flush=True)
    # Only the exchange's finalized result may authorize a paper payout.
    # Held lots have their own independent, fair recovery loop. Avoid duplicate
    # REST reads here and rotate the remaining weather markets fairly.
    held={lot.ticker for engine,_,_ in suite.portfolios.values() for lot in engine.wallet.lots if lot.quantity>0}
    pending={t:m for t,m in suite.settlement_markets().items()
             if m.get('weather_category') and not m.get('paid') and m['close']<=now and t not in held}
    checks=getattr(host,'weather_settlement_checks',None)
    if not isinstance(checks,dict):checks=host.weather_settlement_checks={}
    for ticker in due_for_confirmation(pending,checks,now):
        checks[ticker]=now
        try:
            raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
            if raw.get('ticker')==ticker and raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
                await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(json.dumps(dict(event='paper_weather_settlement_retry',ticker=ticker,
                error=type(exc).__name__,real_orders_enabled=False)),flush=True)
    for ticker in list(checks):
        if ticker not in pending:del checks[ticker]

async def discover_weather(host):
    while not host.done.is_set():
        try:await weather_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:
            print(json.dumps(dict(event='paper_weather_retry',error=type(exc).__name__,code=getattr(exc,'code',None),real_orders_enabled=False)),flush=True)
        await asyncio.sleep(15)

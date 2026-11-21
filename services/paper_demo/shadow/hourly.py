"""Verified hourly-series favorites; bounded fast scans on the shared read budget."""
import asyncio,json,time
from decimal import Decimal as D,ROUND_FLOOR
ZERO=D(0)
from .runner import ts
from .schedules import session_wake
from .discovery_wake import asleep,remember,known_entry_wake
from .discovery_budget import candidate_markets,next_profile


def favorite_bid(m):
    bids=[D(str(m.get(k) or 0)) for k in ('yes_bid_dollars','no_bid_dollars')]
    if not any(bids):bids=[D(str(m.get(k) or 0))/100 for k in ('yes_bid','no_bid')]
    prices=[]
    for i,bid in enumerate(bids):
        opposite=bids[1-i]
        if bid<=0 or opposite<=0:continue
        price=min(bid+D('.01'),D(1)-opposite-D('.01'),D('.95')).quantize(D('.01'),rounding=ROUND_FLOOR)
        if D('.70')<=price<=D('.95'):prices.append(price)
    return max(prices,default=None)


FINANCE_PREFIXES=('KXUSDCAD','KXAUDUSD','KXUSDJPY','KXGBPUSD','KXEURUSD',
                 'KX2YRRATE','KX5YRRATE','KX10YRRATE','KX30YRRATE',
                 'KXINX','KXNDQ','KXNASDAQ100')
COMMODITY_PREFIXES=('KXGOLD','KXSILVER','KXPLATINUM','KXPALLADIUM',
                    'KXCOPPER','KXWTI','KXNATGAS','KXBRENT')

def hourly_category(series):
    return ('finance' if series.startswith(FINANCE_PREFIXES) else
            'commodities' if series.startswith(COMMODITY_PREFIXES) else 'crypto_or_other')


def balanced_hourly_profiles(profiles):
    """Interleave categories so short bounded scans reach Finance too.

    This does not expand the existing shared subscription/read budgets or
    imply that an individual series is actually eligible for an order.
    """
    groups=[[],[],[]]
    for p in profiles:
        series=p['series']
        group={'crypto_or_other':0,'commodities':1,'finance':2}[hourly_category(series)]
        groups[group].append(p)
    ordered=[]
    for index in range(max((len(g) for g in groups),default=0)):
        for group in groups:
            if index<len(group):ordered.append(group[index])
    return ordered


def next_hourly_profile(profiles, blocked, cursor, active):
    """Give the next free slot to the least represented hourly category."""
    counts={kind:sum(hourly_category(t.split('-')[0])==kind for t in active)
            for kind in ('finance','commodities','crypto_or_other')}
    choices=[]
    for offset in range(len(profiles)):
        index=(cursor+offset)%len(profiles);profile=profiles[index]
        if any(t.startswith(profile['series']+'-') for t in blocked):continue
        choices.append((counts[hourly_category(profile['series'])],offset,index,profile))
    if not choices:return None,cursor
    _,_,index,profile=min(choices,key=lambda choice:choice[:2])
    return profile,index+1


async def hourly_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    if not hasattr(suite,'hourly_metadata'):suite.hourly_metadata={};suite.hourly_retry_at={}
    if not hasattr(suite,'hourly_coverage'):suite.hourly_coverage={}
    active=candidate_markets(suite,markets,'hourly',now)
    ps=balanced_hourly_profiles(suite.enabled_profiles('hourly'));staged=0
    scan=dict(at=now,checked_series=0,listed_markets=0,eligible_markets=0,subscribed=0,metadata_checks=0,
              reason='No eligible listed favorite',by_category={})
    # Three profiles per pass rather than one per 15 seconds. Empty/incompatible
    # series back off; stable frequency metadata is cached independently of fees.
    for _ in range(min(3,len(ps))):
        blocked=active+[p['series']+'-cooldown' for p in ps
            if suite.hourly_retry_at.get(p['series'],0)>now or
               asleep(suite,'hourly:'+p['series'],now)]
        p,cursor=next_hourly_profile(ps,blocked,suite.hourly_cursor,active)
        if not p:break
        suite.hourly_cursor=cursor;series=p['series'];scan['checked_series']+=1
        category=scan['by_category'].setdefault(hourly_category(series),dict(checked=0,eligible=0,subscribed=0,capacity_blocked=0))
        category['checked']+=1
        wake=session_wake(series,now)
        if wake is not None:
            suite.hourly_retry_at[series]=wake
            remember(suite,'hourly:'+series,wake,now)
            suite.hourly_coverage[series]=dict(at=now,active_markets=0,eligible_markets=0,next_check_at=wake,
                reason='Cash-index session closed · scheduled to resume before the next opening')
            continue
        metadata=suite.hourly_metadata.get(series)
        if not metadata or now-metadata['at']>=900:
            raw=await asyncio.to_thread(host.verified_data.call,'GET','/series/'+series)
            metadata=dict(at=now,frequency=raw.get('series',{}).get('frequency'))
            suite.hourly_metadata[series]=metadata;scan['metadata_checks']+=1
        if metadata['frequency']!='hourly':
            suite.hourly_coverage[series]=dict(at=now,active_markets=0,eligible_markets=0,reason='Series frequency '+str(metadata['frequency'])+' · excluded from hourly test')
            suite.hourly_retry_at[series]=now+900;continue
        result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=series,
            min_close_ts=int(now+60),max_close_ts=int(now+86400),limit=1000,cursor=suite.hourly_pages.get(series,'')))
        suite.hourly_pages[series]=result.get('cursor','')
        listed=[m for m in result.get('markets',[]) if m.get('ticker','').startswith(series+'-') and m.get('status')=='active'
                and ts(m['open_time'])<=now and 60<ts(m['close_time'])-now<=3600]
        scan['listed_markets']+=len(listed)
        scalping=any(b.enabled and b.series==series for folder,(e,f,ps) in suite.portfolios.items()
            if folder in ('volatility_scalper','scalper_fixed','scalper_grid') for b in f.bots.values())
        def liquid_scalp(m):
            if not scalping:return False
            yes=D(str(m.get('yes_bid_dollars') or D(str(m.get('yes_bid') or 0))/100))
            no=D(str(m.get('no_bid_dollars') or D(str(m.get('no_bid') or 0))/100))
            return yes>0 and no>0 and ZERO<=1-yes-no<=D('.10')
        rows=[m for m in listed if m['ticker'] not in markets and suite.candidate_allowed(m['ticker'],now) and (favorite_bid(m) is not None or liquid_scalp(m))]
        scan['eligible_markets']+=len(rows);category['eligible']+=len(rows)
        capacity=suite.search_capacity('hourly',time.time(),staged+1)
        reason=('No active markets closing within one hour' if not listed else
            'Active markets found · no 70–95¢ maker entry' if not rows else
            'Active qualifying markets · feed capacity paused' if not capacity else
            'Active qualifying market · subscribing to order book')
        suite.hourly_coverage[series]=dict(at=time.time(),active_markets=len(listed),eligible_markets=len(rows),reason=reason)
        suite.hourly_retry_at[series]=now+(15 if listed else 60)
        if not listed:
            # Provider listed a future opening or an hourly market whose final
            # hour has not begun: do not poll it again before that known time.
            future=[known_entry_wake(m,'hourly',now) for m in result.get('markets',[])
                    if m.get('status')=='active' and m.get('ticker','').startswith(series+'-')]
            future=[wake for wake in future if wake is not None]
            if future:
                wake=min(future)
                remember(suite,'hourly:'+series,wake,now)
                suite.hourly_retry_at[series]=wake
                suite.hourly_pages[series]=''
                suite.hourly_coverage[series].update(next_check_at=wake,
                    reason='Known next hourly entry window · sleeping until opening')
                scan['reason']='Known future hourly market · sleeping until entry window'
        if not rows:continue
        if not capacity:
            scan['reason']='Active candidates found; admission paused by measured capacity'
            category['capacity_blocked']+=1
            continue
        raw=min(rows,key=lambda m:(ts(m['close_time']),-float(m.get('volume_fp') or m.get('volume') or 0)))
        fee=await host.fee_policy(raw,{})
        if fee.maker_multiplier!=0 or not host.verified_fees.zero_maker_fees_until(
                raw['ticker'],now,ts(raw['close_time'])):
            category['fee_blocked']=category.get('fee_blocked',0)+1
            scan['reason']='Nonzero or unverified maker fee; not admitted'
            continue
        await host.put('hourly_market',dict(market=dict(ticker=raw['ticker'],event_ticker=raw['event_ticker'],series_ticker=series,
            open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,hourly_price=True),
            taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
        staged+=1;active.append(raw['ticker']);scan['subscribed']+=1;category['subscribed']+=1;scan['reason']='Eligible favorites submitted for monitoring'
    suite.hourly_scan=scan
    if now>=getattr(suite,'hourly_scan_log_at',0):
        suite.hourly_scan_log_at=now+30
        print(json.dumps(dict(event='paper_hourly_scan',**scan,real_orders_enabled=False)),flush=True)
    # Parked candidates still need authoritative settlement, independently of
    # whether their order book is currently subscribed.
    for ticker,m in list(suite.settlement_markets().items()):
        if not m.get('hourly_price') or m['close']>now:continue
        raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
        if raw.get('ticker')==ticker and raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
            await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))


async def discover_hourly(host):
    while not host.done.is_set():
        try:await hourly_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:print(json.dumps(dict(event='paper_hourly_retry',error=type(exc).__name__,code=getattr(exc,'code',None),real_orders_enabled=False)),flush=True)
        await asyncio.sleep(5)

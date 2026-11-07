"""Verified hourly-series favorites; bounded fast scans on the shared read budget."""
import asyncio,json,time
from .runner import ts
from .discovery_budget import candidate_markets,next_profile


def favorite_bid(m):
    bids=[float(m.get(k) or 0) for k in ('yes_bid_dollars','no_bid_dollars')]
    if not any(bids):bids=[float(m.get(k) or 0)/100 for k in ('yes_bid','no_bid')]
    return max((b for b in bids if .70<=b<=.95),default=None)


async def hourly_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    if not hasattr(suite,'hourly_metadata'):suite.hourly_metadata={};suite.hourly_retry_at={}
    active=candidate_markets(suite,markets,'hourly',now)
    ps=suite.enabled_profiles('hourly');staged=0
    scan=dict(at=now,checked_series=0,listed_markets=0,eligible_markets=0,subscribed=0,metadata_checks=0,
              reason='No eligible listed favorite')
    # Three profiles per pass rather than one per 15 seconds. Empty/incompatible
    # series back off; stable frequency metadata is cached independently of fees.
    for _ in range(min(3,len(ps))):
        if not suite.search_capacity('hourly',time.time(),staged+1):
            scan['reason']='Admission paused by measured capacity';break
        blocked=active+[p['series']+'-cooldown' for p in ps if suite.hourly_retry_at.get(p['series'],0)>now]
        p,cursor=next_profile(suite,ps,blocked,suite.hourly_cursor)
        if not p:break
        suite.hourly_cursor=cursor;series=p['series'];scan['checked_series']+=1
        metadata=suite.hourly_metadata.get(series)
        if not metadata or now-metadata['at']>=900:
            raw=await asyncio.to_thread(host.verified_data.call,'GET','/series/'+series)
            metadata=dict(at=now,frequency=raw.get('series',{}).get('frequency'))
            suite.hourly_metadata[series]=metadata;scan['metadata_checks']+=1
        if metadata['frequency']!='hourly':
            suite.hourly_retry_at[series]=now+900;continue
        result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=series,
            min_close_ts=int(now+60),max_close_ts=int(now+3600),limit=1000,cursor=suite.hourly_pages.get(series,'')))
        suite.hourly_pages[series]=result.get('cursor','')
        listed=[m for m in result.get('markets',[]) if m.get('ticker','').startswith(series+'-') and m.get('status')=='active'
                and ts(m['open_time'])<=now and 60<ts(m['close_time'])-now<=3600]
        scan['listed_markets']+=len(listed)
        rows=[m for m in listed if m['ticker'] not in markets and suite.candidate_allowed(m['ticker'],now) and favorite_bid(m) is not None]
        scan['eligible_markets']+=len(rows)
        suite.hourly_retry_at[series]=now+(15 if listed else 60)
        if not rows:continue
        raw=min(rows,key=lambda m:(ts(m['close_time']),-float(m.get('volume_fp') or m.get('volume') or 0)))
        fee=await host.fee_policy(raw,{})
        await host.put('hourly_market',dict(market=dict(ticker=raw['ticker'],event_ticker=raw['event_ticker'],series_ticker=series,
            open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,hourly_price=True),
            taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
        staged+=1;active.append(raw['ticker']);scan['subscribed']+=1;scan['reason']='Eligible favorites submitted for monitoring'
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

"""Verified hourly-series favorites; separate from the 15-minute feed."""
import asyncio,json,time
from .runner import ts
from .discovery_budget import candidate_markets,next_profile

async def hourly_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    existing=[t for t,m in markets.items() if m.get('hourly_price')]
    if suite.search_capacity('hourly',now):
        ps=suite.enabled_profiles('hourly')
        active=candidate_markets(suite,markets,'hourly',now)
        p,cursor=next_profile(suite,ps,active,suite.hourly_cursor)
        if p:
            suite.hourly_cursor=cursor;series=p['series']
            # Verify the exchange's declared frequency, never guess from a name.
            metadata=await asyncio.to_thread(host.verified_data.call,'GET','/series/'+series)
            if metadata.get('series',{}).get('frequency')=='hourly':
                result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=series,
                    min_close_ts=int(now+60),max_close_ts=int(now+3600),limit=1000,cursor=suite.hourly_pages.get(series,'')))
                suite.hourly_pages[series]=result.get('cursor','')
                rows=[m for m in result.get('markets',[]) if m.get('ticker','').startswith(series+'-') and m.get('status')=='active'
                      and m['ticker'] not in markets and suite.candidate_allowed(m['ticker'],now) and ts(m['open_time'])<=now and 60<ts(m['close_time'])-now<=3600]
                def rank(m):
                    bids=[float(m.get(k) or 0) for k in ('yes_bid_dollars','no_bid_dollars')]
                    if not any(bids):bids=[float(m.get(k) or 0)/100 for k in ('yes_bid','no_bid')]
                    return (not any(.69<=b<=.95 for b in bids),ts(m['close_time']),-float(m.get('volume_fp') or m.get('volume') or 0))
                if rows:
                    raw=min(rows,key=rank);fee=await host.fee_policy(raw,{})
                    await host.put('hourly_market',dict(market=dict(ticker=raw['ticker'],event_ticker=raw['event_ticker'],series_ticker=series,
                        open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,hourly_price=True),
                        taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
    settlements=suite.settlement_markets()
    for ticker in [t for t,m in settlements.items() if m.get('hourly_price')]:
        if settlements[ticker]['close']>now:continue
        raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
        if raw.get('ticker')==ticker and raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
            await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))

async def discover_hourly(host):
    while not host.done.is_set():
        try:await hourly_once(host)
        except asyncio.CancelledError:raise
        except Exception as exc:print(json.dumps(dict(event='paper_hourly_retry',error=type(exc).__name__,code=getattr(exc,'code',None),real_orders_enabled=False)),flush=True)
        await asyncio.sleep(15)

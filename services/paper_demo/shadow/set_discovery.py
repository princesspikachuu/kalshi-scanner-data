"""Bounded, paginated GET-only discovery over the existing shared feed/read budget."""
import asyncio,time
from .runner import ts

async def discover_sets(host):
    suite=host.experiments
    while not host.done.is_set():
        e,f,ps=suite.portfolios['complete_set'];bot=next(iter(f.bots.values()))
        try:
            now=time.time()
            set_count=sum(not m.get('paid') for m in e.markets.values())
            if bot.enabled and suite.search_capacity('complete_set',now,2):
                result=await asyncio.to_thread(host.verified_data.call,'GET','/events',
                    dict(status='open',with_nested_markets=True,limit=100,min_close_ts=int(now),cursor=suite.scanner_cursor))
                suite.scanner_cursor=result.get('cursor','')
                accepted=0
                for event in result.get('events',[]):
                    if event.get('mutually_exclusive') is not True:continue
                    event_id=event['event_ticker']
                    if event_id in bot.groups:continue
                    markets=[m for m in event.get('markets',[]) if m.get('event_ticker')==event_id and
                        m.get('status')=='active' and ts(m['open_time'])<=now and 30<ts(m['close_time'])-now<=86400]
                    # Distinct NOs in any subset are covered by the same-event
                    # at-most-one-YES guarantee, even if the listing is incomplete.
                    if len(markets)<2:continue
                    markets=sorted(markets,key=lambda m:float(m.get('volume_fp') or m.get('volume') or 0),reverse=True)[:4]
                    if not suite.search_capacity('complete_set',now,len(markets)) or not suite.extra_capacity([m['ticker'] for m in markets],now):continue
                    prepared=[]
                    for m in markets:
                        fee=await host.fee_policy(m,{})
                        prepared.append(dict(market=dict(ticker=m['ticker'],event_ticker=event_id,
                            close=ts(m['close_time']),open=ts(m['open_time']),discovered_at=now,series_ticker=event['series_ticker']),
                            taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
                    await host.put('set_markets',dict(event=dict(event_ticker=event_id,mutually_exclusive=True),markets=prepared))
                    accepted+=1;set_count+=len(markets)
                    if accepted>=2:break
                suite.scanner_state=dict(at=now,state='scanning',events_seen=len(result.get('events',[])),
                    subscribed_markets=len(suite.extra),groups=len(bot.groups),has_more=bool(suite.scanner_cursor))
            # Authoritative settlement recovery for baskets missed by the legacy
            # 15-minute discovery. Never synthesize a payout from last prices.
            due=[t for t,m in e.markets.items() if not m.get('paid') and m['close']<=now]
            for ticker in due[:8]:
                raw=(await asyncio.to_thread(host.verified_data.call,'GET','/markets/'+ticker))['market']
                if raw.get('status') in ('settled','finalized') and raw.get('result') in ('yes','no'):
                    await host.put('experiment_settlement',dict(ticker=ticker,result=raw['result'],status=raw['status']))
        except asyncio.CancelledError:raise
        except Exception as exc:
            suite.scanner_state=dict(at=time.time(),state='retrying',message='Market metadata unavailable; preserving existing positions',error=type(exc).__name__)
        await asyncio.sleep(30)

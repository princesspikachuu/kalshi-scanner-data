"""Verified hourly-series favorites; bounded fast scans on the shared read budget."""
import asyncio,json,math,time
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


def hourly_listing_stages(raw_markets, series, now):
    """Counts provider page appearances, not distinct exchange events.

    Missing/malformed schedule fields must never abort a whole scan page and
    hide a later, independently eligible regular Favorites event.
    """
    if not isinstance(raw_markets, list):
        raw_markets = []
    stages = dict(returned=len(raw_markets), matched=0, active=0,
                  future_open=0, closing_later=0, closing_soon=0,
                  invalid_schedule=0, in_window=0)
    ready = []
    for market in raw_markets:
        if not isinstance(market, dict):
            continue
        ticker = market.get('ticker')
        if not isinstance(ticker, str) or not ticker.startswith(series + '-'):
            continue
        stages['matched'] += 1
        if market.get('status') != 'active':
            continue
        stages['active'] += 1
        try:
            opens = ts(market['open_time'])
            closes = ts(market['close_time'])
            if not (math.isfinite(opens) and math.isfinite(closes)):
                raise ValueError('Nonfinite market schedule')
        except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
            stages['invalid_schedule'] += 1
            continue
        if opens > now:
            stages['future_open'] += 1
        elif closes - now <= 60:
            stages['closing_soon'] += 1
        elif closes - now > 3600:
            stages['closing_later'] += 1
        else:
            ready.append(market)
            stages['in_window'] += 1
    return ready, stages


async def hourly_once(host):
    suite=host.experiments;now=time.time();markets=suite.feed_markets()
    if not hasattr(suite,'hourly_metadata'):suite.hourly_metadata={};suite.hourly_retry_at={}
    if not hasattr(suite,'hourly_coverage'):suite.hourly_coverage={}
    if not isinstance(getattr(suite,'hourly_empty_listing_probe_at',None),dict):suite.hourly_empty_listing_probe_at={}
    # Keep pagination filters stable for each in-memory cursor chain.
    if not isinstance(getattr(suite,'hourly_page_bounds',None),dict):suite.hourly_page_bounds={}
    active=candidate_markets(suite,markets,'hourly',now)
    ps=balanced_hourly_profiles(suite.enabled_profiles('hourly'));staged=0
    scan=dict(at=now,checked_series=0,listed_markets=0,eligible_markets=0,subscribed=0,metadata_checks=0,
              count_basis='scanned_page_appearances_not_unique_events',
              reason='No eligible listed favorite',by_category={})
    if not isinstance(getattr(suite,'hourly_major_crypto_selection_log_at',None),dict):\n        suite.hourly_major_crypto_selection_log_at={}\n    # Read-only visibility into why major hourly crypto series do not reach\n    # the listing comparison. Never modify scheduling or admission decisions.\n    for watched in ('KXBTCD','KXETHD'):\n        if now < suite.hourly_major_crypto_selection_log_at.get(watched,0):\n            continue\n        suite.hourly_major_crypto_selection_log_at[watched]=now+300\n        if not any(p['series']==watched for p in ps):\n            reason='not_enabled'\n        elif any(t.startswith(watched+'-') for t in active):\n            reason='active_subscription'\n        elif suite.hourly_retry_at.get(watched,0)>now:\n            reason='retry_cooldown'\n        elif asleep(suite,'hourly:'+watched,now):\n            reason='scheduled_sleep'\n        else:\n            reason='available_for_selection'\n        print(json.dumps(dict(event='paper_hourly_major_crypto_selection',\n            series=watched,reason=reason,\n            retry_seconds=max(0,round(suite.hourly_retry_at.get(watched,0)-now)),\n            real_orders_enabled=False)),flush=True)\n    # Three profiles per pass rather than one per 15 seconds. Empty/incompatible
    # series back off; stable frequency metadata is cached independently of fees.
    for _ in range(min(3,len(ps))):
        blocked=active+[p['series']+'-cooldown' for p in ps
            if suite.hourly_retry_at.get(p['series'],0)>now or
               asleep(suite,'hourly:'+p['series'],now)]
        p,cursor=next_hourly_profile(ps,blocked,suite.hourly_cursor,active)
        if not p:break
        suite.hourly_cursor=cursor;series=p['series'];scan['checked_series']+=1
        category=scan['by_category'].setdefault(hourly_category(series),
            dict(checked=0,eligible=0,subscribed=0,capacity_blocked=0,
                 returned=0,active=0,in_window=0,future_open=0,
                 closing_later=0,closing_soon=0,invalid_schedule=0,
                 excluded=0,quote_rejected=0,
                 fee_nonzero=0,fee_unverified=0,fee_verified=0))
        category['checked']+=1
        wake=session_wake(series,now)
        if wake is not None:
            suite.hourly_pages.pop(series,None)
            suite.hourly_page_bounds.pop(series,None)
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
            suite.hourly_pages.pop(series,None);suite.hourly_page_bounds.pop(series,None)
            suite.hourly_retry_at[series]=now+900;continue
        page_cursor=suite.hourly_pages.get(series,'')
        bounds=suite.hourly_page_bounds.get(series) if page_cursor else None
        if not isinstance(bounds,tuple) or len(bounds)!=2:
            # Unknown or stale cursor state cannot be resumed safely.
            page_cursor=''
            bounds=(int(now+60),int(now+86400))
        result=await asyncio.to_thread(host.verified_data.call,'GET','/markets',dict(status='open',series_ticker=series,
            min_close_ts=bounds[0],max_close_ts=bounds[1],limit=1000,cursor=page_cursor))
        next_page=result.get('cursor','') or ''
        suite.hourly_pages[series]=next_page
        if next_page:suite.hourly_page_bounds[series]=bounds
        else:suite.hourly_page_bounds.pop(series,None)
        market_rows=result.get('markets') or []
        # Read-only comparison: an empty time-filtered page does not establish
        # that the venue has no open hourly markets. Probe at most once per
        # series per 15 minutes; never admit candidates from this response.
        if (not market_rows and not page_cursor and not next_page
                and hourly_category(series) in ('crypto_or_other','finance')
                and now>=suite.hourly_empty_listing_probe_at.get(series,0)):
            suite.hourly_empty_listing_probe_at[series]=now+900
            try:
                comparison=await asyncio.to_thread(host.verified_data.call,'GET','/markets',
                    dict(status='open',series_ticker=series,limit=100))
                comparison_rows=comparison.get('markets') or []
                matching=[m for m in comparison_rows if isinstance(m,dict)
                    and isinstance(m.get('ticker'),str) and m['ticker'].startswith(series+'-')]
                print(json.dumps(dict(event='paper_hourly_empty_listing_probe',
                    series=series,category=hourly_category(series),filtered_rows=0,unbounded_page_rows=len(comparison_rows),
                    matching_series_rows=len(matching),
                    status_counts={status:sum(m.get('status')==status for m in matching)
                        for status in sorted({str(m.get('status')) for m in matching})},
                    has_next_page=bool(comparison.get('cursor')),
                    real_orders_enabled=False)),flush=True)
            except Exception as exc:
                print(json.dumps(dict(event='paper_hourly_empty_listing_probe_error',
                    series=series,error=type(exc).__name__,real_orders_enabled=False)),flush=True)
        listed,stages=hourly_listing_stages(market_rows,series,now)
        scan['listed_markets']+=len(listed)
        for field in ('returned','active','in_window','future_open','closing_later',
                      'closing_soon','invalid_schedule'):
            category[field]+=stages[field]
        scalping=any(b.enabled and b.series==series for folder,(e,f,ps) in suite.portfolios.items()
            if folder in ('volatility_scalper','scalper_fixed','scalper_grid') for b in f.bots.values())
        def liquid_scalp(m):
            if not scalping:return False
            yes=D(str(m.get('yes_bid_dollars') or D(str(m.get('yes_bid') or 0))/100))
            no=D(str(m.get('no_bid_dollars') or D(str(m.get('no_bid') or 0))/100))
            return yes>0 and no>0 and ZERO<=1-yes-no<=D('.10')
        rows=[];already_monitored=0;candidate_rejected=0;quote_rejected=0
        for market in listed:
            ticker=market['ticker']
            if ticker in markets:
                already_monitored+=1
            elif not suite.candidate_allowed(ticker,now):
                candidate_rejected+=1
            elif favorite_bid(market) is None and not liquid_scalp(market):
                quote_rejected+=1
            else:
                rows.append(market)
        category['excluded']+=already_monitored+candidate_rejected
        category['quote_rejected']+=quote_rejected
        scan['eligible_markets']+=len(rows);category['eligible']+=len(rows)
        capacity=suite.search_capacity('hourly',time.time(),staged+1)
        reason=('Incomplete market listing; next page pending' if next_page and not listed else
            'No active markets closing within one hour' if not listed else
            'Active markets found · no 70–95¢ maker entry' if not rows else
            'Active qualifying markets · feed capacity paused' if not capacity else
            'Active qualifying market · verifying maker fee')
        # The existing per-series diagnostic reads this human-readable reason.
        # Keep it concise; all counts are from this one REST page, not
        # distinct events or a historical opportunity denominator.
        stage_detail=(f" [ret={stages['returned']} active={stages['active']} win={stages['in_window']}"
                      f" ex={already_monitored+candidate_rejected} quote={quote_rejected}"
                      f" badts={stages['invalid_schedule']}]")
        suite.hourly_coverage[series]=dict(at=time.time(),active_markets=len(listed),
            eligible_markets=len(rows),reason=reason+stage_detail)
        suite.hourly_retry_at[series]=now+(15 if listed or next_page else 60)
        if not listed and not page_cursor and not next_page:
            # A future wake is safe only for a COMPLETE, single-page listing.
            # A nonempty cursor means another page may contain an eligible
            # market now. Later pages alone cannot prove the earliest wake.
            # Keep following incomplete listings on the existing read budget.
            future=[known_entry_wake(m,'hourly',now) for m in market_rows
                    if isinstance(m,dict) and m.get('status')=='active'
                    and isinstance(m.get('ticker'),str)
                    and m['ticker'].startswith(series+'-')]
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
        if fee.maker_multiplier!=0:
            category['fee_blocked']=category.get('fee_blocked',0)+1
            category['fee_nonzero']+=1
            suite.hourly_coverage[series]['reason']='Nonzero maker fee; not admitted'+stage_detail
            scan['reason']='Nonzero maker fee; not admitted'
            continue
        if not host.verified_fees.zero_maker_fees_until(raw['ticker'],now,ts(raw['close_time'])):
            category['fee_blocked']=category.get('fee_blocked',0)+1
            category['fee_unverified']+=1
            suite.hourly_coverage[series]['reason']='Maker fee unverified through close; not admitted'+stage_detail
            scan['reason']='Maker fee unverified through close; not admitted'
            continue
        await host.put('hourly_market',dict(market=dict(ticker=raw['ticker'],event_ticker=raw['event_ticker'],series_ticker=series,
            open=ts(raw['open_time']),close=ts(raw['close_time']),discovered_at=now,hourly_price=True),
            taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
        category['fee_verified']+=1
        suite.hourly_coverage[series]['reason']='Eligible favorite submitted for monitoring'+stage_detail
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

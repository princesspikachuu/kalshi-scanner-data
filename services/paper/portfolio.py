"""Chronological historical order simulation. Never sends provider/order requests.

Quotes are minute snapshots; estimated fills assume a share of observed taker
volume, not a known queue position. Saved statistical rankings are in-sample.
"""
from collections import defaultdict,deque
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
import os
import sqlite3
import tempfile
from scripts.execution_model import best_quote, candle_price, cents, timestamp


def proposed_bid(ask, strategy, best_bid=None):
    """Choose price from ask or best bid; preserve old ask-minus-distance bets.

    Positive adjustments to the best bid improve queue priority, but the
    caller must still enforce post-only price strictly below the current ask.
    """
    basis=strategy.get('bid_reference','ask')
    if basis not in ('ask','best_bid'):
        raise ValueError('Unsupported maker bid reference')
    reference=ask if basis=='ask' else best_bid
    if reference is None:
        raise ValueError('Missing displayed best bid')
    offset=strategy.get('bid_adjustment_cents')
    if offset is None:
        if basis!='ask':
            raise ValueError('Best-bid strategy needs an explicit adjustment')
        offset=-strategy['below_ask_cents']
    price=reference+offset
    cap=strategy.get('maximum_bid_cents')
    return min(price,cap) if cap is not None else price


def replay_portfolio(sources, strategies, starting_cash_cents, fill_model='estimated',on_progress=None):
    """Stream historical events into a disk-backed sorted spool.

    The worker has 512 MiB of RAM. Keeping every decoded candle, trade, and
    another heap of the same events in memory causes OOM kills on multi-day
    replays. SQLite stores the event history in a temporary local file; only
    one selected event is decoded at a time during chronological execution.
    """
    with tempfile.TemporaryDirectory(prefix='pocket-paper-events-') as folder:
        with closing(sqlite3.connect(os.path.join(folder,'timeline.db'))) as db:
            db.execute('PRAGMA journal_mode=OFF')
            db.execute('PRAGMA synchronous=OFF')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('PRAGMA cache_size=-1024')
            db.execute('PRAGMA mmap_size=0')
            db.execute('PRAGMA foreign_keys=OFF')
            return _replay_portfolio_from_spool(sources,strategies,starting_cash_cents,
                fill_model=fill_model,on_progress=on_progress,db=db)


def _replay_portfolio_from_spool(sources,strategies,starting_cash_cents,fill_model,on_progress,db):
    db.execute("""CREATE TABLE events (
        serial INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        ts REAL NOT NULL,
        phase INTEGER NOT NULL,
        kind TEXT NOT NULL,
        data TEXT,
        trade_identity TEXT,
        market_rank INTEGER NOT NULL)""")
    db.execute("""CREATE UNIQUE INDEX unique_trade_event
        ON events(ticker,trade_identity) WHERE trade_identity IS NOT NULL""")
    if fill_model not in ('estimated','conservative','all_filled'):raise ValueError('Unknown paper fill model')
    markets={};record_count=0
    notify=on_progress or (lambda activity:None)
    notify(dict(phase='loading saved evidence',records_loaded=0))
    for asset,payload,records in sources:
        cohort={c['ticker']:dict(candidate=c,asset=asset) for c in payload['candidates']}
        for ticker,m in cohort.items():
            if ticker in markets:
                # The newest saved version replaces ALL events for the market,
                # not just some candles or trades.
                db.execute('DELETE FROM events WHERE ticker=?',(ticker,))
                rank=markets[ticker]['rank']
            else:
                rank=len(markets)
            m['rank']=rank
            close=timestamp(m['candidate']['close_time'])
            m['close']=close
            m['event']=m['candidate'].get('event_ticker') or ticker
            markets[ticker]=m
            if close is not None:
                db.execute("""INSERT INTO events(ticker,ts,phase,kind,data,trade_identity,market_rank)
                    VALUES(?, ?, 0, 'close',NULL,NULL,?)""",(ticker,close,rank))
        for row in records:
            record_count+=1
            if record_count%1024==0:
                db.commit()  # Bound SQLite pending write state and rollback memory.
                notify(dict(phase='loading saved evidence',records_loaded=record_count,
                    current_market=row['ticker']))
            if record_count>250000:
                raise ValueError('Replay evidence limit exceeded; select fewer days')
            ticker=row['ticker'];m=cohort.get(ticker)
            if m is None or m['close'] is None:continue
            kind=row['resource'];data=row['record']
            if kind=='candles':
                ts=data.get('end_period_ts')
                if not isinstance(ts,int) or ts>=m['close']:continue
                db.execute("""INSERT INTO events(ticker,ts,phase,kind,data,trade_identity,market_rank)
                    VALUES(?, ?, 2, 'quote',?,NULL,?)""",
                    (ticker,ts,json.dumps(data,separators=(',',':')),m['rank']))
            elif kind=='trades':
                ts=timestamp(data.get('created_time'))
                if ts is None or ts>=m['close']:continue
                identity=data.get('trade_id') or str(sorted(data.items()))
                db.execute("""INSERT OR IGNORE INTO events(ticker,ts,phase,kind,data,trade_identity,market_rank)
                    VALUES(?, ?, 1, 'trade',?,?,?)""",
                    (ticker,ts,json.dumps(data,separators=(',',':')),str(identity),m['rank']))
    db.commit()
    db.execute('CREATE INDEX chronological_events ON events(ts,phase,market_rank,serial)')
    db.commit()
    total_events=db.execute('SELECT count(*) FROM events').fetchone()[0]
    notify(dict(phase='replaying saved markets',records_loaded=record_count,
        markets_loaded=len(markets),events_total=total_events,
        events_processed=0,percent_complete=35))
    free=starting_cash_cents;orders=[];positions=[];attempted=set();events=[];recent=deque(maxlen=20)
    # Only orders/positions for the affected market need visiting on each
    # trade, quote or close. Global portfolio exposure checks are unchanged.
    orders_by_ticker=defaultdict(list);positions_by_ticker=defaultdict(list)
    counters=defaultdict(int);last_quotes={};peak_event=0
    # Audit the exact ask-filtered opportunities separately from actual fills.
    # The research grid's bid-filtered reference ROI is NOT a prediction here.
    diagnostics=[dict(name=s.get('name') or 'Strategy '+str(i+1),asset=s['asset'],
        ask_band_cents=[s['min_price'],s['max_price']],
        bid_reference=s.get('bid_reference','ask'),
        bid_adjustment_cents=(s.get('bid_adjustment_cents')
            if s.get('bid_adjustment_cents') is not None else -s['below_ask_cents']),
        reference_bid_grid_roi_percent=s.get('statistical_yield_percent'),
        qualified_orders=0,qualified_contracts=0,qualified_wins=0,
        qualified_tickers=set(),qualified_events=set(),entry_minutes_weighted=0,
        entry_minutes_distance_weighted=0,
        all_qualified_filled_pnl_cents=0,all_qualified_stake_cents=0,
        same_orders_best_bid_pnl_cents=0,entry_price_premium_cents=0,
        displayed_spread_cents=0,filled_best_bid_pnl_cents=0,
        filled_entry_price_premium_cents=0,
        filled_contracts=0,filled_winners=0,filled_hold_pnl_cents=0,
        filled_stake_cents=0) for i,s in enumerate(strategies)]
    realized_pnl_cents=0
    def activity(ts,ticker=None):
        return dict(phase='replaying saved markets',simulated_time=ts,current_market=ticker,
            events_processed=processed,events_total=total_events,
            percent_complete=(round(35+64*processed/total_events,2) if total_events else 99),
            orders_placed=counters['orders_placed'],filled_contracts=counters['filled_contracts'],
            available_cash_cents=free,recent_activity=list(recent),
            open_orders=[dict(order_id=o['id'],ticker=o['ticker'],side=o['side'],bid_cents=o['bid'],
                contracts=o['quantity'],remaining=o['remaining'],expires=markets[o['ticker']]['close'])
                for o in orders if o['remaining']][-10:])
    def log(kind,ts,**data):
        event=dict(kind=kind,time=ts,**data);recent.append(event)
        if len(events)<1000:events.append(event)
        notify(activity(ts,data.get('ticker')))
    def exposure(event=None):
        return sum(o['remaining']*o['bid'] for o in orders if event is None or o['event']==event)+sum(p['cost'] for p in positions if not p['closed'] and (event is None or p['event']==event))
    def equity():return free+exposure()
    def cancel(order,ts,reason):
        nonlocal free
        if not order['remaining']:return
        free+=order['remaining']*order['bid']
        counters['cancelled_contracts']+=order['remaining'];counters[reason]+=1
        quantity=order['remaining'];order['remaining']=0
        log('cancel',ts,order_id=order['id'],ticker=order['ticker'],side=order['side'],bid_cents=order['bid'],contracts=quantity,reason=reason)
    def sell(p,ts,bid):
        nonlocal free,realized_pnl_cents
        # Observed best bid, with no user-defined minimum price. Unknown depth.
        free+=bid*p['quantity'];p['closed']=True
        realized_pnl_cents+=bid*p['quantity']-p['cost']
        counters['loss_prevention_sales']+=1
        log('loss_prevention_sale',ts,ticker=p['ticker'],contracts=p['quantity'],sale_cents=bid,
            profit_loss_cents=bid*p['quantity']-p['cost'],evidence='minute best-bid estimate; depth unknown')
    processed=0
    for ts,phase,rank,serial,kind,ticker,packed in db.execute(
        'SELECT ts,phase,market_rank,serial,kind,ticker,data FROM events ORDER BY ts,phase,market_rank,serial'):
        data=ticker if kind=='close' else (ticker,json.loads(packed))
        processed+=1
        if processed%1024==0:notify(activity(ts))
        if kind=='close':
            ticker=data
            for o in orders_by_ticker[ticker]:
                cancel(o,ts,'expired_orders')
            for p in positions_by_ticker[ticker]:
                if not p['closed']:
                    payment=100*p['quantity'] if markets[ticker]['candidate']['result']==p['side'] else 0
                    free+=payment;p['closed']=True
                    realized_pnl_cents+=payment-p['cost']
                    log('settlement',ts,ticker=ticker,contracts=p['quantity'],profit_loss_cents=payment-p['cost'])
        elif kind=='quote':
            ticker,bar=data;m=markets[ticker];last_quotes[ticker]=(ts,bar)
            for p in positions_by_ticker[ticker]:
                if fill_model=='all_filled' or p['closed'] or p['stop'] is None:continue
                bid=cents(candle_price(bar,p['side'],'bid'))
                if bid is None and p['side']=='no':
                    ask=cents(candle_price(bar,'yes','ask'));bid=None if ask is None else 100-ask
                if bid is not None and bid<=p['stop']:sell(p,ts,bid)
            quote=best_quote(bar)
            if quote is None:continue
            side,best_bid,ask=quote;remaining=(m['close']-ts)/60
            eligible=[]
            for index,s in enumerate(strategies):
                compatible=s['asset']==m['asset'] or (s['asset']=='btc' and m['candidate'].get('series')=='KXBTC15M') or (s['asset']=='eth' and m['candidate'].get('series')=='KXETH15M') or (s['asset']=='crypto' and m['candidate'].get('series') in {'KXBTC15M','KXETH15M','KXSOL15M','KXXRP15M','KXDOGE15M','KXBNB15M','KXHYPE15M','KXZEC15M','KXNEAR15M'})
                identity=(ticker,index)
                if not compatible or identity in attempted:continue
                if s['entry_minute_min']<remaining<=s['entry_minute_max'] and s['min_price']<=ask<=s['max_price']:
                    eligible.append((index,s,identity))
            for index,s,identity in sorted(eligible,key=lambda item:-item[1]['statistical_yield_percent']):
                bid=proposed_bid(ask,s,best_bid=best_bid)
                if not 1<=bid<ask:continue
                # Reclaim only unfilled lower-yield orders, never sell positions
                # solely because a different category becomes eligible.
                cost=bid;bankroll=equity()
                desired=min(s['contracts']*cost,int(bankroll*s['balance_percent']/100),int(bankroll*.10))
                for o in sorted(orders,key=lambda order:order['yield']):
                    shortage=free<desired or (o['event']==m['event'] and int(bankroll*.10)-exposure(m['event'])<desired)
                    if shortage and o['remaining'] and o['yield']<s['statistical_yield_percent']:cancel(o,ts,'priority_cancellations')
                bankroll=equity()
                cap=max(0,int(bankroll*.10)-exposure(m['event']))
                budget=min(free,cap,int(bankroll*s['balance_percent']/100))
                quantity=min(s['contracts'],budget//cost)
                if quantity<1:
                    counters['funding_or_event_cap_skips']+=1
                    continue
                attempted.add(identity);free-=quantity*cost
                order=dict(id='paper-'+str(counters['orders_placed']+1),quantity=quantity,ticker=ticker,event=m['event'],side=side,bid=bid,remaining=quantity,
                    created=ts,yield_=s['statistical_yield_percent'],stop=s.get('loss_trigger_cents'),strategy=index,
                    displayed_best_bid=best_bid,displayed_ask=ask)
                order['yield']=order.pop('yield_');orders.append(order);orders_by_ticker[ticker].append(order);counters['orders_placed']+=1
                matched=diagnostics[index];matched['qualified_orders']+=1
                matched['qualified_contracts']+=quantity
                matched['qualified_tickers'].add(ticker)
                matched['qualified_events'].add(m['event'])
                matched['entry_minutes_weighted']+=remaining*quantity
                target=(s['entry_minute_min']+s['entry_minute_max'])/2
                matched['entry_minutes_distance_weighted']+=abs(remaining-target)*quantity
                won=m['candidate']['result']==side
                matched['qualified_wins']+=int(won)*quantity
                matched['all_qualified_stake_cents']+=quantity*bid
                matched['all_qualified_filled_pnl_cents']+=(100*int(won)-bid)*quantity
                matched['same_orders_best_bid_pnl_cents']+=(100*int(won)-best_bid)*quantity
                matched['entry_price_premium_cents']+=(bid-best_bid)*quantity
                matched['displayed_spread_cents']+=(ask-best_bid)*quantity
                if fill_model=='all_filled':
                    filled=order['remaining'];order['remaining']=0
                    position=dict(ticker=ticker,event=order['event'],side=side,
                        quantity=filled,cost=bid*filled,stop=None,closed=False)
                    positions.append(position);positions_by_ticker[ticker].append(position)
                    counters['filled_contracts']+=filled;counters['simulated_fills']+=1
                    matched['filled_contracts']+=filled
                    matched['filled_winners']+=int(won)*filled
                    matched['filled_stake_cents']+=position['cost']
                    matched['filled_hold_pnl_cents']+=(100*int(won)-bid)*filled
                    matched['filled_best_bid_pnl_cents']+=(100*int(won)-best_bid)*filled
                    matched['filled_entry_price_premium_cents']+=(bid-best_bid)*filled
                    log('fill',ts,order_id=order['id'],ticker=ticker,side=side,
                        remaining=0,contracts=filled,bid_cents=bid,
                        evidence='assumed immediate fill; no execution evidence')
                peak_event=max(peak_event,exposure(m['event'])/bankroll*100)
                log('bid',ts,order_id=order['id'],ticker=ticker,event=m['event'],side=side,bid_cents=bid,contracts=quantity,
                    expires=m['close'],statistical_yield_percent=order['yield'],
                    bid_reference=s.get('bid_reference','ask'),best_bid_cents=best_bid,ask_cents=ask)
        elif kind=='trade':
            if fill_model=='all_filled':continue
            ticker,t=data
            if t.get('is_block_trade') is True or t.get('taker_outcome_side') not in ('yes','no'):continue
            try:volume=Decimal(str(t.get('count_fp') or '0'))
            except InvalidOperation:continue
            if not volume.is_finite() or volume<=0:continue
            available=int(volume)
            # One shared volume budget per trade. Multiple bids cannot each
            # claim the same execution volume.
            for o in sorted((o for o in orders_by_ticker[ticker] if o['remaining']),key=lambda o:(-o['bid'],-o['yield'],o['created'])):
                if ts<o['created']+2 or t['taker_outcome_side']==o['side']:continue
                price=cents(t.get(o['side']+'_price_dollars'))
                if price is None or price>o['bid'] or (fill_model=='conservative' and price==o['bid']):continue
                quantity=min(o['remaining'],available)
                if quantity<1:continue
                available-=quantity;o['remaining']-=quantity
                p=dict(ticker=ticker,event=o['event'],side=o['side'],quantity=quantity,cost=o['bid']*quantity,stop=o['stop'],closed=False)
                positions.append(p);positions_by_ticker[ticker].append(p);counters['filled_contracts']+=quantity;counters['simulated_fills']+=1
                matched=diagnostics[o['strategy']];won=markets[ticker]['candidate']['result']==o['side']
                matched['filled_contracts']+=quantity;matched['filled_winners']+=int(won)*quantity
                matched['filled_stake_cents']+=p['cost']
                matched['filled_hold_pnl_cents']+=(100*int(won)*quantity-p['cost'])
                matched['filled_best_bid_pnl_cents']+=(100*int(won)-o['displayed_best_bid'])*quantity
                matched['filled_entry_price_premium_cents']+=(o['bid']-o['displayed_best_bid'])*quantity
                log('fill',ts,order_id=o['id'],ticker=ticker,side=o['side'],remaining=o['remaining'],contracts=quantity,bid_cents=o['bid'],evidence='trade-through proxy' if price<o['bid'] else 'at-price volume estimate')
                saved=last_quotes.get(ticker)
                if saved and 0<=ts-saved[0]<=60 and p['stop'] is not None:
                    bid=cents(candle_price(saved[1],p['side'],'bid'))
                    if bid is not None and bid<=p['stop']:sell(p,ts,bid)
    unresolved=counters['expired_orders']
    # Every market close has been processed. Verify that canceled bid reserves
    # were refunded and realized P/L exactly matches the final cash movement.
    if any(o['remaining'] for o in orders) or any(not p['closed'] for p in positions):
        raise ValueError('Portfolio closeout incomplete')
    if free-starting_cash_cents!=realized_pnl_cents:
        raise ValueError('Portfolio P/L does not reconcile with cash')
    for s in diagnostics:
        # A conditional win rate must not be compared to an unconditional grid
        # win rate. These numbers refer to the SAME bid placement cohort.
        qualified=s['qualified_contracts'];filled=s['filled_contracts']
        s['qualified_win_rate_percent']=(round(100*s['qualified_wins']/qualified,4) if qualified else None)
        s['filled_win_rate_percent']=(round(100*s['filled_winners']/filled,4) if filled else None)
        s['qualified_all_fill_roi_percent']=(round(100*s['all_qualified_filled_pnl_cents']/s['all_qualified_stake_cents'],4)
            if s['all_qualified_stake_cents'] else None)
        s['filled_hold_roi_percent']=(round(100*s['filled_hold_pnl_cents']/s['filled_stake_cents'],4)
            if s['filled_stake_cents'] else None)
        # For $1 binary settlement, mean entry price in cents is precisely
        # the required win rate percentage for break-even before fees.
        s['filled_break_even_win_rate_percent']=(round(s['filled_stake_cents']/filled,4) if filled else None)
        s['qualified_break_even_win_rate_percent']=(round(s['all_qualified_stake_cents']/qualified,4)
            if qualified else None)
        s['fill_rate_percent']=(round(100*filled/qualified,4) if qualified else None)
        s['distinct_markets']=len(s.pop('qualified_tickers'))
        s['distinct_events']=len(s.pop('qualified_events'))
        s['average_entry_minutes_before_close']=(round(s.pop('entry_minutes_weighted')/qualified,3) if qualified else None)
        s['average_distance_from_window_midpoint_minutes']=(round(s.pop('entry_minutes_distance_weighted')/qualified,3) if qualified else None)
        s['avg_displayed_spread_cents']=(round(s['displayed_spread_cents']/qualified,4) if qualified else None)
        s['avg_entry_premium_over_best_bid_cents']=(round(s['entry_price_premium_cents']/qualified,4)
            if qualified else None)
        s['avg_filled_entry_premium_cents']=(round(s['filled_entry_price_premium_cents']/filled,4)
            if filled else None)
        # This is a same-opportunity price comparison, NOT a claim that the
        # lower resting bid would have filled the same contracts.
        if s['same_orders_best_bid_pnl_cents']-s['all_qualified_filled_pnl_cents']!=s['entry_price_premium_cents']:
            raise ValueError('Paper matched-price opportunity P/L does not reconcile')
        if s['filled_best_bid_pnl_cents']-s['filled_hold_pnl_cents']!=s['filled_entry_price_premium_cents']:
            raise ValueError('Paper matched-price fill P/L does not reconcile')
    audit=dict(basis='Ask-price and entry-window-qualified paper orders; not the bid-based research grid.',
        qualified_orders=sum(x['qualified_orders'] for x in diagnostics),
        qualified_contracts=sum(x['qualified_contracts'] for x in diagnostics),
        all_qualified_filled_pnl_cents=sum(x['all_qualified_filled_pnl_cents'] for x in diagnostics),
        same_orders_best_bid_pnl_cents=sum(x['same_orders_best_bid_pnl_cents'] for x in diagnostics),
        entry_price_premium_cents=sum(x['entry_price_premium_cents'] for x in diagnostics),
        filled_entry_price_premium_cents=sum(x['filled_entry_price_premium_cents'] for x in diagnostics),
        filled_contracts=sum(x['filled_contracts'] for x in diagnostics),
        cancelled_unfilled_contracts=counters['cancelled_contracts'],
        fill_rate_percent=(round(100*sum(x['filled_contracts'] for x in diagnostics)/
            sum(x['qualified_contracts'] for x in diagnostics),4)
            if sum(x['qualified_contracts'] for x in diagnostics) else None),
        filled_winners=sum(x['filled_winners'] for x in diagnostics),
        filled_hold_pnl_cents=sum(x['filled_hold_pnl_cents'] for x in diagnostics),
        loss_prevention_delta_cents=realized_pnl_cents-sum(x['filled_hold_pnl_cents'] for x in diagnostics),
        reconciled_realized_pnl_cents=realized_pnl_cents,
        strategies=diagnostics)
    return dict(reconciliation=audit,mode='historical portfolio replay',fill_model=('Assume all qualifying orders fill immediately; hold to settlement' if fill_model=='all_filled' else ('Conservative trade-through' if fill_model=='conservative' else 'Estimated: qualifying trade volume, including at-price trades; queue position unknown')),
        starting_cash_cents=starting_cash_cents,ending_cash_cents=free,profit_loss_cents=free-starting_cash_cents,
        simulated_fills=counters['simulated_fills'],filled_contracts=counters['filled_contracts'],orders_placed=counters['orders_placed'],
        expired_orders=counters['expired_orders'],priority_cancellations=counters['priority_cancellations'],
        loss_prevention_sales=counters['loss_prevention_sales'],funding_or_event_cap_skips=counters['funding_or_event_cap_skips'],
        peak_event_exposure_percent=round(peak_event,4),no_fill_evidence=counters['expired_orders'],
        assumptions='All-filled mode is hypothetical and ignores early-sale triggers. Before fees: no entry or exit fees deducted. Actual market-specific maker fees and taker fees may apply. Snapshot sale prices assume depth; actual fills and intraminute stops are unknown. Rankings use selected saved statistics, not out-of-sample predictions.',
        recent_activity=list(recent),order_preview=events[:12],trades=events,total_trades=len(events),trades_truncated=len(events)>=1000)

"""Chronological historical order simulation. Never sends provider/order requests.

Quotes are minute snapshots; estimated fills assume a share of observed taker
volume, not a known queue position. Saved statistical rankings are in-sample.
"""
from collections import defaultdict,deque
from decimal import Decimal, InvalidOperation
import heapq
from scripts.execution_model import best_quote, candle_price, cents, timestamp


def proposed_bid(ask, strategy):
    price=ask-strategy['below_ask_cents']
    cap=strategy.get('maximum_bid_cents')
    return min(price,cap) if cap is not None else price


def replay_portfolio(sources, strategies, starting_cash_cents, fill_model='estimated',on_progress=None):
    markets={};record_count=0
    notify=on_progress or (lambda activity:None)
    notify(dict(phase='loading saved evidence',records_loaded=0))
    for asset,payload,records in sources:
        cohort={c['ticker']:dict(candidate=c,asset=asset,bars=[],trades=[]) for c in payload['candidates']}
        for row in records:
            record_count+=1
            if record_count%1024==0:notify(dict(phase='loading saved evidence',records_loaded=record_count,current_market=row['ticker']))
            if record_count>250000:raise ValueError('Replay evidence limit exceeded; select fewer days')
            if row['ticker'] in cohort and row['resource'] in ('candles','trades'):
                cohort[row['ticker']]['bars' if row['resource']=='candles' else 'trades'].append(row['record'])
        # Sources arrive oldest first. Never pool duplicate historical versions.
        markets.update(cohort)
    timeline=[];serial=0
    def emit(ts,phase,kind,data):
        nonlocal serial
        serial+=1;heapq.heappush(timeline,(ts,phase,serial,kind,data))
    for ticker,m in markets.items():
        close=timestamp(m['candidate']['close_time']);m['close']=close
        m['event']=m['candidate'].get('event_ticker') or ticker
        if close is None:continue
        for bar in m['bars']:
            ts=bar.get('end_period_ts')
            if isinstance(ts,int) and ts<close:emit(ts,2,'quote',(ticker,bar))
        seen=set()
        for t in m['trades']:
            ts=timestamp(t.get('created_time'))
            identity=t.get('trade_id') or str(sorted(t.items()))
            if ts is not None and ts<close and identity not in seen:
                seen.add(identity);emit(ts,1,'trade',(ticker,t))
        emit(close,0,'close',ticker)
    free=starting_cash_cents;orders=[];positions=[];attempted=set();events=[];recent=deque(maxlen=20)
    # Only orders/positions for the affected market need visiting on each
    # trade, quote or close. Global portfolio exposure checks are unchanged.
    orders_by_ticker=defaultdict(list);positions_by_ticker=defaultdict(list)
    counters=defaultdict(int);last_quotes={};peak_event=0
    # Audit the exact ask-filtered opportunities separately from actual fills.
    # The research grid's bid-filtered reference ROI is NOT a prediction here.
    diagnostics=[dict(name=s.get('name') or 'Strategy '+str(i+1),asset=s['asset'],
        ask_band_cents=[s['min_price'],s['max_price']],
        reference_bid_grid_roi_percent=s.get('statistical_yield_percent'),
        qualified_orders=0,qualified_contracts=0,qualified_wins=0,
        all_qualified_filled_pnl_cents=0,all_qualified_stake_cents=0,
        filled_contracts=0,filled_winners=0,filled_hold_pnl_cents=0,
        filled_stake_cents=0) for i,s in enumerate(strategies)]
    realized_pnl_cents=0
    def activity(ts,ticker=None):
        return dict(phase='replaying saved markets',simulated_time=ts,current_market=ticker,
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
    notify(dict(phase='replaying saved markets',records_loaded=record_count,markets_loaded=len(markets)))
    processed=0
    while timeline:
        ts,phase,_,kind,data=heapq.heappop(timeline)
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
                if p['closed'] or p['stop'] is None:continue
                bid=cents(candle_price(bar,p['side'],'bid'))
                if bid is None and p['side']=='no':
                    ask=cents(candle_price(bar,'yes','ask'));bid=None if ask is None else 100-ask
                if bid is not None and bid<=p['stop']:sell(p,ts,bid)
            quote=best_quote(bar)
            if quote is None:continue
            side,_,ask=quote;remaining=(m['close']-ts)/60
            eligible=[]
            for index,s in enumerate(strategies):
                compatible=s['asset']==m['asset'] or (s['asset']=='btc' and m['candidate'].get('series')=='KXBTC15M') or (s['asset']=='eth' and m['candidate'].get('series')=='KXETH15M') or (s['asset']=='crypto' and m['candidate'].get('series') in {'KXBTC15M','KXETH15M','KXSOL15M','KXXRP15M','KXDOGE15M','KXBNB15M','KXHYPE15M','KXZEC15M','KXNEAR15M'})
                identity=(ticker,index)
                if not compatible or identity in attempted:continue
                if s['entry_minute_min']<remaining<=s['entry_minute_max'] and s['min_price']<=ask<=s['max_price']:
                    eligible.append((index,s,identity))
            for index,s,identity in sorted(eligible,key=lambda item:-item[1]['statistical_yield_percent']):
                bid=proposed_bid(ask,s)
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
                    created=ts,yield_=s['statistical_yield_percent'],stop=s.get('loss_trigger_cents'),strategy=index)
                order['yield']=order.pop('yield_');orders.append(order);orders_by_ticker[ticker].append(order);counters['orders_placed']+=1
                matched=diagnostics[index];matched['qualified_orders']+=1
                matched['qualified_contracts']+=quantity
                won=m['candidate']['result']==side
                matched['qualified_wins']+=int(won)*quantity
                matched['all_qualified_stake_cents']+=quantity*bid
                matched['all_qualified_filled_pnl_cents']+=(100*int(won)-bid)*quantity
                peak_event=max(peak_event,exposure(m['event'])/bankroll*100)
                log('bid',ts,order_id=order['id'],ticker=ticker,event=m['event'],side=side,bid_cents=bid,contracts=quantity,
                    expires=m['close'],statistical_yield_percent=order['yield'])
        elif kind=='trade':
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
    audit=dict(basis='Ask-price and entry-window-qualified paper orders; not the bid-based research grid.',
        qualified_orders=sum(x['qualified_orders'] for x in diagnostics),
        qualified_contracts=sum(x['qualified_contracts'] for x in diagnostics),
        all_qualified_filled_pnl_cents=sum(x['all_qualified_filled_pnl_cents'] for x in diagnostics),
        filled_contracts=sum(x['filled_contracts'] for x in diagnostics),
        filled_winners=sum(x['filled_winners'] for x in diagnostics),
        filled_hold_pnl_cents=sum(x['filled_hold_pnl_cents'] for x in diagnostics),
        loss_prevention_delta_cents=realized_pnl_cents-sum(x['filled_hold_pnl_cents'] for x in diagnostics),
        reconciled_realized_pnl_cents=realized_pnl_cents,
        strategies=diagnostics)
    return dict(reconciliation=audit,mode='historical portfolio replay',fill_model=('Conservative trade-through' if fill_model=='conservative' else 'Estimated: qualifying trade volume, including at-price trades; queue position unknown'),
        starting_cash_cents=starting_cash_cents,ending_cash_cents=free,profit_loss_cents=free-starting_cash_cents,
        simulated_fills=counters['simulated_fills'],filled_contracts=counters['filled_contracts'],orders_placed=counters['orders_placed'],
        expired_orders=counters['expired_orders'],priority_cancellations=counters['priority_cancellations'],
        loss_prevention_sales=counters['loss_prevention_sales'],funding_or_event_cap_skips=counters['funding_or_event_cap_skips'],
        peak_event_exposure_percent=round(peak_event,4),no_fill_evidence=counters['expired_orders'],
        assumptions='Before fees: no entry or exit fees deducted. Actual market-specific maker fees and taker fees may apply. Snapshot sale prices assume depth; actual fills and intraminute stops are unknown. Rankings use selected saved statistics, not out-of-sample predictions.',
        recent_activity=list(recent),order_preview=events[:12],trades=events,total_trades=len(events),trades_truncated=len(events)>=1000)

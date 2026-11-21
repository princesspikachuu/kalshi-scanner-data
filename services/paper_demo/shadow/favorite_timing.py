"""Actual-fill cohorts: series, side, paid price and remaining event time.

Cash results include every tracked fill; forecast calibration requires a fresh
entry observation and authoritative outcome. Partial fills are not independent
events. Earlier observations are never relabeled with later submission metadata.
"""
from decimal import Decimal as D
from .observation_returns import merge, summarize
from .weather_window import is_daily,observation_end

BANDS=((180,'<3m'),(300,'3–5m'),(600,'5–10m'),(900,'10–15m'),(1800,'15–30m'),(3600,'30–60m'),(7200,'1–2h'))
METRICS='timing-metrics|'

def horizon(seconds):return next((label for upper,label in BANDS if seconds<upper),'>=2h')
def clock(m,now):
    if is_daily(m):return max(0,observation_end(m)-now),'weather_local_day_end'
    if m.get('sports') and m.get('sports_expected_end') is not None:
        return max(0,m['sports_expected_end']-now),'estimated_game_end'
    return max(0,m['close']-now),'market_close'
def market_type(profile,m):
    return 'sports' if m.get('sports') else m.get('weather_category') or (profile.get('asset') if profile.get('asset') in ('weather','weather_daily') else None) or ('hourly_price' if m.get('hourly_price') or profile.get('asset')=='hourly' else '15m_price')
def cell(cells,key,metadata=None):
    return cells.setdefault(METRICS+key,dict(metadata or {},contracts='0',cost='0',closed='0',closed_cost='0',
        net='0',dollar_hours='0',holding_seconds='0',resolved='0',winners='0',profitable_closed='0',profit_classified_closed='0',unverified='0'))
def add(row,field,value):row[field]=str(D(row.get(field,'0'))+value)

def fill(strategy,order,quantity,entry_key):
    a=strategy.attempts.get(order.ticker)
    if not a:return
    e=strategy.e;m=e.markets[order.ticker]
    recent=getattr(e,'_recent_fills',{}).get(order.id,[])
    price=D(recent[-1]['price']) if recent else order.price
    fee=e.fees[order.ticker].charge(quantity,price,order.maker)
    if order.action=='buy':
        if 'entry_fills' not in a:
            a['entry_fills']=[]
            a['timing_legacy_quantity']=str(max(D(0),sum((l.quantity for l in e.wallet.lots if l.ticker==order.ticker),D(0))-quantity))
        remaining,basis=clock(m,e.now)
        key=('paper-data-v3|' if a.get('entry_mode')=='paper_exploration' else '')+entry_key(strategy.series,order.side,price,remaining,basis)
        verified=e.book_fresh(order.ticker)
        cost=quantity*price+fee
        row=cell(strategy.exit_evidence.cells,key,dict(key=key,series=strategy.series,market_type=market_type(strategy.profile,m),
            side=order.side,price=str(price),horizon=horizon(remaining),clock=basis))
        add(row,'contracts',quantity);add(row,'cost',cost)
        row['time_min']=min(row.get('time_min',int(remaining)),int(remaining))
        row['time_max']=max(row.get('time_max',int(remaining)),int(remaining))
        if not verified:add(row,'unverified',quantity)
        if order.execution_model=='worker-delay-v1':
            add(row,'latency_observed_contracts',quantity)
            add(row,'worker_delay_seconds',quantity*D(str(order.worker_delay_seconds)))
        previous=a['entry_fills'][-1] if a['entry_fills'] else None
        if (previous and previous['key']==key and previous['verified']==verified and previous['remaining']==previous['quantity']
                and previous['at']==e.now and previous.get('order_id')==order.id and D(previous['cost'])*quantity==cost*D(previous['quantity'])):
            old_q=D(previous['quantity']);old_cost=D(previous['cost'])
            previous['at']=float((D(str(previous['at']))*old_q+D(str(e.now))*quantity)/(old_q+quantity))
            previous['cost_at']=float((D(str(previous.get('cost_at',previous['at'])))*old_cost+D(str(e.now))*cost)/(old_cost+cost))
            previous.update(quantity=str(old_q+quantity),remaining=str(old_q+quantity),cost=str(old_cost+cost),remaining_cost=str(old_cost+cost))
            return
        a['entry_fills'].append(dict(key=key,at=e.now,cost_at=e.now,price=str(price),quantity=str(quantity),remaining=str(quantity),
            cost=str(cost),remaining_cost=str(cost),return_net='0',return_closed='0',seconds_to_market_close=max(0,m['close']-e.now),
            seconds_to_event_end=remaining,clock=basis,verified=verified,order_id=order.id,
            execution_model=order.execution_model,worker_delay_seconds=order.worker_delay_seconds,
            decision_at=order.decision_at,arrival_at=order.arrives))
        e.log('FAVORITE_ENTRY_COHORT',order,quantity=quantity,price=price,fee=fee,
            details=__import__('json').dumps(a['entry_fills'][-1]))
    elif a.get('entry_fills'):
        legacy=min(quantity,D(a.get('timing_legacy_quantity','0')))
        a['timing_legacy_quantity']=str(D(a.get('timing_legacy_quantity','0'))-legacy)
        close(strategy,a,quantity-legacy,price,fee*(quantity-legacy)/quantity,e.now)

def close(strategy,a,quantity,price,fee,now):
    left=quantity
    for chunk in a.get('entry_fills',[]):
        available=D(chunk['remaining']);take=min(left,available)
        if not take:continue
        cost=D(chunk['remaining_cost'])*take/available
        row=cell(strategy.exit_evidence.cells,chunk['key'])
        add(row,'closed',take);add(row,'closed_cost',cost)
        net=take*price-fee*take/quantity-cost
        add(row,'net',net)
        # Older partly closed chunks lack the necessary exit attribution.
        # Only complete tracked histories can contribute to average event ROI.
        if 'return_net' in chunk or available==D(chunk['quantity']):
            chunk['return_net']=str(D(chunk.get('return_net','0'))+net)
            chunk['return_closed']=str(D(chunk.get('return_closed','0'))+take)
        # Count realized profitable closures, not the eventual contract outcome.
        # Each fill cohort carries its exact entry cost including fees; a
        # partial exit is classified only after its exit fee is allocated.
        add(row,'profit_classified_closed',take)
        if net>0:add(row,'profitable_closed',take)
        elapsed=D(str(max(0,now-chunk['at'])))
        add(row,'holding_seconds',take*elapsed);add(row,'dollar_hours',cost*D(str(max(0,now-chunk.get('cost_at',chunk['at']))))/3600)
        chunk['remaining']=str(available-take);chunk['remaining_cost']=str(D(chunk['remaining_cost'])-cost)
        left-=take
        if not left:break

def settle(strategy,ticker,observe):
    a=strategy.attempts[ticker];m=strategy.e.markets[ticker]
    if a.get('timing_finalized') or m.get('yes_payout_confirmed') not in ('0','1'):return
    payout=int(m['yes_payout_confirmed']==('1' if a['side']=='yes' else '0'))
    quantity=sum((D(c['remaining']) for c in a.get('entry_fills',[])),D(0))
    if quantity:close(strategy,a,quantity,D(payout),D(0),strategy.e.now)
    for chunk in a.get('entry_fills',[]):
        row=cell(strategy.exit_evidence.cells,chunk['key']);q=D(chunk['quantity'])
        add(row,'resolved',q);add(row,'winners',q*payout)
        if not strategy.trial_valid(ticker,a):add(row,'execution_unverified_contracts',q)
        if chunk['verified']:observe(strategy.exit_evidence.cells,chunk['key'],m.get('event_ticker',ticker),payout,observed_at=strategy.e.now)
    grouped={}
    for chunk in a.get('entry_fills',[]):
        grouped.setdefault(chunk['key'],[]).append(chunk)
    for key,chunks in grouped.items():
        if not all(c['verified'] for c in chunks):continue
        if not strategy.hold_only and not all(D(c.get('return_closed','0'))==D(c['quantity']) for c in chunks):continue
        returns=cell(strategy.exit_evidence.cells,key).setdefault('hold_return_events' if strategy.hold_only else 'return_events',{})
        merge(returns,{m.get('event_ticker',ticker):dict(
            cost=str(sum((D(c['cost']) for c in chunks),D(0))),
            net=str(sum((D(c['quantity'])*payout-D(c['cost']) if strategy.hold_only else D(c['return_net']) for c in chunks),D(0))))})
        while len(returns)>500:returns.pop(next(iter(returns)))
        if strategy.hold_only:
            wide=cell(strategy.exit_evidence.cells,key).setdefault('wide_events',{})
            event=m.get('event_ticker',ticker);records=wide.setdefault(event,[])
            for chunk in chunks:
                seconds=int(chunk.get('seconds_to_event_end',chunk.get('seconds_to_market_close',0)))
                existing=next((record for record in records if record[0]==seconds),None)
                if existing:
                    existing[1]=str(D(existing[1])+D(chunk['quantity']));existing[2]=str(D(existing[2])+D(chunk['cost']))
                    existing[3]=str(D(existing[3])+D(chunk['quantity'])*payout-D(chunk['cost']))
                else:records.append([seconds,chunk['quantity'],chunk['cost'],str(D(chunk['quantity'])*payout-D(chunk['cost']))])
            while len(wide)>500:wide.pop(next(iter(wide)))
    a['timing_finalized']=True

def rows(cells,hold_only=False):
    result=[]
    for key,row in cells.items():
        if not key.startswith(METRICS):continue
        events=cells.get(row['key'],{}).get('events',{})
        closed=D(row['closed']);hours=D(row['dollar_hours']);qty=D(row['contracts'])
        measured=D(row.get('latency_observed_contracts','0'))
        attributed=row.get('hold_return_events' if hold_only else 'return_events',{})
        # Research treats known outcomes as held to settlement. Account cash and
        # the realized ledger above retain the actual exits. Historic aggregate
        # rows lack per-event sizing: flag the equal-size reconstruction instead
        # of presenting its fee allocation as exact.
        if hold_only and events and qty>0 and D(row.get('unverified','0'))==0:
            attributed=dict(attributed)
            cost=D(row.get('cost','0'))
            complete=qty==D(row.get('resolved','0'))
            for event,payout in events.items():
                if event in attributed:continue
                if len(events)==1 and complete and cost>0:
                    attributed[event]=dict(cost=str(cost),net=str(D(row.get('winners','0'))-cost))
                elif cost>0:
                    unit=cost/qty
                    attributed[event]=dict(cost=str(unit),net=str(D(payout)-unit),estimated=True)
        transport={k:v for k,v in row.items() if k not in ('return_events','hold_return_events')}
        result.append(dict(transport,outcome_events=events,return_events=attributed,return_policy='hold_only' if hold_only else 'all_executions',**summarize(attributed),average_worker_delay_ms=str(1000*D(row.get('worker_delay_seconds','0'))/measured) if measured else None,events=len(events),event_win_rate=100*sum(events.values())/len(events) if events else None,
            break_even=str(100*D(row['cost'])/qty) if qty else None,
            average_holding_minutes=str(D(row['holding_seconds'])/closed/60) if closed else None,
            net_per_dollar_hour=str(D(row['net'])/hours) if hours else None,
            open_contracts=str(qty-closed)))
    order={label:i for i,(_,label) in enumerate(BANDS)}
    return sorted(result,key=lambda r:(r['series'],D(r['price']),order.get(r['horizon'],len(BANDS)),r['side']))

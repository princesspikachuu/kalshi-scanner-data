"""Causal Maker ranking and short-lived, read-only admission hypotheses."""
import math,statistics
from copy import deepcopy
from decimal import Decimal as D
from .execution import tick_size
from .runner import ts

def turnover_score(prints,now,bids,profiles,fee,market):
    times=sorted(ts(p['created_time']) for p in prints)
    hour=sum(at>=now-3600 for at in times);six=sum(at>=now-21600 for at in times)
    sizes=[float(p.get('count_fp',1)) for p in prints]
    typical=max(1,statistics.median(q for q in sizes if math.isfinite(q) and q>0)) if any(math.isfinite(q) and q>0 for q in sizes) else 1
    # Recency dominates because fill opportunity is perishable. Six-hour and
    # daily rates smooth a quiet minute/hour, but cannot make stale historical
    # volume look like current turnover. A capped response remains a lower bound.
    six_rate=six/6;day_rate=len(times)/24
    flow=.60*hour+.30*six_rate+.10*day_rate
    best=None
    for p in profiles:
        c=p.get('config',{});q=D(p['contracts'])
        for side in ('yes','no'):
            bid=D(str(bids[side]));ask=1-D(str(bids['no' if side=='yes' else 'yes']))
            if not c.get('min_price',.2)<=float(bid)<=c.get('max_price',.8) or float(ask-bid)+1e-9<c.get('min_spread',.03):continue
            tick=tick_size(market,bid);buy=min(ask-tick,bid+tick);sell=max(buy+tick,ask-tick)
            if buy<=0 or buy>=ask or sell>=1:continue
            entry_fee=fee.charge(q,buy,True);exit_fee=fee.charge(q,sell,True)
            net=(sell-buy)*q-entry_fee-exit_fee
            if net<=D(str(c.get('min_net',.005))):continue
            capital=buy*q+entry_fee
            trips_per_day=min(1440,24*flow/(2*max(1,float(q)/typical)))
            hold=86400/max(.001,trips_per_day)
            score=float(net/capital)*trips_per_day
            row=dict(execution_score=score,expected_net_per_round=str(net),expected_capital=str(capital),
                expected_hold_seconds=hold,trades_last_hour=hour,trades_last_six_hours=six,
                recent_flow_per_hour=flow,observed_trades=len(times),sample_capped=len(times)>=100,
                ranking_basis='recency-weighted observed trade flow and fee-adjusted spread; uncalibrated ranking only',
                ranking_side=side,ranking_profile=p['id'])
            if best is None or score>best['execution_score']:best=row
    return best

def ranked_rows(state):
    def rank(item):
        _,r=item;good=r.get('reason') in ('awaiting_shared_admission','cached_admission_retry','admitted_to_shared_monitoring','maker_replacement_cancel_pending','reallocation_slot_ready','verified_waiting_for_capacity')
        return (0 if good else 1 if not r.get('inspected_at') else 2,-r.get('execution_score',r['score']))
    return [dict(ticker=t,category=r['category'],score=r.get('execution_score',r['score']),
        score_basis='verified turnover estimate' if 'execution_score' in r else 'discovery prior',
        trades_24h=r.get('trades_24h'),trades_last_hour=r.get('trades_last_hour'),
        recent_flow_per_hour=r.get('recent_flow_per_hour'),expected_net_per_round=r.get('expected_net_per_round'),
        expected_hold_seconds=r.get('expected_hold_seconds'),
        reason=r.get('reason','awaiting trade-frequency verification'))
        for t,r in sorted(state.get('candidates',{}).items(),key=rank)[:20]]

async def retry_verified(host,state,now):
    rows=state.get('candidates',{});ready=[];choices=None
    for ticker,row in rows.items():
        cached=row.get('ready')
        if not cached:continue
        if not 0<=now-cached['verified_at']<=120:
            row.pop('ready');row.update(reason='verified_candidate_expired',retry_at=now)
            state['cached_admission_expired']=state.get('cached_admission_expired',0)+1;continue
        if ticker in host.experiments.feed_markets():row.pop('ready');continue
        if choices is None:choices=host.experiments.enabled_profiles('market_maker')
        if not any(p['market_category']==row['category'] and ticker not in p.get('paused_markets',[]) for p in choices):
            row.pop('ready');row['reason']='strategy_paused';continue
        if now>=cached['next_try']:ready.append((ticker,row,cached))
    if not ready or now<state.get('next_cached_try',0):return False
    ticker,row,cached=max(ready,key=lambda item:item[1].get('execution_score',item[1]['score']))
    if not host.experiments.search_capacity('market_maker',now) and host.experiments.can_replace_maker_market(cached['payload'],now) is not True:return False
    cached['next_try']=now+5;row['reason']='cached_admission_retry'
    state['next_cached_try']=now+5
    state['cached_admission_retries']=state.get('cached_admission_retries',0)+1
    state['state']='Cached verified candidate awaiting shared admission'
    await host.put('maker_market',deepcopy(cached['payload']))
    return True

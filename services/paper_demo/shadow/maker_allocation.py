"""Replace only inactive, unfilled Maker probes; wait for real simulated cancellation acknowledgments."""
import json,math
from .market_maker import MM_FOLDERS
from .monitoring import protected

def credited_capacity(suite,ticker,now):
    credit=suite.maker_allocation['credits'].get(ticker)
    if credit is None or credit<now:return False
    s=suite.monitoring_snapshot(now)
    return (s['admitting'] and s['subscribed_markets']+1<=s['total'] and
        s['entry_markets']+1<=s['entry_candidates'] and s['categories']['market_maker']+1<=8+4*s['level'])

def replacement(suite,market,now):
    state=suite.maker_allocation;ranking=market.get('maker_ranking',{});score=ranking.get('execution_score',0)
    if not math.isfinite(score) or score<=0 or ranking.get('trades_last_hour',0)<6:return None
    if not 0<=now-market.get('discovered_at',0)<=120 or not 0<=now-market.get('maker_last_trade_at',0)<=300:return None
    if now<state['next_at'] or not suite.monitoring_snapshot(now)['admitting'] or not suite.candidate_allowed(market['ticker'],now):return None
    choices=[]
    for ticker,m in suite.feed_markets().items():
        if not m.get('market_maker') or ticker==market['ticker'] or ticker in state['pending'] or now-m.get('discovered_at',now)<300:continue
        if ticker in suite.host.engine.markets and suite.host.engine.markets[ticker]['close']>now:continue
        if protected(suite,ticker,now):continue
        # A shared market owned by another strategy is never reclaimed here.
        if any(ticker in e.markets and not e.markets[ticker].get('entry_parked') for folder,(e,_,_) in suite.portfolios.items() if folder not in MM_FOLDERS):continue
        engines=[e for folder,(e,_,_) in suite.portfolios.items() if folder in MM_FOLDERS and ticker in e.markets]
        trades=[t[0] for e in engines for t in e.tape.markets.get(ticker,{}).get('trades',())]
        if any(at>=now-300 for at in trades):continue
        last=max(m.get('discovered_at',0),m.get('maker_last_trade_at',0),max(trades,default=0))
        old=m.get('maker_ranking',{}).get('execution_score',0)*(.5**min(20,max(0,now-last)/300))
        if score>max(.001,old*2):choices.append((old,ticker))
    return min(choices)[1] if choices else None

def begin(suite,market,now):
    ticker=replacement(suite,market,now)
    if ticker is None:return False
    target=market['ticker'];state=suite.maker_allocation
    state['pending'][ticker]=dict(target=target,requested_at=now);state['next_at']=now+30
    for folder,(e,_,_) in suite.portfolios.items():
        if folder not in MM_FOLDERS or ticker not in e.markets:continue
        e.advance(now);e.markets[ticker]['maker_replacement_pending']=True
        for order in list(e.orders.values()):
            if order.ticker==ticker and order.action=='buy' and order.status in ('pending','resting'):e.cancel(order.id)
        e.log('MAKER_REALLOCATION_REQUESTED',ticker=ticker,reason='better_verified_recent_trade_flow',
            details=json.dumps(dict(target=target,new_score=market['maker_ranking']['execution_score'])))
    return True

def finalize(suite,now):
    state=suite.maker_allocation
    state['credits']={t:at for t,at in state['credits'].items() if at>=now}
    for ticker,pending in list(state['pending'].items()):
        engines=[(e,f) for folder,(e,f,_) in suite.portfolios.items() if folder in MM_FOLDERS and ticker in e.markets]
        if protected(suite,ticker,now):
            for e,_ in engines:e.markets[ticker].pop('maker_replacement_pending',None)
            state['pending'].pop(ticker);state['aborted']=state.get('aborted',0)+1
            continue
        if any(o.ticker==ticker and o.status in ('pending','resting') for e,_ in engines for o in e.orders.values()):continue
        for e,f in engines:
            f.step(ticker)  # Record the terminal cancellation, with new entries still blocked.
            e.markets[ticker].pop('maker_replacement_pending',None)
        m=suite.feed_markets().get(ticker)
        if m:suite.park_candidate(ticker,m,now)
        state['credits'][pending['target']]=now+120
        row=getattr(suite,'maker_discovery',{}).get('candidates',{}).get(pending['target'])
        if row is not None:row.update(reason='reallocation_slot_ready',retry_at=now)
        state['pending'].pop(ticker);state['completed']=state.get('completed',0)+1
        for e,_ in engines:e.log('MAKER_REALLOCATION_ACK',ticker=ticker,reason='cancellation_acknowledged_slot_released',details=json.dumps(pending))

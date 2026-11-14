"""Fill-conditioned calibration and maker quotes for paper data collection.

Paper exploration uses configured sizes and competitive maker bids. It is never
represented as an established advantage. Evidence is bucketed by series, side,
price and time; correlated thresholds from one event count only once per cell.
"""
import math
from decimal import Decimal as D, ROUND_FLOOR
from .favorite_timing import horizon,clock

TICK = D('.01')


def entry_key(series, side, bid, remaining, basis='market_close'):
    return f'entry-v2|{series}|{side}|{int(bid*100)}|{horizon(remaining)}|{basis}'


def observe(cells, key, event, payout, observed_at=None):
    cell = cells.setdefault(key, {})
    outcomes = cell.setdefault('events', {})
    if event in outcomes:
        # Different thresholds in one event can disagree. Retain the adverse
        # result rather than letting several correlated wins inflate evidence.
        outcomes[event] = min(outcomes[event], int(payout))
        return
    outcomes[event] = int(payout)
    # Old outcomes keep their original count, but cannot be assigned a made-up
    # timestamp. Only newly confirmed, timestamped outcomes enter rolling rates.
    if observed_at is not None:
        cell.setdefault('event_times', {})[event] = float(observed_at)
    # Keep event identities and timestamp metadata bounded together.
    while len(outcomes) > 500:
        oldest = next(iter(outcomes))
        outcomes.pop(oldest)
        cell.get('event_times', {}).pop(oldest, None)


def estimate(cells, key):
    outcomes = cells.get(key, {}).get('events', {})
    n = len(outcomes)
    if n < 30:
        return dict(samples=n, mean=None, lower=None)
    mean = sum(outcomes.values()) / n
    z = 1.96
    lower = (mean + z*z/(2*n) - z*math.sqrt(mean*(1-mean)/n + z*z/(4*n*n))) / (1+z*z/n)
    return dict(samples=n, mean=mean, lower=lower)


def quote(engine, profile, contracts, ticker, side, cells, max_price=None):
    book = engine.books[ticker]
    bid, ask = book.bid(side), book.ask(side)
    if bid is None or ask is None or bid >= ask:
        return None
    exploration = profile.get('paper_exploration', True) is not False
    remaining,basis=clock(engine.markets[ticker],engine.now)
    candidate=min(bid+TICK,ask-TICK,D('.95'))
    key = ('paper-data-v3|' if exploration else '')+entry_key(profile['series'],side,candidate,remaining,basis)
    value = estimate(cells, key)
    buffer = max(TICK, D(str(profile.get('entry_edge_buffer', '.02'))))
    ceiling = D('.95')
    if max_price is not None:
        ceiling = min(ceiling, D(max_price))
    if exploration:
        # Collect execution/outcome data, including weak or unknown estimates.
        # A post-only bid improves the public bid by one tick when spread permits.
        price = min(bid+TICK, ask-TICK, ceiling)
        quantity = contracts
        mode = 'paper_exploration'
    else:
        price=min(bid+TICK,ask-TICK,ceiling).quantize(TICK,rounding=ROUND_FLOOR)
        while price>=D('.70'):
            key=entry_key(profile['series'],side,price,remaining,basis);value=estimate(cells,key)
            if value['lower'] is not None and price+engine.fees[ticker].charge(contracts,price,True)/contracts+buffer<=D(str(value['lower'])):break
            price-=TICK
        if price<D('.70'):return None
        quantity=contracts
        mode='calibrated_maker'
    price = price.quantize(TICK, rounding=ROUND_FLOOR)
    if not D('.70') <= price <= D('.95'):
        return None
    available = engine.available()+sum((o.reserved for o in engine.orders.values()
        if o.ticker==ticker and o.action=='buy' and o.status in ('pending','resting')),D(0))
    budget = available if exploration else available*D('.05')
    quantity = min(quantity, (budget/price).to_integral_value(rounding=ROUND_FLOOR))
    if quantity < 1:
        return None
    fee = engine.fees[ticker].charge(quantity, price, True)
    # Walk price down for the actual series fee, including rounding.
    if not exploration:
        if price+fee/quantity+buffer > D(str(value['lower'])):
            return None
    if quantity*price+fee > available:
        quantity=min(quantity,(available/(price+fee/quantity)).to_integral_value(rounding=ROUND_FLOOR))
        if quantity<1:return None
        fee=engine.fees[ticker].charge(quantity,price,True)
        if quantity*price+fee>available:return None
    if not exploration and price+fee/quantity+buffer>D(str(value['lower'])):return None
    if exploration:
        key='paper-data-v3|'+entry_key(profile['series'],side,price,remaining,basis);value=estimate(cells,key)
    return dict(price=price, quantity=quantity, fee=fee, mode=mode,
                estimate=value, key=key, ceiling=str(ceiling),policy='favorites-paper-data-v3' if exploration else 'favorites-value-v2')

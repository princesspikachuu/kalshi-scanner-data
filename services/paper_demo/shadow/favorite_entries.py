"""Fill-conditioned calibration and maker quotes for paper data collection.

Paper exploration uses configured sizes and competitive maker bids. It is never
represented as an established advantage. Evidence is bucketed by series, side,
price and time; correlated thresholds from one event count only once per cell.
"""
import math
from decimal import Decimal as D, ROUND_FLOOR

TICK = D('.01')


def entry_key(series, side, bid, remaining):
    horizon = 'under5' if remaining < 300 else 'under15' if remaining < 900 else 'under60' if remaining < 3600 else 'daily'
    return f'entry|{series}|{side}|{int(bid * 20)}|{horizon}'


def observe(cells, key, event, payout):
    cell = cells.setdefault(key, {})
    outcomes = cell.setdefault('events', {})
    if event in outcomes:
        # Different thresholds in one event can disagree. Retain the adverse
        # result rather than letting several correlated wins inflate evidence.
        outcomes[event] = min(outcomes[event], int(payout))
        return
    outcomes[event] = int(payout)
    # Bounded recent sample rather than unbounded event identities/checkpoints.
    while len(outcomes) > 500:
        outcomes.pop(next(iter(outcomes)))


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
    key = ('paper-data-v3|' if exploration else '')+entry_key(profile['series'], side, bid, engine.markets[ticker]['close']-engine.now)
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
        if value['lower'] is None:return None
        ceiling = min(ceiling, D(str(value['lower']))-buffer)
        price = min(bid+TICK, ask-TICK, ceiling)
        quantity = contracts
        mode = 'calibrated_maker'
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
        while price >= D('.70') and price+fee/quantity+buffer > D(str(value['lower'])):
            price -= TICK
            fee = engine.fees[ticker].charge(quantity, price, True)
        if price < D('.70'):
            return None
    if quantity*price+fee > available:
        quantity=min(quantity,(available/(price+fee/quantity)).to_integral_value(rounding=ROUND_FLOOR))
        if quantity<1:return None
        fee=engine.fees[ticker].charge(quantity,price,True)
        if quantity*price+fee>available:return None
    return dict(price=price, quantity=quantity, fee=fee, mode=mode,
                estimate=value, key=key, ceiling=str(ceiling),policy='favorites-paper-data-v3' if exploration else 'favorites-value-v2')

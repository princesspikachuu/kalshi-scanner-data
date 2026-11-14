"""Decimal fee and liquidity rules shared by the persistent simulator and tests."""
from decimal import Decimal,ROUND_CEILING,InvalidOperation
D=Decimal
QUANTUM=D('.0001') # Dollars: one centicent, current exchange rounding quantum.

def decimal(value):
    n=D(str(value))
    if not n.is_finite():raise ValueError('Nonfinite amount')
    return n

def charge(price,quantity,kind,multiplier,maker=True):
    p,q,m=map(decimal,(price,quantity,multiplier))
    if not 0<p<1 or q<=0 or m<0 or m>100:raise ValueError('Invalid execution fee inputs')
    if kind not in ('quadratic','quadratic_with_maker_fees'):raise ValueError('Unsupported fee schedule')
    rate=D('.0175') if maker and kind=='quadratic_with_maker_fees' else D(0) if maker else D('.07')
    cost=p*q;raw=rate*m*q*p*(1-p)
    # The published rounding applies to fee + position cost, not each contract.
    fee=(cost+raw).quantize(QUANTUM,rounding=ROUND_CEILING)-cost
    return cost,fee

def book_levels(book,side,kind):
    if side not in ('yes','no') or kind not in ('entry','exit'):raise ValueError('Invalid order side')
    if kind=='entry':return sorted(((1-p,n) for p,n in book['no' if side=='yes' else 'yes'].items()),key=lambda x:x[0])
    return sorted(book[side].items(),reverse=True)

def sweep(book,side,kind,limit,quantity):
    """Immediate execution walks actual opposing depth, bounded by limit/size.

    Maker bots never use this path: crossing maker orders are rejected instead.
    Caller owns a shadow book and must debit returned depth before another sweep.
    """
    remaining=decimal(quantity);fills=[];limit=decimal(limit)
    for price,size in book_levels(book,side,kind):
        if (kind=='entry' and price>limit) or (kind=='exit' and price<limit):break
        n=min(remaining,size)
        if n>0:fills.append((price,n));remaining-=n
        if not remaining:break
    return fills,remaining

def queue_ahead(book,side,kind,price):
    price=decimal(price)
    levels=book[side].items() if kind=='entry' else ((1-p,n) for p,n in book['no' if side=='yes' else 'yes'].items())
    return sum((n for p,n in levels if p>=price),D(0)) if kind=='entry' else sum((n for p,n in levels if p<=price),D(0))

def eligible_trade(order,trade,now):
    """No old/late/block/unknown-aggressor prints, and no quote-only fills."""
    try:
        ts=decimal(trade['ts_ms'])/1000 if trade.get('ts_ms') is not None else decimal(trade['ts'])
        side=trade.get('taker_outcome_side',trade.get('taker_side'))
        if trade.get('is_block_trade') or side not in ('yes','no'):return None
        if not decimal(order['active_at'])<ts<decimal(order['expires']) or not decimal(now)-2<=ts<=decimal(now)+D('.5'):return None
        if order.get('cancel_at') is not None and ts>=decimal(order['cancel_at']):return None
        if (order['kind']=='entry' and side==order['side']) or (order['kind']=='exit' and side!=order['side']):return None
        p=decimal(trade[order['side']+'_price_dollars']);n=decimal(trade['count_fp']);limit=decimal(order['price_dollars'])
        if not 0<p<1 or not 0<n<=100000000 or n!=n.quantize(D('.01')):return None
        if (order['kind']=='entry' and p>limit) or (order['kind']=='exit' and p<limit):return None
        return n
    except (KeyError,ValueError,TypeError,InvalidOperation):return None

"""Bounded series-fair market selection; held exposure always comes first."""
from services.research.reports import SERIES

def family(series):
    for asset in ('sports','weather','weather_daily','commodities_15m','finance_15m'):
        if series in SERIES[asset]:return asset
    return 'crypto'

def select_markets(quotes,pinned,now,limit=100,cycle_series=()):
    """Round robin per *individual* series, never by broad asset family.

    One copper or Brent listing must not occupy dozens of slots while other
    individual 15-minute bots get no live books. Pinned markets containing
    owned orders take priority over every other subscription.
    """
    cycle_series=set(cycle_series)
    chosen={t:q for t,q in sorted(quotes.items()) if t in pinned}
    if len(chosen)>limit:raise ValueError('Held market capacity exceeded')
    buckets={}
    for ticker,q in quotes.items():
        end=q.get('entry_close',q['close'])
        if ticker not in chosen and q.get('status')=='active' and now<end<=now+86400:
            buckets.setdefault(q['series'],[]).append((ticker,q))
    for series,items in buckets.items():
        if series in cycle_series:
            # A newly opened 15-minute contract is more useful than a distant
            # historical listing. Prefer newest open, then imminent close.
            items.sort(key=lambda p:(-p[1].get('open',0),p[1].get('entry_close',p[1]['close']),p[0]))
        else:items.sort(key=lambda p:(p[1].get('entry_close',p[1]['close']),p[0]))
    counts={series:sum(q['series']==series for q in chosen.values()) for series in buckets}
    while len(chosen)<limit and buckets:
        series=min(buckets,key=lambda s:(counts[s],s not in cycle_series,family(s)!='sports',s))
        ticker,q=buckets[series].pop(0);chosen[ticker]=q;counts[series]+=1
        if not buckets[series]:del buckets[series]
    return chosen

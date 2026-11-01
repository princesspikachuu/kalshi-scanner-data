"""Bounded category-fair market selection; held exposure always comes first."""
from services.research.reports import SERIES

def family(series):
    for asset in ('sports','weather','weather_daily'):
        if series in SERIES[asset]:return asset
    return 'crypto'

def select_markets(quotes,pinned,now,limit=100):
    chosen={t:q for t,q in sorted(quotes.items()) if t in pinned}
    if len(chosen)>limit:raise ValueError('Held market capacity exceeded')
    buckets={}
    for ticker,q in quotes.items():
        end=q.get('entry_close',q['close'])
        if ticker not in chosen and q.get('status')=='active' and now<end<=now+86400:
            buckets.setdefault(family(q['series']),[]).append((ticker,q))
    for items in buckets.values():items.sort(key=lambda p:(p[1].get('entry_close',p[1]['close']),p[0]))
    counts={asset:sum(family(q['series'])==asset for q in chosen.values()) for asset in buckets}
    while len(chosen)<limit and buckets:
        asset=min(buckets,key=lambda a:(counts[a],a!='sports',a))
        ticker,q=buckets[asset].pop(0);chosen[ticker]=q;counts[asset]+=1
        if not buckets[asset]:del buckets[asset]
    return chosen

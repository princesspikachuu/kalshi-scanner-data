"""Transparent, hierarchical statistics for the Statistics-Backed Favorites paper strategy."""
import json,math
from decimal import Decimal as D, ROUND_FLOOR
from .favorite_entries import entry_key
from .favorite_timing import METRICS,clock,horizon,market_type

TICK=D('.01')

def price_bucket(price):
    cents=int(D(price)*100)
    lo=70 if cents<75 else 75 if cents<80 else 80 if cents<85 else 85 if cents<90 else 90
    hi=74 if lo<90 else 95
    if lo in (75,80,85):hi=lo+4
    return f'{lo}-{hi}'

def _wilson(wins,n,z=1.96):
    if not n:return None
    p=wins/n;den=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/den

def _merge_event(target,event,value):
    target[event]=min(target.get(event,1),int(value))

def aggregate(cells):
    groups={}
    for k,row in cells.items():
        if not k.startswith(METRICS) or not row.get('key'):continue
        events=cells.get(row['key'],{}).get('events',{})
        dims=dict(series=row.get('series'),market_type=row.get('market_type'),side=row.get('side'),
                  price_bucket=price_bucket(row.get('price','0')),horizon=row.get('horizon'))
        levels=[
            ('exact',(dims['series'],dims['market_type'],dims['side'],dims['price_bucket'],dims['horizon'])),
            ('market_type_price_time_side',(dims['market_type'],dims['side'],dims['price_bucket'],dims['horizon'])),
            ('market_type_price_time',(dims['market_type'],dims['price_bucket'],dims['horizon'])),
            ('market_type_price',(dims['market_type'],dims['price_bucket'])),
            ('price',(dims['price_bucket'],)),
            ('global',()),
        ]
        for level,key in levels:
            g=groups.setdefault((level,key),dict(level=level,key=key,events={},contracts=D(0),cost=D(0),net=D(0)))
            for event,value in events.items():_merge_event(g['events'],event,value)
            g['contracts']+=D(row.get('closed','0'));g['cost']+=D(row.get('closed_cost','0'));g['net']+=D(row.get('net','0'))
    return groups

def summarize(group):
    events=group['events'];n=len(events);wins=sum(events.values());mean=wins/n if n else None
    return dict(level=group['level'],group=list(group['key']),samples=n,win_rate=mean,
                lower=_wilson(wins,n),realized_net=str(group['net']),
                realized_roi=float(group['net']/group['cost']) if group['cost'] else None)

def select(cells,profile,m,side,price,remaining,min_samples=20):
    groups=aggregate(cells);mt=market_type(profile,m);pb=price_bucket(price);hz=horizon(remaining)
    candidates=[
        ('exact',(profile['series'],mt,side,pb,hz)),
        ('market_type_price_time_side',(mt,side,pb,hz)),
        ('market_type_price_time',(mt,pb,hz)),
        ('market_type_price',(mt,pb)),
        ('price',(pb,)),
        ('global',()),
    ]
    best=None
    for level,key in candidates:
        s=summarize(groups.get((level,key),dict(level=level,key=key,events={},contracts=D(0),cost=D(0),net=D(0))))
        if best is None or s['samples']>best['samples']:best=s
        if s['samples']>=int(min_samples):return dict(s,reason='sample_threshold_met')
    return dict(best or {},level=(best or {}).get('level','global'),samples=(best or {}).get('samples',0),
                reason='insufficient_samples')

def statistics_quote(engine,profile,contracts,ticker,side,cells,max_price=None):
    book=engine.books[ticker];bid,ask=book.bid(side),book.ask(side)
    if bid is None or ask is None or bid>=ask:return None,dict(reason='no_valid_maker_spread',samples=0,level=None)
    ceiling=min(D('.95'),D(max_price) if max_price is not None else D('.95'))
    price=min(bid+TICK,ask-TICK,ceiling).quantize(TICK,rounding=ROUND_FLOOR)
    if not D('.70')<=price<=D('.95'):return None,dict(reason='outside_favorite_price_range',samples=0,level=None)
    available=engine.available()+sum((o.reserved for o in engine.orders.values() if o.ticker==ticker and o.action=='buy' and o.status in ('pending','resting')),D(0))
    budget=min(available,available*D(str(profile.get('statistics_max_capital_fraction','.05'))))
    quantity=min(contracts,(budget/price).to_integral_value(rounding=ROUND_FLOOR))
    if quantity<1:return None,dict(reason='risk_or_capital_limit',samples=0,level=None)
    fee=engine.fees[ticker].charge(quantity,price,True)
    while quantity>0 and quantity*price+fee>available:
        quantity-=1;fee=engine.fees[ticker].charge(quantity,price,True) if quantity else D(0)
    if quantity<1:return None,dict(reason='risk_or_capital_limit',samples=0,level=None)
    remaining,basis=clock(engine.markets[ticker],engine.now)
    evidence=select(cells,profile,engine.markets[ticker],side,price,remaining,profile.get('statistics_min_samples',20))
    all_in=price+fee/quantity+D(str(profile.get('statistics_slippage_buffer','.005')))
    min_edge=D(str(profile.get('statistics_min_probability_edge','.01')))
    min_roi=D(str(profile.get('statistics_min_expected_roi','.01')))
    mean=D(str(evidence['win_rate'])) if evidence.get('win_rate') is not None else None
    lower=D(str(evidence['lower'])) if evidence.get('lower') is not None else None
    expected_ev=(mean-all_in) if mean is not None else None
    expected_roi=(expected_ev/all_in) if expected_ev is not None and all_in else None
    decision=dict(evidence,price=str(price),quantity=str(quantity),fee=str(fee),all_in_probability=str(all_in),
                  required_probability=str(all_in+min_edge),expected_value=str(expected_ev) if expected_ev is not None else None,
                  expected_roi=str(expected_roi) if expected_roi is not None else None,
                  min_expected_roi=str(min_roi),basis=basis,horizon=horizon(remaining))
    if evidence.get('reason')!='sample_threshold_met':
        return None,decision
    if lower is None or lower<=all_in+min_edge:
        return None,dict(decision,reason='confidence_lower_bound_below_threshold')
    if expected_roi is None or expected_roi<min_roi:
        return None,dict(decision,reason='expected_roi_below_threshold')
    key=entry_key(profile['series'],side,price,remaining,basis)
    return dict(price=price,quantity=quantity,fee=fee,mode='statistics_backed',estimate=decision,key=key,
                ceiling=str(ceiling),policy='favorites-statistics-v1'),dict(decision,reason='trade')

def leaderboard(cells,min_samples=1,limit=10):
    result=[summarize(g) for g in aggregate(cells).values() if g['level'] in ('exact','market_type_price_time_side')]
    result=[r for r in result if r['samples']>=min_samples]
    result.sort(key=lambda r:((r['realized_roi'] if r['realized_roi'] is not None else -999),r['samples']),reverse=True)
    return result[:limit]

class StatisticsFavoritesMixin:
    def set_statistics_source(self,source):self.statistics_source=source
    def _source_cells(self):return self.statistics_source() if getattr(self,'statistics_source',None) else {}
    def statistics_snapshot(self):
        return dict(min_samples=int(self.profile.get('statistics_min_samples',20)),
                    best_segments=leaderboard(self._source_cells(),1,10),
                    latest_decisions=list(self.decisions.values())[-20:])

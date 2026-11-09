"""Transparent, hierarchical statistics for the Statistics-Backed Favorites paper strategy."""
import math
from decimal import Decimal as D, ROUND_FLOOR
from .favorite_entries import entry_key
from .favorite_timing import METRICS,clock,horizon,market_type

TICK=D('.01')

def price_bucket(price):
    cents=int(D(price)*100)
    lo=70 if cents<75 else 75 if cents<80 else 80 if cents<85 else 85 if cents<90 else 90 if cents<95 else 95
    hi=min(lo+4,95)
    return f'{lo}-{hi}'

def _wilson(wins,n,z=1.96):
    if not n:return None
    p=wins/n;den=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/den

PRICE_BUCKETS=tuple(f'{lo}-{min(lo+4,95)}' for lo in (70,75,80,85,90,95))
TIME_BUCKETS=('<3m','3–5m','5–10m','10–15m','15–30m','30–60m','1–2h','>=2h')

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

def select_groups(groups,profile,m,side,price,remaining,min_samples=20):
    mt=market_type(profile,m);pb=price_bucket(price);hz=horizon(remaining)
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

def select(cells,profile,m,side,price,remaining,min_samples=20):
    return select_groups(aggregate(cells),profile,m,side,price,remaining,min_samples)

def statistics_quote(engine,profile,contracts,ticker,side,cells,max_price=None,groups=None):
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
    evidence=select_groups(groups if groups is not None else aggregate(cells),profile,engine.markets[ticker],side,price,remaining,profile.get('statistics_min_samples',20))
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

def leaderboard_groups(groups,min_samples=1,limit=10):
    result=[summarize(g) for g in groups.values() if g['level'] in ('exact','market_type_price_time_side')]
    result=[r for r in result if r['samples']>=min_samples]
    result.sort(key=lambda r:((r['realized_roi'] if r['realized_roi'] is not None else -999),r['samples']),reverse=True)
    return result[:limit]

def leaderboard(cells,min_samples=1,limit=10):
    return leaderboard_groups(aggregate(cells),min_samples,limit)

def statistics_matrix(groups,profile):
    """Per-market-type 5-cent price x unchanged time grid.

    Exact cells never inherit samples from broad parent groups. A separate
    fallback field exposes when a live decision would use pooled evidence.
    Eligibility here is evidence-only; live fees, depth, cash, and risk can
    still reject an order.
    """
    minimum=int(profile.get('statistics_min_samples',20))
    edge=D(str(profile.get('statistics_min_probability_edge','.01')))
    slippage=D(str(profile.get('statistics_slippage_buffer','.005')))
    min_roi=D(str(profile.get('statistics_min_expected_roi','.01')))
    market_types=sorted({key[1][0] for key in groups if key[0]=='market_type_price_time' and key[1][0]})
    result=[]
    for kind in market_types:
        cells=[]
        for bucket in PRICE_BUCKETS:
            price_hi=D(bucket.split('-')[1])/100
            for time in TIME_BUCKETS:
                key=('market_type_price_time',(kind,bucket,time))
                row=summarize(groups.get(key,dict(level='market_type_price_time',key=key[1],events={},contracts=D(0),cost=D(0),net=D(0))))
                # Look up the model's fallback level for the same group.
                def lookup():
                    for level,parent in (('market_type_price',(kind,bucket)),('price',(bucket,)),('global',())):
                        g=groups.get((level,parent))
                        if g is not None and len(g['events'])>=minimum:return level,len(g['events'])
                    return 'insufficient_samples',0
                fallback,pooled_n=lookup() if row['samples']<minimum else ('market_type_price_time',row['samples'])
                lower=D(str(row['lower'])) if row['lower'] is not None else None
                # No fee schedule is assumed in the matrix. This upper-bound
                # test is necessary, not sufficient, for live order eligibility.
                capable=row['samples']>=minimum and lower is not None and lower>price_hi+slippage+edge
                capable=capable and row['win_rate'] is not None and (
                    D(str(row['win_rate']))-price_hi-slippage)/(price_hi+slippage)>=min_roi
                cells.append(dict(price_bucket=bucket,horizon=time,**row,
                    eligibility='evidence_candidate' if capable else 'insufficient_samples' if row['samples']<minimum else 'evidence_rejected',
                    fallback_level=fallback,fallback_samples=pooled_n))
        result.append(dict(market_type=kind,price_buckets=list(PRICE_BUCKETS),time_buckets=list(TIME_BUCKETS),cells=cells))
    return result

class StatisticsFavoritesMixin:
    def set_statistics_source(self,source):self.statistics_source=source
    def _source_cells(self):return self.statistics_source() if getattr(self,'statistics_source',None) else {}
    def statistics_groups(self):
        now=self.e.now
        refresh=float(self.profile.get('statistics_refresh_seconds',30))
        if getattr(self,'_statistics_groups',None) is None or now-getattr(self,'_statistics_groups_at',-1e9)>=refresh:
            self._statistics_groups=aggregate(self._source_cells());self._statistics_groups_at=now
        return self._statistics_groups
    def statistics_snapshot(self):
        return dict(min_samples=int(self.profile.get('statistics_min_samples',20)),
                    refresh_seconds=float(self.profile.get('statistics_refresh_seconds',30)),
                    evidence_refreshed_at=getattr(self,'_statistics_groups_at',None),
                    best_segments=leaderboard_groups(self.statistics_groups(),1,10),
                    matrix=statistics_matrix(self.statistics_groups(),self.profile),
                    latest_decisions=list(self.decisions.values())[-20:])

"""Evidence-based continuation comparisons plus explicit dollar loss budgets.
A confidence bound is an estimate, never a guarantee of price or execution.
"""
import math
from decimal import Decimal as D
from .core import ZERO

class ExitEvidence:
    def __init__(self,cells=None):self.cells=cells or {}
    def key(self,series,bid,remaining):return f'{series}|{int(bid*20)}|{int(max(0,remaining)//60)}'
    def observe(self,key,recovery):
        value=max(0.,min(1.,float(recovery)))
        c=self.cells.setdefault(key,dict(n=0,total=0.,square=0.))
        c['n']+=1;c['total']+=value;c['square']+=value*value
    def estimate(self,key):
        c=self.cells.get(key,{});n=c.get('n',0)
        if n<30:return dict(samples=n,upper=None,mean=None)
        mean=c['total']/n
        # Empirical Bernstein upper bound for a bounded [0,1] recovery. More
        # conservative than declaring a price stop optimal from a few examples.
        variance=max(0,(c['square']-n*mean*mean)/(n-1))
        radius=math.sqrt(2*variance*math.log(60)/n)+7*math.log(60)/(3*(n-1))
        return dict(samples=n,mean=mean,upper=min(1.,mean+radius))

def liquidation(engine,ticker,side,quantity):
    left=quantity;net=ZERO
    for price,depth in engine.books[ticker].iter_depth(side,'sell'):
        take=min(left,depth)
        if take:
            net+=take*price-engine.fees[ticker].charge(take,price,False);left-=take
        if not left:return net
    return None  # Missing depth is not an executable price of zero.

def assess(engine,ticker,lots,attempt,evidence):
    quantity=sum((l.quantity for l in lots),ZERO)
    if not quantity:return None
    side=lots[0].side;bid=engine.books[ticker].bid(side)
    if bid is None:return None
    key=evidence.key(ticker.split('-')[0],bid,engine.markets[ticker]['close']-engine.now)
    # One observation per market/state bucket, not one per tick.
    attempt.setdefault('risk_observations',{})[key]=True
    proceeds=liquidation(engine,ticker,side,quantity)
    estimate=evidence.estimate(key)
    attempt['risk_estimate']=dict(estimate,liquidation_net=str(proceeds) if proceeds is not None else None)
    if proceeds is None:return None
    cost=sum((l.quantity*l.price+l.entry_fee for l in lots),ZERO)
    # Budget is allocated per acquired contract so partial fills cannot consume
    # the original full-order dollar allowance repeatedly.
    budget=D(attempt['loss_budget'])*quantity/D(attempt['quantity'])
    if cost-proceeds>=budget:return 'Dollar loss budget reached; depth-qualified IOC exit'
    if estimate['upper'] is not None and proceeds/quantity>D(str(estimate['upper'])):
        return 'Net sale value exceeds conservative upper continuation estimate'
    return None

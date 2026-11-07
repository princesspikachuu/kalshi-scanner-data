"""Coverage-proven sets: NO on distinct mutually exclusive outcomes pays at least n-1.
No assumption that a list of YES markets is exhaustive; no LLM rule inference.
"""
from itertools import combinations
from decimal import Decimal as D
import json
from .core import ConvexityStrategy,ZERO

class CompleteSetStrategy(ConvexityStrategy):
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,None,profile['name'])
        self.profile=profile;self.groups={};self.attempts={};self.last_scan=0;self.scans=0;self.profitable=0
        self.last_reason='Waiting for verified mutually exclusive same-day events'
    def exit_allowed(self,order):return self.e.now<self.e.markets[order.ticker]['close']
    def safety_cancel(self,ticker):pass
    def on_fill(self,order,quantity):pass
    def register(self,event,markets):
        # Every constituent must belong to the same authoritative event. At most
        # one YES is enough for a NO basket; exhausting all outcomes is unnecessary.
        if event.get('mutually_exclusive') is not True or not 2<=len(markets)<=8:return False
        tickers=[m['ticker'] for m in markets]
        if len(set(tickers))!=len(tickers) or any(m.get('event_ticker')!=event['event_ticker'] for m in markets):return False
        self.groups[event['event_ticker']]=tickers;return True
    def cost(self,ticker,quantity):
        left=quantity;cost=ZERO;limit=None
        for price,depth in self.e.books[ticker].depth('no','buy'):
            take=min(left,depth)
            if take:
                cost+=take*price+self.e.fees[ticker].charge(take,price,False)
                left-=take;limit=price
            if not left:return cost,limit
        return None,None
    def step(self,changed_ticker=None):
        now=self.e.now
        for event,a in list(self.attempts.items()):
            if a.get('finished'):continue
            orders=[self.e.orders.get(i) for i in a['orders']]
            if any(o and o.status in ('pending','resting') for o in orders):continue
            qty=D(a['quantity']);inventory=[self.e.wallet.inventory(t,'no') for t in a['tickers']]
            if not a.get('checked'):
                a['checked']=True
                if all(q==qty for q in inventory):
                    a['complete']=True;self.e.log('SET_COMPLETED',details=json.dumps(a))
                else:
                    a['complete']=False;self.e.log('SET_INCOMPLETE',reason='Individual leg executions did not complete the package',details=json.dumps(a))
            if a['complete']:
                if all(self.e.markets[t].get('paid') for t in a['tickers']):a['finished']=True
                continue
            # Unwind only failed-package inventory; successful baskets remain
            # hedged until each outcome is authoritatively settled.
            if now-a.get('last_unwind',0)<1:continue
            a['last_unwind']=now
            for ticker in a['tickers']:
                lots=[l for l in self.e.wallet.lots if l.ticker==ticker]
                if lots and self.e.book_fresh(ticker) and now<self.e.markets[ticker]['close']:
                    if not any(o.ticker==ticker and o.status=='pending' for o in self.e.orders.values()):
                        self.e.place(ticker,'no','sell',sum((l.quantity for l in lots),ZERO),D('.01'),maker=False,targets=[l.id for l in lots])
            if not any(inventory):a['finished']=True
        if not self.enabled or now-self.last_scan<1:return
        self.last_scan=now
        for event,tickers in list(self.groups.items()):
            if event in self.attempts:continue
            ready=[t for t in tickers if t in self.e.markets and 1<self.e.markets[t]['close']-now<=86400
                   and self.e.book_fresh(t) and self.e.wallet.stat(t).valid and t not in self.halted]
            if len(ready)<2:continue
            self.scans+=1;best=None
            # Pairs minimize leg risk; also compare the full available basket.
            baskets=list(combinations(ready,2))
            if len(ready)>2:baskets.append(tuple(ready))
            for basket in baskets:
                for qty in sorted({D(1),min(D(5),self.contracts),self.contracts}):
                    prices=[self.cost(t,qty) for t in basket]
                    if any(c is None for c,p in prices):continue
                    cost=sum((c for c,p in prices),ZERO);profit=qty*(len(basket)-1)-cost
                    # Positive buffer is an explicit paper execution margin, not a
                    # probability claim. Prices are capped at the observed depth.
                    if profit<qty*D('.01') or cost>self.e.available():continue
                    if best is None or profit>best[0]:best=(profit,basket,qty,prices,cost)
            if best:
                profit,basket,qty,prices,cost=best;self.profitable+=1
                a=dict(tickers=list(basket),quantity=str(qty),minimum_payout=str(qty*(len(basket)-1)),
                    expected_cost=str(cost),expected_net=str(profit),started_at=now,orders=[],finished=False)
                self.attempts[event]=a
                self.e.log('SET_OPPORTUNITY',details=json.dumps(a))
                for ticker,(_,limit) in zip(basket,prices):
                    a['orders'].append(self.e.place(ticker,'no','buy',qty,limit,maker=False,expiry=now+2))
                self.last_reason='Executing depth-qualified paper complete set'
            else:self.last_reason='Scanning verified sets; no executable net discount'

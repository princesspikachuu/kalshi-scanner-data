"""Experimental policy: relative quotes and market-level, bounded continuation evidence.

Only finished, feed-valid attempts train the model. Estimates describe the policy
that generated them, not an independently observed counterfactual return.
"""
import math
from decimal import Decimal as D
from .core import ZERO
from .sequential import SequentialStrategy,PairModel
from .risk import liquidation

def category(m):
    return 'sports' if m.get('sports') else str(m.get('weather_category') or '15m')

def time_band(seconds):return sum(seconds>x for x in (180,600,1800,7200))

def bounded_radius(n,total,square,width):
    variance=max(0.,(square-total*total/n)/(n-1)) if n>1 else 0.
    return math.sqrt(2*variance*math.log(60)/n)+7*width*math.log(60)/(3*(n-1)) if n>1 else float('inf')

class AdaptivePairModel(PairModel):
    def observe(self,key,first,completed,net):
        super().observe(key,first,completed,net)
        if key.startswith('entry|'):super().observe(key.rsplit('|',1)[0],first,completed,net)
    def estimate(self,key):
        exact=self.cells.get(key,{})
        pooled=key.rsplit('|',1)[0]
        source=key if exact.get('n',0)>=60 else pooled
        c=self.cells.get(source,{})
        result=super().estimate(source);n=c.get('n',0)
        result.update(evidence='series' if source==key else 'category_pool',series_samples=exact.get('n',0))
        # Net per proposed contract lies in [-1,1]. A conservative bound avoids
        # promoting a tiny streak of identical wins to full-size trading.
        result['lower_net']=c['total']/n-bounded_radius(n,c['total'],c['square'],2) if n>=60 else None
        return result
    def observe_state(self,key,completed,recovery):
        if not 0<=recovery<=1:return
        for k in (key,'|'.join(key.split('|')[:5])):
            c=self.cells.setdefault(k,dict(n=0,completed=0,total=0.,square=0.))
            c['n']+=1;c['completed']+=int(completed);c['total']+=recovery;c['square']+=recovery*recovery
    def state_estimate(self,key):
        c=self.cells.get(key,{})
        pooled=False
        if c.get('n',0)<60:c=self.cells.get('|'.join(key.split('|')[:5]),{});pooled=True
        n=c.get('n',0)
        if n<60:return dict(samples=n,completion_probability=None,recovery_upper=None,pooled=pooled)
        mean=c['total']/n
        return dict(samples=n,completion_probability=(c['completed']+1)/(n+2),
            recovery_upper=min(1.,mean+bounded_radius(n,c['total'],c['square'],1)),pooled=pooled)

class AdaptiveSequentialStrategy(SequentialStrategy):
    def candidates(self,book):
        y,n=book.bid('yes'),book.bid('no')
        if y is None or n is None:return ()
        # Candidate distances are relative to each side's bid, including
        # asymmetric markets. A small fixed grid bounds exploration and state.
        return sorted({(max(1,int(y*100)-dy),max(1,int(n*100)-dn))
            for dy,dn in ((0,0),(2,2),(5,5),(8,8),(2,5),(5,2),(0,5),(5,0))})
    def choice_key(self,m,remaining,movement,prices):
        book=self.e.books[m['ticker']]
        distances=(int(book.bid('yes')*100)-prices[0],int(book.bid('no')*100)-prices[1])
        return '|'.join(map(str,('entry',category(m),time_band(remaining),'moving' if abs(movement)>.04 else 'quiet',*distances,self.series)))
    def deadline(self,m,now,movement):
        horizon=min(900,max(60,(m['close']-now)*.35/(1+20*abs(movement))))
        return min(m['close']-30,now+horizon)
    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        if a and not a.get('first') and order.action=='buy':
            book=self.e.books[order.ticker]
            y,n=book.bid('yes'),book.bid('no')
            if y is not None and n is not None:a['first_mid']=float((y+1-n)/2)
        super().on_fill(order,quantity)
    def continuation(self,ticker,lots,a):
        book=self.e.books[ticker];m=self.e.markets[ticker];now=self.e.now
        y,n=book.bid('yes'),book.bid('no')
        if y is None or n is None:return None
        mid=float((y+1-n)/2);side=lots[0].side
        adverse=(a.get('first_mid',mid)-mid)*(1 if side=='yes' else -1)
        move=-1 if adverse<-.02 else 1 if adverse>.02 else 0
        spread=int((1-y-n)*100);depth_y=book.levels['yes'].get(y,ZERO);depth_n=book.levels['no'].get(n,ZERO)
        imbalance=float((depth_y-depth_n)/(depth_y+depth_n)) if depth_y+depth_n else 0
        queue=sum((o.ahead for o in self._open(ticker) if o.action=='buy'),ZERO)
        key='|'.join(map(str,('state',category(m),time_band(m['close']-now),side,move,
            min(3,max(0,spread)//2),-1 if imbalance<-.3 else 1 if imbalance>.3 else 0,min(3,int(queue/10)))))
        states=a.setdefault('continuation_states',{})
        # One sample per attempt/state; bounded storage, no per-tick pseudo-samples.
        if len(states)<24:states.setdefault(key,True)
        estimate=self.model.state_estimate(key);a['continuation_estimate']=estimate
        qty=sum((l.quantity for l in lots),ZERO);sale=liquidation(self.e,ticker,side,qty)
        if sale is not None and estimate['recovery_upper'] is not None and sale/qty>D(str(estimate['recovery_upper'])):
            return 'Executable net sale exceeds conditional continuation upper estimate'
        return None
    def finish(self,ticker):
        a=self.attempts[ticker]
        if a.get('recorded'):return
        super().finish(ticker)
        if not self.e.wallet.stat(ticker).valid or not a.get('first') or not D(a.get('first_quantity','0')):return
        recovery=float((D(a['net'])+D(a['first_cost']))/D(a['first_quantity']))
        for key in a.get('continuation_states',{}):self.model.observe_state(key,a['completed'],recovery)

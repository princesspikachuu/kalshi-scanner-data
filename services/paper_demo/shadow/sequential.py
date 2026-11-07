"""Sequential maker pairs. Empirical estimates never substitute price touches for fills."""
import math
from collections import deque
from decimal import Decimal as D
from .core import ConvexityStrategy,ZERO
from .risk import ExitEvidence,assess

CANDIDATES=((40,40),(43,43),(45,45),(47,47),(49,49),(40,48),(48,40))

class PairModel:
    def __init__(self,data=None):self.cells=data or {}
    def key(self,series,seconds,movement,prices):
        return '|'.join(map(str,(series,int(seconds//180), 'moving' if abs(movement)>.04 else 'quiet',*prices)))
    def observe(self,key,first,completed,net):
        c=self.cells.setdefault(key,dict(n=0,first=0,completed=0,total=0.,square=0.))
        c['n']+=1;c['first']+=bool(first);c['completed']+=bool(completed)
        c['total']+=float(net);c['square']+=float(net)**2
    def estimate(self,key):
        c=self.cells.get(key,{}) ;n=c.get('n',0)
        if not n:return dict(samples=0,first_probability=None,completion_probability=None,expected_net=None,lower_net=None)
        mean=c['total']/n
        variance=max(0,(c['square']-n*mean*mean)/(n-1)) if n>1 else 0
        return dict(samples=n,first_probability=(c['first']+1)/(n+2),
            completion_probability=(c['completed']+1)/(c['first']+2),expected_net=mean,
            lower_net=mean-1.96*math.sqrt(variance/n) if n>=20 else None)

class SequentialStrategy(ConvexityStrategy):
    def __init__(self,engine,profile,model):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile,self.model=profile,model
        self.exit_evidence=ExitEvidence()
        self.attempts={};self.history={};self.decisions={};self.exit_at={}
    def safety_cancel(self,ticker):pass
    def exit_allowed(self,order):return self.e.now<self.e.markets[order.ticker]['close']
    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        if not a:return
        if order.action=='sell':return
        if not a['first']:a.update(first_side=order.side,first_quantity='0',first_cost='0')
        a['first']=True
        if order.side==a.get('first_side'):
            a['first_quantity']=str(D(a['first_quantity'])+quantity)
            a['first_cost']=str(D(a['first_cost'])+quantity*order.price+self.e.fees[order.ticker].charge(quantity,order.price,order.maker))
        # Cancel the original pair before replacing with the exact residual hedge.
        # Cancellation has latency; outstanding quantities are reconciled in step().
        self.e.cancel_buys(order.ticker)
    def _open(self,ticker):
        return [o for o in self.e.orders.values() if o.ticker==ticker and o.status in ('pending','resting')]
    def finish(self,ticker):
        a=self.attempts[ticker]
        if a.get('recorded'):return
        stat=self.e.wallet.stat(ticker)
        net=stat.gross-stat.realized_fees-D(a['baseline'])
        complete=a['first'] and not a.get('failed',False) and not self.e.wallet.inventory(ticker,'yes') and not self.e.wallet.inventory(ticker,'no')
        # Feed interruptions are never training evidence, but retain financial losses.
        if stat.valid and a['first'] and D(a.get('first_quantity','0')):
            recovery=(net+D(a['first_cost']))/D(a['first_quantity'])
            for key in a.get('risk_observations',{}):self.exit_evidence.observe(key,recovery)
        if stat.valid:self.model.observe(a['key'],a['first'],complete,net/D(a['quantity']))
        a.update(recorded=True,completed=complete,net=str(net))
        self.e.log('PAIR_RESULT',ticker=ticker,details=__import__('json').dumps(a))
    def step(self,changed_ticker=None):
        for ticker,m in list(self.e.markets.items()):
            if not ticker.startswith(self.series+'-') or changed_ticker and ticker!=changed_ticker:continue
            now=self.e.now;remaining=m['close']-now
            a=self.attempts.get(ticker);book=self.e.books[ticker]
            if a:
                lots=[l for l in self.e.wallet.lots if l.ticker==ticker]
                orders=self._open(ticker)
                if a.get('recorded'):continue
                if m.get('paid') and a['first']:a['failed']=True
                if m.get('paid') or (a['first'] and not lots and not orders):self.finish(ticker);continue
                if remaining<=0:continue
                if not a['first']:
                    if now>=a['entry_deadline'] or not self.enabled or ticker in self.halted:
                        self.e.cancel_buys(ticker)
                        if not orders:self.finish(ticker)
                    continue
                if not lots:continue
                # Once first filled, stop increasing inventory. Only residual hedge
                # quantities are replaced, and only after cancellations acknowledge.
                if not self.e.book_fresh(ticker):continue
                lot=lots[0];qty=sum((l.quantity for l in lots if l.side==lot.side),ZERO)
                reason=assess(self.e,ticker,lots,a,self.exit_evidence)
                if reason:a['failed']=True;a['exit_reason']=reason;self.e.cancel_buys(ticker)
                if orders:continue
                if remaining<=30 or now>=a['completion_deadline'] or a.get('failed'):
                    a['failed']=True
                    if now-self.exit_at.get(ticker,0)>=1:
                        self.exit_at[ticker]=now
                        self.e.place(ticker,lot.side,'sell',qty,D('.01'),maker=False,phase=1,targets=[l.id for l in lots])
                    continue
                opposite='no' if lot.side=='yes' else 'yes';price=D(a['no'] if opposite=='no' else a['yes'])
                ask=book.ask(opposite)
                if ask and price<ask:self.e.place(ticker,opposite,'buy',qty,price,expiry=a['completion_deadline'])
                continue
            if (not self.enabled or ticker in self.halted or not self.e.wallet.stat(ticker).valid or
                not self.e.book_fresh(ticker) or remaining<180 or now<m.get('open',m['close']-900) or now<self.e.safety_until):continue
            y,n=book.bid('yes'),book.bid('no')
            if y is None or n is None:continue
            h=self.history.setdefault(ticker,deque(maxlen=120));h.append((now,float((y+1-n)/2)))
            while h and now-h[0][0]>60:h.popleft()
            if not h or now-h[0][0]<20:continue
            movement=h[-1][1]-h[0][1]
            choices=[]
            for yp,np in CANDIDATES:
                yes,no=D(yp)/100,D(np)/100
                if yes>=book.ask('yes') or no>=book.ask('no'):continue
                fee=self.e.fees[ticker].charge(D(1),yes,True)+self.e.fees[ticker].charge(D(1),no,True)
                if 1-yes-no-fee<=0:continue
                key=self.model.key(self.series,remaining,movement,(yp,np));estimate=self.model.estimate(key)
                choices.append((estimate,key,yes,no))
            if not choices:continue
            supported=[c for c in choices if c[0]['lower_net'] is not None and c[0]['lower_net']>0]
            if supported:
                estimate,key,yes,no=max(supported,key=lambda c:c[0]['lower_net']);quantity=self.contracts;mode='empirical'
            else:
                # Explicit 1-contract paper exploration, never presented as a
                # positive-profit forecast. Deterministic least-sampled rotation.
                estimate,key,yes,no=min(choices,key=lambda c:(c[0]['samples'],sum(map(ord,ticker+c[1]))%997))
                quantity=D(1);mode='paper_exploration'
            required=quantity*(yes+no)+self.e.fees[ticker].charge(quantity,yes,True)+self.e.fees[ticker].charge(quantity,no,True)
            if required>self.e.available():continue
            a=dict(key=key,yes=str(yes),no=str(no),quantity=str(quantity),first=False,recorded=False,
                baseline=str(self.e.wallet.stat(ticker).gross-self.e.wallet.stat(ticker).realized_fees),
                entry_deadline=min(now+60,m['close']-120),completion_deadline=m['close']-30,
                mode=mode,estimate=estimate,started_at=now,loss_budget=str(min(D(5),self.e.wallet.cash*D('.01'))))
            self.attempts[ticker]=a;self.decisions[ticker]=a
            self.e.log('PAIR_DECISION',ticker=ticker,details=__import__('json').dumps(a))
            self.e.place(ticker,'yes','buy',quantity,yes,expiry=a['entry_deadline'])
            self.e.place(ticker,'no','buy',quantity,no,expiry=a['entry_deadline'])

"""Paper test of maker purchases of market-implied favorites; no presumed edge."""
import json
from decimal import Decimal as D
from .core import ConvexityStrategy,ZERO
from .risk import ExitEvidence,assess
from .favorite_entries import quote,observe

class FavoritesStrategy(ConvexityStrategy):
    recover_fresh_entries=True
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile=profile;self.attempts={};self.decisions={};self.exit_evidence=ExitEvidence();self.exit_at={}
        self.last_reason=('Waiting for verified live sport · final two estimated hours' if profile.get('asset')=='sports' else 'Waiting for a 70–95¢ favorite · maker entry with evidence-based risk exits')
    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        if a and order.action=='buy':a['first']=True
        self.e.cancel_buys(order.ticker)
    def safety_cancel(self,ticker):pass
    def exit_allowed(self,order):return self.e.now<self.e.markets[order.ticker]['close']
    def entry_quote(self,ticker,side,max_price=None):
        return quote(self.e,self.profile,self.contracts,ticker,side,self.exit_evidence.cells,max_price)
    def cancel_entry(self,ticker,reason):
        self.e.cancel_buys(ticker)
        self.last_reason=reason
    def submit_entry(self,ticker,a,q):
        # Never stack a replacement on an outstanding cancellation or partial fill.
        if any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):return
        expiry=min(self.e.now+30,a['entry_deadline'])
        if expiry<=self.e.now+self.e.latency:return
        a.update(price=str(q['price']),quantity=str(q['quantity']),entry_key=q['key'],
            entry_mode=q['mode'],entry_estimate=q['estimate'],last_submit=self.e.now,
            price_band='70–79¢' if q['price']<D('.80') else '80–89¢' if q['price']<D('.90') else '90–95¢',
            breakeven_probability=str(q['price']+q['fee']/q['quantity']))
        self.last_reason=(f"1-contract maker demo trial at {q['price']*100:.0f}¢ · probability unknown" if q['mode']=='paper_exploration' else
            f"Value-qualified maker at {q['price']*100:.0f}¢ · {q['estimate']['samples']} settled events")
        self.e.log('FAVORITE_ENTRY_DECISION',ticker=ticker,reason=self.last_reason,details=json.dumps(dict(mode=q['mode'],estimate=q['estimate'],ceiling=q['ceiling'])))
        self.e.place(ticker,a['side'],'buy',q['quantity'],q['price'],maker=True,expiry=expiry)
    def entry_allowed(self,m,now):
        if self.profile.get('retired') or self.series.endswith('15M'):return False
        return not m.get('sports') or (m.get('sports_live') is True and
            m.get('sports_start',float('inf'))<=now<m.get('sports_verified_until',0) and
            60<m.get('sports_expected_end',0)-now<=self.profile.get('late_game_hours',2)*3600)
    def entry_deadline(self,m,now):
        deadline=m['close']-60
        if m.get('sports'):deadline=min(deadline,m.get('sports_verified_until',now),m.get('sports_expected_end',now)-60)
        return deadline
    def entry_ready(self,ticker):
        book=self.e.books[ticker];m=self.e.markets[ticker]
        if not self.e.book_fresh(ticker):return False
        # A new verified snapshot establishes present execution state. Earlier
        # missing data stays excluded from historical metrics and model training.
        recovered=getattr(book,'snapshot_at',0)>0
        if recovered and m.pop('entry_recovery_halt',False):
            self.halted.discard(ticker)
            self.e.log('FAVORITE_ENTRY_RECOVERED',ticker=ticker,reason='Fresh full snapshot; earlier gap remains excluded')
        return ticker not in self.halted and (self.e.wallet.stat(ticker).valid or recovered)
    def step(self,changed_ticker=None):
        markets=([(changed_ticker,self.e.markets[changed_ticker])] if changed_ticker in self.e.markets else []) if changed_ticker is not None else list(self.e.markets.items())
        for ticker,m in markets:
            if not ticker.startswith(self.series+'-'):continue
            a=self.attempts.get(ticker);now=self.e.now
            if m.get('paid'):
                if not a or a.get('recorded'):continue
                s=self.e.wallet.stat(ticker)
                if s.valid and a['first'] and m.get('yes_payout_confirmed') in ('0','1'):
                    payout=int(m['yes_payout_confirmed']==('1' if a['side']=='yes' else '0'))
                    for key in a.get('risk_observations',{}):self.exit_evidence.observe(key,payout)
                    if a.get('entry_key'):observe(self.exit_evidence.cells,a['entry_key'],m.get('event_ticker',ticker),payout)
                a.update(recorded=True,completed=a['first'],net=str(s.gross-s.realized_fees))
                self.last_reason='Favorite trial settled; result includes all fees'
                continue
            if a and a.get('first'):
                self.e.cancel_buys(ticker)
                lots=[l for l in self.e.wallet.lots if l.ticker==ticker]
                if lots and self.e.book_fresh(ticker):
                    reason=assess(self.e,ticker,lots,a,self.exit_evidence)
                    if reason:a['exit_reason']=reason
                    if a.get('exit_reason') and now-self.exit_at.get(ticker,0)>=1 and not any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):
                        self.exit_at[ticker]=now
                        self.e.log('FAVORITE_RISK_EXIT',ticker=ticker,reason=a['exit_reason'])
                        self.e.place(ticker,a['side'],'sell',sum((l.quantity for l in lots),ZERO),D('.01'),maker=False,targets=[l.id for l in lots])
                continue
            if not self.enabled or not self.entry_allowed(m,now) or not self.entry_ready(ticker) or m['close']-now<=60:
                if a:self.cancel_entry(ticker,'Waiting: entry conditions or fresh verified book unavailable')
                continue
            if a and now<a.get('retry_at',0):continue
            deadline=self.entry_deadline(m,now)
            if deadline<=now+self.e.latency:
                if a:self.cancel_entry(ticker,'Waiting for renewed live verification')
                continue
            if not a:
                book=self.e.books[ticker]
                quotes=[(book.bid(side),side) for side in ('yes','no') if book.bid(side) is not None]
                if not quotes:continue
                _,side=max(quotes)
            else:side=a['side']
            q=self.entry_quote(ticker,side,a.get('initial_ceiling',a['price']) if a else None)
            active=[o for o in self.e.orders.values() if o.ticker==ticker and o.status in ('pending','resting')]
            if not q:
                if a:
                    self.cancel_entry(ticker,'Waiting for a maker bid with sufficient value after fees')
                    a['retry_at']=now+2
                else:self.last_reason='Waiting for a maker bid with sufficient value after fees'
                continue
            if not a:
                price,quantity,fee=q['price'],q['quantity'],q['fee']
                a=dict(first=False,recorded=False,side=side,price=str(price),quantity=str(quantity),
                    entry_deadline=deadline,started_at=now,implied_probability=str(price),initial_ceiling=str(price),
                    loss_budget=str(min(D(5),self.e.wallet.cash*D('.01'))))
                self.attempts[ticker]=a
            a.update(recorded=False,entry_deadline=deadline)
            if any(o.price>q['price'] or o.quantity>q['quantity'] or (a.get('entry_mode')=='calibrated_maker' and q['mode']=='paper_exploration') for o in active):
                self.cancel_entry(ticker,'Maker entry cancelled: value or fee conditions changed')
                a['retry_at']=now+1
            elif active:
                # Extend the safety lease only after full revalidation. Keep the
                # original arrival/queue position and never revive a cancellation.
                canceling={ident for _,_,action,ident in self.e.pending if action=='cancel'}
                for order in active:
                    if order.id not in canceling:order.expiry=min(now+30,deadline)
            else:self.submit_entry(ticker,a,q)

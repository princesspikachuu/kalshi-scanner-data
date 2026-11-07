"""Paper test of maker purchases of market-implied favorites; no presumed edge."""
from decimal import Decimal as D,ROUND_FLOOR
from .core import ConvexityStrategy,ZERO
from .risk import ExitEvidence,assess

class FavoritesStrategy(ConvexityStrategy):
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
    def entry_allowed(self,m,now):
        if self.profile.get('retired') or self.series.endswith('15M'):return False
        return not m.get('sports') or (m.get('sports_live') is True and
            m.get('sports_start',float('inf'))<=now<m.get('sports_verified_until',0) and
            60<m.get('sports_expected_end',0)-now<=self.profile.get('late_game_hours',2)*3600)
    def step(self,changed_ticker=None):
        for ticker,m in list(self.e.markets.items()):
            if not ticker.startswith(self.series+'-') or changed_ticker and changed_ticker!=ticker:continue
            a=self.attempts.get(ticker);now=self.e.now
            if a:
                if a.get('recorded'):continue
                if not self.enabled or not self.entry_allowed(m,now):self.e.cancel_buys(ticker)
                if m.get('paid'):
                    s=self.e.wallet.stat(ticker)
                    if s.valid and a['first']:
                        payout=1 if m.get('yes_payout_confirmed')==('1' if a['side']=='yes' else '0') else 0
                        if m.get('yes_payout_confirmed') in ('0','1'):
                            for key in a.get('risk_observations',{}):self.exit_evidence.observe(key,payout)
                    a.update(recorded=True,completed=a['first'],net=str(s.gross-s.realized_fees))
                    self.last_reason='Favorite trial settled; result includes all fees'
                elif a['first']:
                    lots=[l for l in self.e.wallet.lots if l.ticker==ticker]
                    if lots and self.e.book_fresh(ticker):
                        reason=assess(self.e,ticker,lots,a,self.exit_evidence)
                        if reason:a['exit_reason']=reason;self.e.cancel_buys(ticker)
                        if a.get('exit_reason') and now-self.exit_at.get(ticker,0)>=1 and not any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):
                            self.exit_at[ticker]=now
                            self.e.log('FAVORITE_RISK_EXIT',ticker=ticker,reason=a['exit_reason'])
                            self.e.place(ticker,a['side'],'sell',sum((l.quantity for l in lots),ZERO),D('.01'),maker=False,targets=[l.id for l in lots])
                elif not a['first'] and now>=a['entry_deadline']:
                    self.e.cancel_buys(ticker)
                    if not any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):a['recorded']=True
                continue
            if (not self.enabled or not self.entry_allowed(m,now) or ticker in self.halted or not self.e.wallet.stat(ticker).valid or
                not self.e.book_fresh(ticker) or m['close']-now<60):continue
            book=self.e.books[ticker];quotes=[(book.bid(side),side) for side in ('yes','no') if book.bid(side) is not None]
            if not quotes:continue
            bid,side=max(quotes);ask=book.ask(side)
            if not ask:continue
            price=min(bid+D('.01'),ask-D('.01'))
            if not D('.70')<=price<=D('.95'):continue
            quantity=min(self.contracts,(self.e.available()*D('.05')/price).to_integral_value(rounding=ROUND_FLOOR))
            if quantity<1:continue
            fee=self.e.fees[ticker].charge(quantity,price,True)
            if quantity*price+fee>self.e.available():continue
            deadline=min(now+60,m['close']-30)
            if m.get('sports'):deadline=min(deadline,m['sports_verified_until'],m['sports_expected_end']-60)
            if deadline<=now+self.e.latency:continue
            a=dict(first=False,recorded=False,side=side,price=str(price),quantity=str(quantity),
                entry_deadline=deadline,started_at=now,implied_probability=str(price),
                loss_budget=str(min(D(5),self.e.wallet.cash*D('.01'))),breakeven_probability=str(price+fee/quantity),price_band='70–79¢' if price<D('.80') else '80–89¢' if price<D('.90') else '90–95¢')
            self.attempts[ticker]=a
            self.last_reason=f"Testing {side.upper()} favorite at {price*100:.0f}¢ · risk-managed"
            self.e.place(ticker,side,'buy',quantity,price,expiry=deadline)

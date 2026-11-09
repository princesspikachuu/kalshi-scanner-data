"""Paper test of maker purchases of market-implied favorites; no presumed edge."""
import json
from decimal import Decimal as D
from .core import ConvexityStrategy,ZERO
from .risk import ExitEvidence,assess
from .favorite_entries import quote,observe,entry_key
from . import favorite_timing

class FavoritesStrategy(ConvexityStrategy):
    recover_fresh_entries=True
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile=profile;self.attempts={};self.decisions={};self.exit_evidence=ExitEvidence();self.exit_at={}
        self.last_reason=('Waiting for verified live sport · final two estimated hours' if profile.get('asset')=='sports' else 'Waiting for a 70–95¢ favorite · maker entry with evidence-based risk exits')
    def on_data_gap(self,ticker,reason):
        a=self.attempts.get(ticker);window=a.get('data_window') if a else None
        if window and window.get('valid') and not window.get('ended_at') and self.e.now<self.e.markets[ticker]['close']:
            window.update(valid=False,gap_at=self.e.now,reason=reason)

    def trial_valid(self,ticker,a):
        window=a.get('data_window')
        return window.get('valid',False) if window else self.e.wallet.stat(ticker).valid

    def finish_data_window(self,ticker,a):
        window=a.get('data_window')
        if window and a.get('first') and not any(l.ticker==ticker for l in self.e.wallet.lots) and not any(
                o.ticker==ticker and o.action=='buy' and o.status in ('pending','resting') for o in self.e.orders.values()):
            window.setdefault('ended_at',self.e.now)

    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        favorite_timing.fill(self,order,quantity,entry_key)
        if a and order.action=='buy':
            a['first']=True
            if a.get('entry_policy')=='favorites-paper-data-v3':
                for other in self.e.orders.values():
                    if other.ticker==order.ticker and other.action=='buy' and other.id!=order.id:self.e.cancel(other.id)
                return
        self.e.cancel_buys(order.ticker)
        if a and order.action=='sell':self.finish_data_window(order.ticker,a)
    def retain_partial_entry(self,ticker,m,a,lots):
        active=[o for o in self.e.orders.values() if o.ticker==ticker and o.action=='buy' and o.status in ('pending','resting')]
        if not active:return
        q=self.entry_quote(ticker,a['side']) if (self.enabled and self.entry_allowed(m,self.e.now)
            and self.entry_ready(ticker) and m['close']-self.e.now>60 and not a.get('exit_reason')) else None
        desired=max(ZERO,D(a.get('target_inventory',str(self.contracts)))-sum((l.quantity for l in lots),ZERO))
        if not q or any(o.price>q['price'] or o.remaining>min(desired,q['quantity']) for o in active):
            self.e.cancel_buys(ticker);return
        canceling={ident for _,_,action,ident in self.e.pending if action=='cancel'}
        for order in active:
            if order.id not in canceling:order.expiry=min(self.e.now+30,self.entry_deadline(m,self.e.now))
    def safety_cancel(self,ticker):pass
    def exit_allowed(self,order):return self.e.now<self.e.markets[order.ticker]['close']
    def entry_quote(self,ticker,side,max_price=None):
        return quote(self.e,self.profile,self.contracts,ticker,side,self.exit_evidence.cells,
            None if self.profile.get('paper_exploration',True) is not False else max_price)
    def cancel_entry(self,ticker,reason):
        self.e.cancel_buys(ticker)
        self.last_reason=reason
    def submit_entry(self,ticker,a,q):
        # Never stack a replacement on an outstanding cancellation or partial fill.
        if any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):return
        expiry=min(self.e.now+30,a['entry_deadline'])
        if expiry<=self.e.now+self.e.latency:return
        if not a.get('first'):
            a['data_window']=dict(started_at=self.e.now,valid=self.entry_ready(ticker),scope='entry-through-exit-or-close-v1')
        elif a.get('data_window',{}).get('ended_at') is not None:
            # A second opportunity may follow an earlier fully closed position.
            a['data_window'].pop('ended_at',None)
            a['data_window']['valid']=a['data_window'].get('valid',True) and self.entry_ready(ticker)
        a.update(price=str(q['price']),quantity=str(q['quantity']),entry_key=q['key'],
            entry_mode=q['mode'],entry_estimate=q['estimate'],entry_policy=q['policy'],last_submit=self.e.now,
            price_band='70–79¢' if q['price']<D('.80') else '80–89¢' if q['price']<D('.90') else '90–95¢',
            breakeven_probability=str(q['price']+q['fee']/q['quantity']))
        self.last_reason=(f"{q['quantity']:f}-contract maker data trial at {q['price']*100:.0f}¢ · collecting outcomes" if q['mode']=='paper_exploration' else
            f"Value-qualified maker at {q['price']*100:.0f}¢ · {q['estimate']['samples']} settled events")
        ident=self.e.place(ticker,a['side'],'buy',q['quantity'],q['price'],maker=True,expiry=expiry)
        request=self.e.orders[ident]
        self.e.log('FAVORITE_ENTRY_DECISION',ticker=ticker,order_id=ident,reason=self.last_reason,details=json.dumps(dict(
            mode=q['mode'],policy=q['policy'],quantity=str(q['quantity']),price=str(q['price']),estimate=q['estimate'],ceiling=q['ceiling'],execution_model=request.execution_model,
            worker_delay_ms=request.worker_delay_seconds*1000,decision_at=request.decision_at,arrival_at=request.arrives)))
        if q['mode']=='paper_exploration':
            print(json.dumps(dict(event='favorite_paper_entry',ticker=ticker,order_id=ident,quantity=str(q['quantity']),
                price=str(q['price']),policy=q['policy'],maker=True,execution_model=request.execution_model,
                worker_delay_ms=request.worker_delay_seconds*1000,arrival_at=request.arrives,real_orders_enabled=False)),flush=True)
    def repeat_data_entry(self,ticker,m,a,lots):
        """Collect distinct later signals in one market, without loop duplicates.

        Re-entry is paper-exploration only. Keep one market-level attempt record
        and its individual fill cohorts for settlement while limiting inventory
        to five configured entries per market.
        """
        if self.profile.get('paper_exploration',True) is False or a.get('entry_policy')!='favorites-paper-data-v3':
            return
        if a.get('exit_reason') or not self.enabled or m.get('entry_parked'):
            a['repeat_qualified']=False
            return
        if not self.entry_allowed(m,self.e.now) or not self.entry_ready(ticker) or m['close']-self.e.now<=60:
            a['repeat_qualified']=False
            return
        if self.entry_deadline(m,self.e.now)<=self.e.now+self.e.latency:
            a['repeat_qualified']=False
            return
        if any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):
            return
        q=self.entry_quote(ticker,a['side'])
        if not q:
            a['repeat_qualified']=False
            return
        remaining,basis=favorite_timing.clock(m,self.e.now)
        signal=entry_key(self.series,a['side'],q['price'],remaining,basis)
        if a.get('repeat_qualified') and signal==a.get('last_repeat_signal'):
            a['repeat_duplicate_suppressed']=a.get('repeat_duplicate_suppressed',0)+1
            return
        a['repeat_opportunities_detected']=a.get('repeat_opportunities_detected',0)+1
        inventory=sum((l.quantity for l in lots if l.side==a['side']),ZERO)
        max_inventory=self.contracts*D(str(self.profile.get('paper_repeat_inventory_multiplier',5)))
        if inventory+q['quantity']>max_inventory:
            a['repeat_risk_suppressed']=a.get('repeat_risk_suppressed',0)+1
            a['last_repeat_suppression']=dict(reason='inventory_cap',signal=signal,at=self.e.now)
            return
        if self.e.now-a.get('last_submit',0)<10:
            return
        # Refresh the deadline from the currently verified market state.
        # Sports verification may expire earlier than the original attempt.
        a['entry_deadline']=self.entry_deadline(m,self.e.now)
        a['target_inventory']=str(inventory+q['quantity'])
        self.submit_entry(ticker,a,q)
        a['last_repeat_signal']=signal
        a['repeat_qualified']=True
        a['repeat_entries']=a.get('repeat_entries',0)+1
        self.e.log('FAVORITE_REPEAT_OPPORTUNITY',ticker=ticker,details=json.dumps(dict(
            opportunity_key=signal,repeat_entries=a['repeat_entries'],
            inventory_before=str(inventory),max_inventory=str(max_inventory),
            price=str(q['price']),quantity=str(q['quantity']),
            entries_attempted=a['repeat_entries'],
            opportunities_detected=a['repeat_opportunities_detected']))))

    def entry_allowed(self,m,now):
        if self.profile.get('retired'):return False
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
                favorite_timing.settle(self,ticker,observe)
                trial_valid=self.trial_valid(ticker,a)
                if trial_valid and a['first'] and m.get('yes_payout_confirmed') in ('0','1'):
                    payout=int(m['yes_payout_confirmed']==('1' if a['side']=='yes' else '0'))
                    for key in a.get('risk_observations',{}):self.exit_evidence.observe(key,payout)
                    if a.get('entry_key') and not a.get('entry_fills'):observe(self.exit_evidence.cells,a['entry_key'],m.get('event_ticker',ticker),payout)
                self.e.log('FAVORITE_TRIAL_QUALITY',ticker=ticker,details=json.dumps(dict(
                    cycle_valid=s.valid,execution_window_valid=trial_valid,window=a.get('data_window'),
                    verified_entry_chunks=sum(bool(c.get('verified')) for c in a.get('entry_fills',[])))))
                a.update(recorded=True,completed=a['first'],net=str(s.gross-s.realized_fees))
                self.last_reason='Favorite trial settled; result includes all fees'
                continue
            if a and a.get('first'):
                self.finish_data_window(ticker,a)
                lots=[l for l in self.e.wallet.lots if l.ticker==ticker]
                if a.get('entry_policy')=='favorites-paper-data-v3':self.retain_partial_entry(ticker,m,a,lots)
                else:self.e.cancel_buys(ticker)
                if lots and self.e.book_fresh(ticker):
                    reason=assess(self.e,ticker,lots,a,self.exit_evidence)
                    if reason:a['exit_reason']=reason;self.e.cancel_buys(ticker)
                    if a.get('exit_reason') and now-self.exit_at.get(ticker,0)>=1 and not any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):
                        self.exit_at[ticker]=now
                        self.e.log('FAVORITE_RISK_EXIT',ticker=ticker,reason=a['exit_reason'])
                        self.e.place(ticker,a['side'],'sell',sum((l.quantity for l in lots),ZERO),D('.01'),maker=False,targets=[l.id for l in lots])
                self.repeat_data_entry(ticker,m,a,lots)
                continue
            if m.get('entry_parked') or not self.enabled or not self.entry_allowed(m,now) or not self.entry_ready(ticker) or m['close']-now<=60:
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
            reprice_for_data=q['mode']=='paper_exploration' and now-a.get('last_submit',0)>=10
            if any(o.price>q['price'] or o.quantity!=q['quantity'] or
                    (reprice_for_data and q['price']-o.price>=D('.02')) or
                    (a.get('entry_mode')=='calibrated_maker' and q['mode']=='paper_exploration') for o in active):
                self.cancel_entry(ticker,'Maker entry refreshed: current price, configured size or fee conditions changed')
                a['retry_at']=now+1
            elif active:
                # Extend the safety lease only after full revalidation. Keep the
                # original arrival/queue position and never revive a cancellation.
                canceling={ident for _,_,action,ident in self.e.pending if action=='cancel'}
                for order in active:
                    if order.id not in canceling:order.expiry=min(now+30,deadline)
            else:
                self.submit_entry(ticker,a,q)
                if q['mode']=='paper_exploration':
                    remaining,basis=favorite_timing.clock(m,now)
                    a['last_repeat_signal']=entry_key(self.series,side,q['price'],remaining,basis)
                    a['repeat_qualified']=True
                    a['target_inventory']=str(q['quantity'])

"""Paper test of maker purchases of market-implied favorites; no presumed edge."""
import json
from decimal import Decimal as D
from .core import ConvexityStrategy,ZERO
from .risk import ExitEvidence,assess
from .favorite_entries import quote,observe,entry_key
from .favorite_statistics import price_bucket
from . import favorite_timing,weather_window

class FavoritesStrategy(ConvexityStrategy):
    recover_fresh_entries=True
    hold_only=True
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile=profile;self.attempts={};self.decisions={};self.exit_evidence=ExitEvidence();self.exit_at={}
        self.last_reason=('Waiting for verified live sport · final two estimated hours' if profile.get('asset')=='sports' else 'Waiting for a 70–95¢ favorite · maker entry · hold to settlement')
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

    def research_bucket(self,ticker,side,price,at=None):
        remaining,basis=favorite_timing.clock(self.e.markets[ticker],self.e.now if at is None else at)
        return '|'.join((side,price_bucket(price),favorite_timing.horizon(remaining),basis))

    def active_buckets(self,ticker,a,active=None):
        if active is None:
            active=[o for o in self.e.orders.values() if o.ticker==ticker and o.action=='buy'
                    and o.status in ('pending','resting')]
        previous=a.get('pending_buckets',{})
        if not isinstance(previous,dict):previous={}
        buckets={o.id:previous.get(o.id) or self.research_bucket(ticker,o.side,o.price,o.created)
                 for o in active}
        # Drop old order identities; the actual fill cohorts preserve historical
        # price and time attribution through market settlement.
        a['pending_buckets']=buckets
        return active,buckets

    def filled_buckets(self,a):
        buckets={f"{a['side']}|{price_bucket(chunk['price'])}|"
                 f"{favorite_timing.horizon(float(chunk.get('seconds_to_event_end',chunk.get('seconds_to_market_close',0))))}|"
                 f"{chunk.get('clock','market_close')}"
                 for chunk in a.get('entry_fills',[]) if D(chunk.get('quantity','0'))>0}
        if a.get('first') and not a.get('entry_fills') and not a.get('legacy_filled_bucket'):
            # An older restored held lot may predate fill-cohort storage.
            # Capture its original saved bucket once, before new bids update
            # entry_key; keep that bucket when newer recorded cohorts appear.
            parts=str(a.get('entry_key','')).split('|')
            if len(parts)>=6 and parts[-3].isdigit() and parts[-4] in ('yes','no'):
                a['legacy_filled_bucket']=f"{parts[-4]}|{price_bucket(D(parts[-3])/100)}|{parts[-2]}|{parts[-1]}"
            else:
                a['legacy_bucket_unknown']=True
        if a.get('legacy_filled_bucket'):buckets.add(a['legacy_filled_bucket'])
        return buckets

    def research_inventory_cap(self):
        # Saved historical sizes cannot silently enlarge the one-contract
        # collector's five-entry inventory guard.
        return min(D(self.contracts),D(1))*D(str(self.profile.get('paper_repeat_inventory_multiplier',5)))

    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        # Attribution remains based on actual fill price/time, never submission.
        favorite_timing.fill(self,order,quantity,entry_key)
        if a and order.action=='buy':
            a['first']=True
            if a.get('entry_policy')=='favorites-paper-data-v3':
                filled=(a.get('pending_buckets') or {}).get(order.id)
                if filled is None:filled=self.research_bucket(order.ticker,order.side,order.price,order.created)
                active,buckets=self.active_buckets(order.ticker,a)
                # A second distinct 5c x time-band bid must survive another
                # bucket filling; duplicate bids inside the same bucket do not.
                for other in active:
                    if other.id!=order.id and buckets.get(other.id)==filled:self.e.cancel(other.id)
                return
        self.e.cancel_buys(order.ticker)
        if a and order.action=='sell':self.finish_data_window(order.ticker,a)

    def retain_partial_entry(self,ticker,m,a,lots):
        active,_=self.active_buckets(ticker,a)
        if not active:return
        valid=(self.enabled and self.entry_allowed(m,self.e.now) and self.entry_ready(ticker)
               and m['close']-self.e.now>60 and not a.get('exit_reason'))
        q=self.entry_quote(ticker,a['side']) if valid else None
        if not q:
            self.e.cancel_buys(ticker)
            return
        inventory=sum((l.quantity for l in lots if l.side==a['side']),ZERO)
        ceiling=self.research_inventory_cap()
        permitted=ceiling-inventory
        # Preserve older valid bucket bids through a price/time transition, but
        # fail closed on quantity, direction, or market-cap violations.
        for order in sorted(active,key=lambda o:(o.created,o.id)):
            if (order.side!=a['side'] or order.remaining>D(1) or order.price>D('.95')
                    or order.price<D('.70') or order.remaining>permitted
                    or order.price>=self.e.books[ticker].ask(order.side)):
                self.e.cancel(order.id)
            else:
                permitted-=order.remaining
        canceling={ident for _,_,action,ident in self.e.pending if action=='cancel'}
        for order in active:
            if order.id not in canceling:order.expiry=min(self.e.now+30,self.entry_deadline(m,self.e.now))
    def safety_cancel(self,ticker):pass
    def exit_allowed(self,order):return not self.hold_only and self.e.now<self.e.markets[order.ticker]['close']
    def entry_quote(self,ticker,side,max_price=None):
        return quote(self.e,self.profile,self.contracts,ticker,side,self.exit_evidence.cells,
            None if self.profile.get('paper_exploration',True) is not False else max_price)
    def cancel_entry(self,ticker,reason):
        self.e.cancel_buys(ticker)
        self.last_reason=reason
    def submit_entry(self,ticker,a,q,allow_parallel=False):
        # Distinct-bucket paper probes may coexist; other modes still never
        # stack an order on an outstanding cancellation or partial fill.
        if not allow_parallel and any(o.ticker==ticker and o.status in ('pending','resting') for o in self.e.orders.values()):return None
        expiry=min(self.e.now+30,a['entry_deadline'])
        if expiry<=self.e.now+self.e.latency:return
        if not a.get('first') and (not a.get('data_window') or not any(
                o.ticker==ticker and o.action=='buy' and o.status in ('pending','resting')
                for o in self.e.orders.values())):
            # Preserve a shared verification window while parallel bids coexist,
            # but start a fresh window after an earlier unfilled/gapped bid exits.
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
            f"{q['quantity']:f}-contract targeted statistical learning probe at {q['price']*100:.0f}¢ · not a proven edge" if q['mode']=='statistics_exploration' else
            f"Value-qualified maker at {q['price']*100:.0f}¢ · {q['estimate']['samples']} settled events")
        ident=self.e.place(ticker,a['side'],'buy',q['quantity'],q['price'],maker=True,expiry=expiry)
        request=self.e.orders[ident]
        bucket=self.research_bucket(ticker,a['side'],q['price'])
        if q['mode']=='paper_exploration' and request.status in ('pending','resting'):
            a.setdefault('pending_buckets',{})[ident]=bucket
        self.e.log('FAVORITE_ENTRY_DECISION',ticker=ticker,order_id=ident,reason=self.last_reason,details=json.dumps(dict(
            mode=q['mode'],policy=q['policy'],quantity=str(q['quantity']),price=str(q['price']),execution_status=request.status,research_bucket=bucket,
            event_ticker=self.e.markets[ticker].get('event_ticker',ticker),estimate=q['estimate'],ceiling=q['ceiling'],execution_model=request.execution_model,
            worker_delay_ms=request.worker_delay_seconds*1000,decision_at=request.decision_at,arrival_at=request.arrives)))
        if request.status not in ('pending','resting'):
            # A rejected paper order is not a resting bid or collected sample.
            return None
        if q['mode']=='paper_exploration':
            print(json.dumps(dict(event='favorite_paper_entry',ticker=ticker,order_id=ident,quantity=str(q['quantity']),
                price=str(q['price']),policy=q['policy'],research_bucket=bucket,
                event_ticker=self.e.markets[ticker].get('event_ticker',ticker),maker=True,execution_model=request.execution_model,
                worker_delay_ms=request.worker_delay_seconds*1000,arrival_at=request.arrives,real_orders_enabled=False)),flush=True)
        return ident

    def offer_distinct_bucket(self,ticker,m,a,lots,q,active=None,pending=None):
        if q['mode']!='paper_exploration':return 'duplicate'
        bucket=self.research_bucket(ticker,a['side'],q['price'])
        if a.get('first') and not a.get('entry_fills'):self.filled_buckets(a)
        if a.get('legacy_bucket_unknown'):
            a['last_repeat_suppression']=dict(reason='legacy_filled_bucket_unknown',signal=bucket,at=self.e.now)
            return 'blocked'
        if active is None or pending is None:active,pending=self.active_buckets(ticker,a)
        if bucket in pending.values() or bucket in self.filled_buckets(a):
            if bucket!=a.get('last_duplicate_bucket') or self.e.now-a.get('last_duplicate_log_at',0)>=10:
                a['repeat_duplicate_suppressed']=a.get('repeat_duplicate_suppressed',0)+1
                a['last_duplicate_bucket']=bucket;a['last_duplicate_log_at']=self.e.now
            return 'duplicate'
        if bucket!=a.get('last_qualified_bucket'):
            a['repeat_opportunities_detected']=a.get('repeat_opportunities_detected',0)+1
            a['last_qualified_bucket']=bucket
        inventory=sum((l.quantity for l in lots if l.side==a['side']),ZERO)
        exposure=inventory+sum((o.remaining for o in active),ZERO)
        maximum=self.research_inventory_cap()
        if exposure+q['quantity']>maximum:
            if bucket!=a.get('last_risk_blocked_bucket'):
                a['repeat_risk_suppressed']=a.get('repeat_risk_suppressed',0)+1
                a['last_risk_blocked_bucket']=bucket
            a['last_repeat_suppression']=dict(reason='inventory_plus_resting_cap',signal=bucket,at=self.e.now)
            return 'blocked'
        # The quote routine credits this market's resting reserves to allow
        # replacement pricing. Distinct *additional* bids cannot spend those
        # funds twice: only actually unreserved cash can collateralize one.
        unreserved=self.e.available()
        required=q['quantity']*q['price']+q['fee']
        if required>unreserved:
            a['last_repeat_suppression']=dict(reason='insufficient_unreserved_cash',signal=bucket,
                at=self.e.now,available=str(unreserved),required=str(required))
            return 'blocked'
        if self.e.now-a.get('last_submit',0)<10:return 'blocked'
        active_ids={order.id for order in active}
        if any(action=='cancel' and ident in active_ids for _,_,action,ident in self.e.pending):
            # Never create new exposure before a submitted cancellation is
            # acknowledged, even if the next eligible bucket is different.
            return 'blocked'
        a['entry_deadline']=self.entry_deadline(m,self.e.now)
        a['target_inventory']=str(exposure+q['quantity'])
        order_id=self.submit_entry(ticker,a,q,allow_parallel=True)
        if order_id is None:return 'blocked'
        a['last_repeat_signal']=bucket
        a['repeat_qualified']=True
        a['repeat_entries']=a.get('repeat_entries',0)+1
        self.e.log('FAVORITE_REPEAT_OPPORTUNITY',ticker=ticker,details=json.dumps(dict(
            opportunity_key=bucket,repeat_entries=a['repeat_entries'],
            inventory_before=str(inventory),outstanding_before=str(exposure-inventory),max_inventory=str(maximum),
            price=str(q['price']),quantity=str(q['quantity']),entries_attempted=a['repeat_entries'],
            opportunities_detected=a['repeat_opportunities_detected'])))
        return 'submitted'

    def repeat_data_entry(self,ticker,m,a,lots):
        """Allow a new 5-cent / remaining-time research bucket even with older bids.

        A filled cohort counts only after authoritative settlement; multiple
        bids/positions on one event never multiply global outcome observations.
        """
        if self.profile.get('paper_exploration',True) is False or a.get('entry_policy')!='favorites-paper-data-v3':
            return
        if a.get('exit_reason') or not self.enabled or m.get('entry_parked'):
            a['repeat_qualified']=False;return
        if not self.entry_allowed(m,self.e.now) or not self.entry_ready(ticker) or m['close']-self.e.now<=60:
            a['repeat_qualified']=False;return
        if self.entry_deadline(m,self.e.now)<=self.e.now+self.e.latency:
            a['repeat_qualified']=False;return
        q=self.entry_quote(ticker,a['side'])
        if not q:
            a['repeat_qualified']=False;return
        self.offer_distinct_bucket(ticker,m,a,lots,q)

    def entry_allowed(self,m,now):
        if self.profile.get('retired'):return False
        if weather_window.is_daily(m) or self.profile.get('asset')=='weather_daily':
            return weather_window.entry_allowed(m,now)
        return not m.get('sports') or (m.get('sports_live') is True and
            m.get('sports_start',float('inf'))<=now<m.get('sports_verified_until',0) and
            60<m.get('sports_expected_end',0)-now<=self.profile.get('late_game_hours',2)*3600)
    def entry_deadline(self,m,now):
        deadline=m['close']-60
        if weather_window.is_daily(m):
            end=weather_window.entry_end(m)
            if end is None:return now
            deadline=min(deadline,end-60)
        if m.get('sports'):deadline=min(deadline,m.get('sports_verified_until',now),m.get('sports_expected_end',now)-60)
        return deadline
    def entry_order_allowed(self,order):
        m=self.e.markets[order.ticker]
        return not weather_window.is_daily(m) or weather_window.entry_allowed(m,self.e.now)

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
            if weather_window.is_daily(m) and not weather_window.entry_allowed(m,now):
                self.e.cancel_buys(ticker)
                self.last_reason='Daily weather: entries only in the city’s final two hours; official settlement may follow later'
            if self.hold_only:
                for order in self.e.orders.values():
                    if order.ticker==ticker and order.action=='sell' and order.status in ('pending','resting'):
                        self.e.cancel(order.id)
                if a and a.get('exit_reason'):
                    a['legacy_exit_reason']=a.pop('exit_reason')
            if m.get('paid'):
                if not a or a.get('recorded'):continue
                s=self.e.wallet.stat(ticker)
                favorite_timing.settle(self,ticker,observe)
                trial_valid=self.trial_valid(ticker,a)
                if trial_valid and a['first'] and m.get('yes_payout_confirmed') in ('0','1'):
                    payout=int(m['yes_payout_confirmed']==('1' if a['side']=='yes' else '0'))
                    if not self.hold_only:
                        for key in a.get('risk_observations',{}):self.exit_evidence.observe(key,payout)
                    if a.get('entry_key') and not a.get('entry_fills'):observe(self.exit_evidence.cells,a['entry_key'],m.get('event_ticker',ticker),payout,observed_at=self.e.now)
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
                if not self.hold_only and lots and self.e.book_fresh(ticker):
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
                chooser=getattr(self,'choose_entry_side',None)
                if chooser:side=chooser(ticker,quotes) or side
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
            # A previously resting maker bid can become marketable as the book
            # moves. Cancel crossed bids before considering another bucket; a
            # parallel entry must not bypass the post-only safety requirement.
            crossed=[o for o in active if o.action=='buy' and
                     o.price>=self.e.books[ticker].ask(o.side)]
            if crossed:
                for order in crossed:self.e.cancel(order.id)
                self.last_reason='Cancel crossed maker bid before renewed research entry'
                a['retry_at']=now+1
                continue
            compare=active
            if a.get('entry_policy')=='favorites-paper-data-v3' and active:
                # Only compare the current candidate with bids in its own 5c
                # / time bucket. Old distinct-bucket queues are not replacements.
                _,buckets=self.active_buckets(ticker,a,active)
                current=self.research_bucket(ticker,side,q['price'])
                compare=[order for order in active if buckets.get(order.id)==current]
                status=self.offer_distinct_bucket(ticker,m,a,[],q,active=active,pending=buckets)
                if status in ('blocked','submitted'):
                    canceling={ident for _,_,action,ident in self.e.pending if action=='cancel'}
                    for order in active:
                        if order.id not in canceling:order.expiry=min(now+30,deadline)
                    continue
            # Within the same research bucket, a more competitive quote is not a
            # new sample. Preserve the already-valid maker queue position instead
            # of paying cancellation/reentry churn for a 2c price improvement.
            reprice_for_data=(q['mode']=='paper_exploration' and
                a.get('entry_policy')!='favorites-paper-data-v3' and now-a.get('last_submit',0)>=10)
            if any(o.price>q['price'] or o.quantity!=q['quantity'] or
                    (reprice_for_data and q['price']-o.price>=D('.02')) or
                    (a.get('entry_mode')=='calibrated_maker' and q['mode']=='paper_exploration') for o in compare):
                if a.get('entry_policy')=='favorites-paper-data-v3':
                    for order in compare:self.e.cancel(order.id)
                    self.last_reason='Maker entry refreshed within current research bucket'
                else:
                    self.cancel_entry(ticker,'Maker entry refreshed: current price, configured size or fee conditions changed')
                a['retry_at']=now+1
            elif active:
                # Renew only verified, non-canceling orders while retaining their
                # arrival timestamp and original maker queue position.
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

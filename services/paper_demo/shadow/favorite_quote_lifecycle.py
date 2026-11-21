"""Ephemeral, bounded diagnostics for regular Favorites paper maker bids only.

Observes the existing order journal; never changes prices, orders, fills or cash.
A quote or partial fill is not an independent settled market observation.
"""
from collections import Counter, OrderedDict, deque
from math import ceil, isfinite
import time

WINDOW_SECONDS=300
MAX_OPEN=2048
MAX_HISTORY=4096
EVENTS={'ORDER_SUBMITTED','ORDER_REJECTED','MAKER_RESTING','CANCEL_SUBMITTED','CANCELLED','EXPIRED','FILL'}

def _percentile(values, proportion):
    if not values:return None
    a=sorted(values)
    return round(a[max(0,ceil(len(a)*proportion)-1)],3)

class FavoriteQuoteLifecycle:
    def __init__(self,now=None):
        self.started=time.time() if now is None else float(now)
        self.open=OrderedDict()
        self.history=deque(maxlen=MAX_HISTORY)
        self.restored=self.evicted=self.overwritten=self.unlinked=0

    def _record(self,at,kind,row,duration=None):
        if len(self.history)==MAX_HISTORY:self.overwritten+=1
        self.history.append((float(at),kind,row['ticker'],row['event'],duration))

    def _start(self,order,market,restored=False):
        current=self.open.get(order.id)
        if current is not None:return current
        if len(self.open)>=MAX_OPEN:
            self.open.popitem(last=False)
            self.evicted+=1
        row=dict(ticker=order.ticker,event=(market or {}).get('event_ticker') or None,
                 created=float(order.created),
                 resting=(float(order.arrives) if restored and order.status=='resting' else None),
                 filled=False,cancel=None,restored=restored)
        self.open[order.id]=row
        if restored:self.restored+=1
        return row

    def seed_restored(self,orders,markets):
        for o in orders:
            if o.maker and o.action=='buy' and o.status in ('pending','resting'):
                self._start(o,markets.get(o.ticker,{}),restored=True)

    def observe(self,kind,order,at,market=None,reason=None):
        if kind not in EVENTS or not order.maker or order.action!='buy':return
        if not isinstance(at,(int,float)) or not isfinite(at):return
        row=self.open.get(order.id)
        if kind=='ORDER_SUBMITTED':
            if row is None:
                row=self._start(order,market)
                self._record(at,'submitted',row)
            return
        if kind=='ORDER_REJECTED':
            if row is None:
                row=dict(ticker=order.ticker,event=(market or {}).get('event_ticker') or None)
            self._record(at,'rejected',row)
            self.open.pop(order.id,None)
            return
        if row is None:
            self.unlinked+=1
            return
        if kind=='MAKER_RESTING':
            if row['resting'] is None:
                row['resting']=float(at)
                self._record(at,'rested',row)
        elif kind=='CANCEL_SUBMITTED':
            if row['cancel'] is None:
                row['cancel']=float(at)
                self._record(at,'cancel_requested',row)
        elif kind=='FILL':
            self._record(at,'fill_events',row)
            if not row['filled']:
                row['filled']=True
                wait=max(0.,at-row['resting']) if row['resting'] is not None else None
                self._record(at,'first_filled',row,wait)
            if not order.remaining:self._finish(order.id,row,'filled_complete',at)
        elif kind in ('CANCELLED','EXPIRED'):
            self._finish(order.id,row,
                         ('cancelled' if kind=='CANCELLED' else 'expired')+
                         ('_after_partial_fill' if row['filled'] else '_without_fill'),at)

    def _finish(self,ident,row,result,at):
        age=max(0.,at-row['resting']) if row['resting'] is not None else None
        self._record(at,result,row,age)
        if row['resting'] is None:self._record(at,'terminal_before_rest',row)
        if result.startswith('cancelled') and row['cancel'] is not None:
            self._record(at,'cancel_ack',row,max(0.,at-row['cancel']))
        self.open.pop(ident,None)

    def snapshot(self,now=None,errors=0):
        now=time.time() if now is None else float(now)
        while self.history and self.history[0][0]<now-WINDOW_SECONDS:self.history.popleft()
        events=[r for r in self.history if r[0]<=now]
        counts=Counter(r[1] for r in events)
        submitted=[r for r in events if r[1]=='submitted']
        first_filled=[r for r in events if r[1]=='first_filled']
        terminal=[r[4] for r in events if
                  r[1].startswith(('cancelled_','expired_')) or r[1]=='filled_complete']
        open_age=[max(0.,now-r['resting']) for r in self.open.values() if r['resting'] is not None]
        return dict(window_seconds=WINDOW_SECONDS,telemetry_started_at=self.started,
                    coverage='read-only since worker start; outcomes unconfirmed',
                    submitted_orders=counts['submitted'],
                    submitted_tickers=len({r[2] for r in submitted}),
                    submitted_events=len({r[3] for r in submitted if r[3]}),
                    submitted_missing_event_id=sum(not r[3] for r in submitted),
                    first_filled_orders=counts['first_filled'],
                    first_filled_events=len({r[3] for r in first_filled if r[3]}),
                    first_filled_missing_event_id=sum(not r[3] for r in first_filled),
                    fill_events=counts['fill_events'],
                    completely_filled_orders=counts['filled_complete'],
                    cancelled_without_fill=counts['cancelled_without_fill'],
                    cancelled_after_partial_fill=counts['cancelled_after_partial_fill'],
                    expired_without_fill=counts['expired_without_fill'],
                    expired_after_partial_fill=counts['expired_after_partial_fill'],
                    rejected_orders=counts['rejected'],
                    terminal_before_rest=counts['terminal_before_rest'],
                    open_orders=len(self.open),
                    open_resting=sum(r['resting'] is not None for r in self.open.values()),
                    open_after_partial_fill=sum(r['filled'] for r in self.open.values()),
                    open_restored=sum(r['restored'] for r in self.open.values()),
                    pending_cancel_ack=sum(r['cancel'] is not None for r in self.open.values()),
                    open_rest_age_p50_seconds=_percentile(open_age,.50),
                    open_rest_age_p90_seconds=_percentile(open_age,.90),
                    terminal_rest_p50_seconds=_percentile([x for x in terminal if x is not None],.50),
                    terminal_rest_p90_seconds=_percentile([x for x in terminal if x is not None],.90),
                    first_fill_wait_p50_seconds=_percentile([r[4] for r in first_filled if r[4] is not None],.50),
                    first_fill_wait_p90_seconds=_percentile([r[4] for r in first_filled if r[4] is not None],.90),
                    cancel_ack_p90_seconds=_percentile([r[4] for r in events if r[1]=='cancel_ack'],.90),
                    restored_seeded_total=self.restored,
                    unlinked_events_total=self.unlinked,evicted_open_total=self.evicted,
                    overwritten_history_total=self.overwritten,observer_errors_total=errors)

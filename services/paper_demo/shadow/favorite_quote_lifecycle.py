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
# Explicit fixed categories bound log size; unknown metadata must not be
# mislabeled as a known 15-minute contract.
MARKET_TYPES=('15m_price','hourly_price','weather','weather_daily','sports','unknown')
REST_BANDS=('under_5s','5_to_30s','30_to_120s','at_least_120s','unknown_not_resting')
# Fixed diagnostic labels; user-supplied strategy strings/IDs never become log keys.
CANCEL_CAUSES=('entry_guard','quote_unavailable','crossed_quote','same_bucket_reprice',
               'partial_guard','redundant_after_fill','daily_window','after_fill',
               'fee_guard','unknown')


def _market_type(market, ticker):
    if not isinstance(market,dict) or not market:
        return 'unknown'
    if market.get('sports'):
        return 'sports'
    if market.get('weather_category') in ('weather','weather_daily'):
        return market['weather_category']
    if market.get('hourly_price'):
        return 'hourly_price'
    # Only the regular Favorites fleet uses this observer; 15m entries have
    # explicit 15M series prefixes even if their normalized market omits
    # category metadata. Do not classify an arbitrary other ticker as 15m.
    series=str(market.get('series_ticker') or ticker.split('-',1)[0])
    return '15m_price' if series.endswith('15M') else 'unknown'


def _rest_band(seconds):
    if seconds is None:return 'unknown_not_resting'
    if seconds<5:return 'under_5s'
    if seconds<30:return '5_to_30s'
    if seconds<120:return '30_to_120s'
    return 'at_least_120s'

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
        self.history.append((float(at),kind,row['ticker'],row['event'],duration,row['market_type']))

    def _start(self,order,market,restored=False):
        current=self.open.get(order.id)
        if current is not None:return current
        if len(self.open)>=MAX_OPEN:
            self.open.popitem(last=False)
            self.evicted+=1
        row=dict(ticker=order.ticker,event=(market or {}).get('event_ticker') or None,
                 market_type=_market_type(market,order.ticker),
                 created=float(order.created),
                 resting=(float(order.arrives) if restored and order.status=='resting' else None),
                 filled=False,cancel=None,restored=restored,cancel_cause=None)
        self.open[order.id]=row
        if restored:self.restored+=1
        return row

    def seed_restored(self,orders,markets):
        for o in orders:
            if o.maker and o.action=='buy' and o.status in ('pending','resting'):
                self._start(o,markets.get(o.ticker,{}),restored=True)

    def note_cancel_cause(self,ident,cause):
        """Attach a fixed, ephemeral *intent* before the normal cancellation.

        Never changes the order, its price, expiry, queue position or audit.
        The actual outcome is counted only after an observed CANCELLED event.
        """
        row=self.open.get(ident)
        if row is not None and row.get('cancel_cause') is None:
            row['cancel_cause']=cause if cause in CANCEL_CAUSES else 'unknown'

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
                row=dict(ticker=order.ticker,event=(market or {}).get('event_ticker') or None,
                         market_type=_market_type(market,order.ticker))
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
            if kind=='CANCELLED' and not row['filled']:
                cause=row.get('cancel_cause')
                if cause is None:
                    # Only known engine guard wording is interpreted; never
                    # log an arbitrary free-form reason from the exchange.
                    cause=('fee_guard' if reason=='Maker entry fee nonzero or unverified'
                           else 'daily_window' if reason=='Entry window closed or not yet open'
                           else 'unknown')
                self._record(at,'cancel_cause:'+cause,row)
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
        # Type-specific counts are measurements of different quote lifecycles,
        # not a causal filled/submitted ratio, and NEVER settled event outcomes.
        by_market_type={}
        for market_type in MARKET_TYPES:
            sliced=[r for r in events if r[5]==market_type]
            open_rows=[r for r in self.open.values() if r['market_type']==market_type]
            if not sliced and not open_rows:continue
            c=Counter(r[1] for r in sliced)
            sub=[r for r in sliced if r[1]=='submitted']
            filled=[r for r in sliced if r[1]=='first_filled']
            cancels=[r for r in sliced if r[1]=='cancelled_without_fill']
            cancel_ages=[r[4] for r in cancels if r[4] is not None]
            fill_ages=[r[4] for r in filled if r[4] is not None]
            bands=Counter(_rest_band(r[4]) for r in cancels)
            cancel_causes={cause:c['cancel_cause:'+cause] for cause in CANCEL_CAUSES
                           if c['cancel_cause:'+cause]}
            opening_ages=[max(0.,now-r['resting']) for r in open_rows if r['resting'] is not None]
            by_market_type[market_type]=dict(
                submitted_orders=c['submitted'],
                submitted_events=len({r[3] for r in sub if r[3]}),
                submitted_missing_event_id=sum(not r[3] for r in sub),
                first_filled_orders=c['first_filled'],
                first_filled_events=len({r[3] for r in filled if r[3]}),
                cancelled_without_fill=c['cancelled_without_fill'],
                unfilled_cancel_causes=cancel_causes,
                cancelled_after_partial_fill=c['cancelled_after_partial_fill'],
                expired_without_fill=c['expired_without_fill'],
                expired_after_partial_fill=c['expired_after_partial_fill'],
                rejected_orders=c['rejected'],
                open_orders=len(open_rows),
                open_resting=sum(r['resting'] is not None for r in open_rows),
                # Right-censored current bids do not count as failures.
                open_rest_age_p50_seconds=_percentile(opening_ages,.5),
                canceled_unfilled_rest_p50_seconds=_percentile(cancel_ages,.5),
                first_fill_rest_p50_seconds=_percentile(fill_ages,.5),
                canceled_unfilled_rest_bands={k:bands[k] for k in REST_BANDS})
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
                    unfilled_cancel_causes={cause:counts['cancel_cause:'+cause]
                        for cause in CANCEL_CAUSES if counts['cancel_cause:'+cause]},
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
                    overwritten_history_total=self.overwritten,observer_errors_total=errors,
                    by_market_type=by_market_type)

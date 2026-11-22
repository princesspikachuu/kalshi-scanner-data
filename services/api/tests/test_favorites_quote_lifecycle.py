"""Regular Favorites maker quote-lifecycle telemetry: no strategy or cash changes."""
import json
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Order
from services.paper_demo.shadow.favorite_quote_lifecycle import FavoriteQuoteLifecycle,MAX_OPEN,MAX_HISTORY
from services.api.tests.test_favorite_maker_entries import MakerEntries


def order(ident,ticker='KXTEST-1',now=1,quantity='1'):
    return Order(ident,ticker,'yes','buy',D(quantity),D('.80'),True,1,
                 now,now+.15,now+30,None,status='pending',remaining=D(quantity))


class FavoriteQuoteLifecycleTests(unittest.TestCase):
    def setup_bot(self):
        e,b,book=MakerEntries().setup_bot()
        tracker=FavoriteQuoteLifecycle(e.now)
        e._favorite_quote_lifecycle=tracker
        return e,b,book,tracker

    def test_partial_fills_count_one_filled_order_not_two_independent_events(self):
        e,b,book,t=self.setup_bot()
        b.step()
        o=next(iter(e.orders.values()))
        e.advance(201)
        e.fill(o,D('.4'),o.price,'TEST')
        e.fill(o,D('.6'),o.price,'TEST')
        snap=t.snapshot(201)
        self.assertEqual(snap['submitted_orders'],1)
        self.assertEqual(snap['fill_events'],2)
        self.assertEqual(snap['first_filled_orders'],1)
        self.assertEqual(snap['first_filled_events'],1)
        self.assertEqual(snap['completely_filled_orders'],1)
        self.assertEqual(snap['open_orders'],0)
        self.assertIsNotNone(snap['first_fill_wait_p50_seconds'])
        self.assertEqual(snap['observer_errors_total'],0)

    def test_cancel_without_fill_and_partial_fill_expiry_are_different(self):
        e,b,book,t=self.setup_bot()
        b.step()
        o=next(iter(e.orders.values()))
        e.advance(201);e.cancel(o.id);e.advance(202)
        snap=t.snapshot(202)
        self.assertEqual(snap['cancelled_without_fill'],1)
        self.assertEqual(snap['fill_events'],0)
        self.assertEqual(snap['terminal_before_rest'],0)
        self.assertIsNotNone(snap['cancel_ack_p90_seconds'])
        p=order('S100',now=205)
        t.observe('ORDER_SUBMITTED',p,205,{'event_ticker':'EV'})
        p.status='resting';t.observe('MAKER_RESTING',p,205.15,{'event_ticker':'EV'})
        p.remaining=D('.6');t.observe('FILL',p,211,{'event_ticker':'EV'})
        p.status='expired';t.observe('EXPIRED',p,236,{'event_ticker':'EV'})
        snap=t.snapshot(236)
        self.assertEqual(snap['expired_after_partial_fill'],1)
        self.assertEqual(snap['first_filled_orders'],1)
        self.assertEqual(snap['completely_filled_orders'],0)


    def test_unfilled_cancel_cause_is_fixed_and_counted_only_after_ack(self):
        t=FavoriteQuoteLifecycle(100)
        market={'event_ticker':'ONE','weather_category':'weather'}
        for i,cause in enumerate(('crossed_quote','same_bucket_reprice',
                                  'free-form private credential secret')):
            o=order('CAUSE'+str(i),ticker='KXTEMP-1',now=101+i*10)
            t.observe('ORDER_SUBMITTED',o,o.created,market)
            o.status='resting'
            t.observe('MAKER_RESTING',o,o.created+.1,market)
            t.note_cancel_cause(o.id,cause)
            t.note_cancel_cause(o.id,'quote_unavailable')  # don't overwrite original
            t.observe('CANCEL_SUBMITTED',o,o.created+1,market)
            self.assertEqual(t.snapshot(o.created+1)['cancelled_without_fill'],i)
            o.status='cancelled'
            t.observe('CANCELLED',o,o.created+2,market)
        s=t.snapshot(150)
        reasons={'crossed_quote':1,'same_bucket_reprice':1,'unknown':1}
        self.assertEqual(s['unfilled_cancel_causes'],reasons)
        self.assertEqual(s['by_market_type']['weather']['unfilled_cancel_causes'],
                         reasons)
        self.assertEqual(s['cancelled_without_fill'],3)
        self.assertNotIn('private credential',json.dumps(s))
        self.assertNotIn('CAUSE',json.dumps(s))

    def test_partial_fill_and_expiry_not_mistaken_for_unfilled_cancel_causes(self):
        t=FavoriteQuoteLifecycle(100)
        market={'event_ticker':'EVENT','hourly_price':True}
        partial=order('PARTIAL',now=101)
        t.observe('ORDER_SUBMITTED',partial,101,market)
        t.observe('MAKER_RESTING',partial,101.1,market)
        t.note_cancel_cause(partial.id,'crossed_quote')
        partial.remaining=D('.5')
        t.observe('FILL',partial,103,market)
        partial.status='cancelled'
        t.observe('CANCELLED',partial,104,market)
        expiry=order('EXPIRE',now=105)
        t.observe('ORDER_SUBMITTED',expiry,105,market)
        t.observe('MAKER_RESTING',expiry,105.1,market)
        expiry.status='expired'
        t.observe('EXPIRED',expiry,135,market)
        s=t.snapshot(140)
        self.assertEqual(s['cancelled_after_partial_fill'],1)
        self.assertEqual(s['expired_without_fill'],1)
        self.assertEqual(s['unfilled_cancel_causes'],{})

    def test_engine_guard_cancel_is_classified_without_raw_reason_leak(self):
        t=FavoriteQuoteLifecycle(100)
        for i,reason in enumerate((
                'Maker entry fee nonzero or unverified',
                'Entry window closed or not yet open',
                'private account secret unknown cause')):
            p=order('GUARD'+str(i),now=101+i)
            t.observe('ORDER_SUBMITTED',p,p.created,{'event_ticker':'E'})
            p.status='cancelled'
            t.observe('CANCELLED',p,p.created+.5,{},reason=reason)
        s=t.snapshot(110)
        self.assertEqual(s['unfilled_cancel_causes'],
                         {'fee_guard':1,'daily_window':1,'unknown':1})
        self.assertNotIn('private account',json.dumps(s))

    def test_regular_favorites_strategy_cancel_only_changes_telemetry(self):
        e,b,book,t=self.setup_bot()
        b.step()
        o=next(iter(e.orders.values()))
        e.advance(201)
        before_cash=e.wallet.cash
        before_count=len(e.orders)
        b.cancel_entry(o.ticker,'Waiting for verified book',category='entry_guard')
        e.advance(202)
        self.assertEqual(o.status,'cancelled')
        self.assertEqual(e.wallet.cash,before_cash)
        self.assertEqual(len(e.orders),before_count)
        self.assertEqual(t.snapshot(202)['unfilled_cancel_causes'],
                         {'entry_guard':1})

    def test_cancel_telemetry_exception_cannot_block_original_order_cancel(self):
        e,b,book,t=self.setup_bot()
        b.step()
        o=next(iter(e.orders.values()))
        e.advance(201)
        t.note_cancel_cause=Mock(side_effect=RuntimeError('private diagnostic issue'))
        b.cancel_entry(o.ticker,'No quote',category='quote_unavailable')
        e.advance(202)
        self.assertEqual(o.status,'cancelled')
        self.assertGreaterEqual(e._favorite_quote_lifecycle_errors,1)

    def test_outstanding_resting_orders_are_right_censored(self):
        e,b,book,t=self.setup_bot()
        b.step();e.advance(201)
        s=t.snapshot(210)
        self.assertEqual(s['open_orders'],1)
        self.assertEqual(s['open_resting'],1)
        self.assertEqual(s['cancelled_without_fill'],0)
        self.assertEqual(s['expired_without_fill'],0)
        self.assertGreater(s['open_rest_age_p50_seconds'],8)
        self.assertIsNone(s['terminal_rest_p50_seconds'])

    def test_repeat_quotes_are_not_distinct_event_outcomes(self):
        t=FavoriteQuoteLifecycle(100)
        for i in range(3):
            o=order('S'+str(i),ticker='TICKER-'+str(i),now=100+i)
            t.observe('ORDER_SUBMITTED',o,100+i,{'event_ticker':'ONE'})
        s=t.snapshot(105)
        self.assertEqual(s['submitted_orders'],3)
        self.assertEqual(s['submitted_tickers'],3)
        self.assertEqual(s['submitted_events'],1)
        self.assertEqual(s['first_filled_orders'],0)

    def test_missing_event_ticker_never_fabricates_independent_event(self):
        t=FavoriteQuoteLifecycle(100)
        o=order('SNOEVENT',ticker='NOEVENT-1',now=100)
        t.observe('ORDER_SUBMITTED',o,100,{})
        s=t.snapshot(101)
        self.assertEqual(s['submitted_orders'],1)
        self.assertEqual(s['submitted_tickers'],1)
        self.assertEqual(s['submitted_events'],0)
        self.assertEqual(s['submitted_missing_event_id'],1)

    def test_restored_orders_do_not_invent_new_submissions(self):
        e,b,book=MakerEntries().setup_bot()
        b.step();e.advance(201)
        t=FavoriteQuoteLifecycle(201)
        t.seed_restored(e.orders.values(),e.markets)
        s=t.snapshot(202)
        self.assertEqual(s['submitted_orders'],0)
        self.assertEqual(s['open_orders'],1)
        self.assertEqual(s['open_restored'],1)
        o=next(iter(e.orders.values()))
        t.observe('CANCELLED',o,203,e.markets[o.ticker])
        self.assertEqual(t.snapshot(203)['cancelled_without_fill'],1)

    def test_rejected_order_can_be_counted_without_prior_submit(self):
        t=FavoriteQuoteLifecycle(50)
        o=order('S4',now=51);o.status='rejected'
        t.observe('ORDER_REJECTED',o,51,{'event_ticker':'E'})
        s=t.snapshot(51)
        self.assertEqual(s['rejected_orders'],1)
        self.assertEqual(s['submitted_orders'],0)
        self.assertEqual(s['open_orders'],0)

    def test_market_type_mapping_is_metadata_grounded_and_unknown_is_not_fabricated(self):
        from services.paper_demo.shadow.favorite_quote_lifecycle import _market_type
        self.assertEqual(_market_type({'weather_category':'weather'},'X'),'weather')
        self.assertEqual(_market_type({'weather_category':'weather_daily'},'X'),'weather_daily')
        self.assertEqual(_market_type({'sports':True},'X'),'sports')
        self.assertEqual(_market_type({'hourly_price':True},'X'),'hourly_price')
        self.assertEqual(_market_type({'close':900},'KXBTC15M-26NOV'),'15m_price')
        self.assertEqual(_market_type({'series_ticker':'KXGOLD15M'},'X'),'15m_price')
        self.assertEqual(_market_type({'close':900},'KXUNKNOWN-1'),'unknown')
        self.assertEqual(_market_type({},'KXBTC15M-1'),'unknown')

    def test_cancellation_rest_duration_bands_and_event_dedup_by_market_type(self):
        from services.paper_demo.shadow.favorite_quote_lifecycle import REST_BANDS
        t=FavoriteQuoteLifecycle(100)
        # Multiple quotes for the same venue event are NOT new independent
        # settlements, even if their resting lifetimes differ.
        for i,seconds in enumerate((2,10,60,130)):
            o=order('S-weather-'+str(i),ticker='KXTEMP-1',now=101)
            market={'event_ticker':'WEATHER-EVENT','weather_category':'weather'}
            t.observe('ORDER_SUBMITTED',o,101,market)
            o.status='resting';t.observe('MAKER_RESTING',o,101.1,market)
            o.status='cancelled';t.observe('CANCELLED',o,101.1+seconds,market)
        s=t.snapshot(250)
        w=s['by_market_type']['weather']
        self.assertEqual(w['submitted_orders'],4)
        self.assertEqual(w['submitted_events'],1)
        self.assertEqual(w['cancelled_without_fill'],4)
        self.assertEqual(w['canceled_unfilled_rest_p50_seconds'],10)
        self.assertEqual(w['canceled_unfilled_rest_bands'],
                         dict(zip(REST_BANDS,(1,1,1,1,0))))
        self.assertEqual(w['first_filled_orders'],0)
        self.assertEqual(w['open_orders'],0)
        self.assertEqual(s['submitted_events'],1)
        self.assertEqual(s['cancelled_without_fill'],4)

    def test_fills_open_orders_and_missing_event_ids_split_by_category(self):
        t=FavoriteQuoteLifecycle(200)
        event='BTC-ONE'
        market={'event_ticker':event,'close':1000,'series_ticker':'KXBTC15M'}
        for i in range(2):
            o=order('SF'+str(i),ticker='KXBTC15M-'+str(i),now=201)
            t.observe('ORDER_SUBMITTED',o,201,market)
            o.status='resting';t.observe('MAKER_RESTING',o,201.15,market)
            o.remaining=D(0);o.status='filled'
            t.observe('FILL',o,231,market)
        missing=order('SPENDING',ticker='KXTEMPD-1',now=211)
        other={'weather_category':'weather_daily'}  # deliberately no event_ticker
        t.observe('ORDER_SUBMITTED',missing,211,other)
        missing.status='resting';t.observe('MAKER_RESTING',missing,211.15,other)
        s=t.snapshot(235)
        btc=s['by_market_type']['15m_price']
        daily=s['by_market_type']['weather_daily']
        self.assertEqual(btc['first_filled_orders'],2)
        self.assertEqual(btc['first_filled_events'],1)
        self.assertEqual(btc['submitted_events'],1)
        self.assertEqual(s['first_filled_events'],1)
        self.assertEqual(daily['open_orders'],1)
        self.assertEqual(daily['open_resting'],1)
        self.assertEqual(daily['submitted_events'],0)
        self.assertEqual(daily['submitted_missing_event_id'],1)
        self.assertEqual(daily['cancelled_without_fill'],0)
        self.assertGreater(daily['open_rest_age_p50_seconds'],20)

    def test_empty_type_and_old_history_omit_stale_rows(self):
        t=FavoriteQuoteLifecycle(100)
        o=order('S-SHORT',ticker='KXTEST-1',now=100)
        t.observe('ORDER_SUBMITTED',o,100,{})
        self.assertIn('unknown',t.snapshot(101)['by_market_type'])
        self.assertNotIn('sports',t.snapshot(101)['by_market_type'])
        self.assertEqual(t.snapshot(401)['by_market_type']['unknown']['open_orders'],1)
        o.status='cancelled';t.observe('CANCELLED',o,401,{})
        self.assertEqual(t.snapshot(702)['by_market_type'],{})

    def test_observer_failure_never_interrupts_engine_audit_or_order(self):
        e,b,book,t=self.setup_bot()
        broken=Mock()
        broken.observe.side_effect=RuntimeError('diagnostics unavailable')
        e._favorite_quote_lifecycle=broken
        b.step()
        self.assertEqual(len(e.orders),1)
        self.assertEqual(e._favorite_quote_lifecycle_errors,1)
        self.assertTrue(any(kind=='ORDER_SUBMITTED' for kind,_ in e.audit.events))

    def test_hard_memory_bounds_and_old_events_expire(self):
        t=FavoriteQuoteLifecycle(0)
        for i in range(MAX_OPEN+1):
            o=order('S'+str(i),now=i)
            t.observe('ORDER_SUBMITTED',o,i,{'event_ticker':'E'})
        self.assertEqual(len(t.open),MAX_OPEN)
        self.assertEqual(t.evicted,1)
        self.assertLessEqual(len(t.history),MAX_HISTORY)
        s=t.snapshot(MAX_OPEN+2)
        self.assertLessEqual(s['submitted_orders'],301)
        self.assertGreater(s['submitted_orders'],0)
        self.assertEqual(t.snapshot(MAX_OPEN+400)['submitted_orders'],0)

if __name__=='__main__':
    unittest.main()

"""Regular Favorites maker quote-lifecycle telemetry: no strategy or cash changes."""
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

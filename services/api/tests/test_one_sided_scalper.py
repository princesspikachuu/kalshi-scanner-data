"""Live one-sided books must not reuse cached quotes or restart trading."""
import unittest
from decimal import Decimal as D
from services.api.tests import test_scalper as scalper_fixture
from services.api.tests import test_market_maker as maker_fixture
T=scalper_fixture.T

class OneSidedScalperTests(unittest.TestCase):
    setup_bot=scalper_fixture.ScalperTests.setup_bot
    tick=scalper_fixture.ScalperTests.tick
    warm=scalper_fixture.ScalperTests.warm
    fill_entry=scalper_fixture.ScalperTests.fill_entry
    def test_cached_features_reject_missing_live_bid_or_ask(self):
        for removed in ('yes','no'):
            e,b=self.setup_bot();self.warm(e,b)
            self.assertIsNotNone(b.features(T,'yes'))
            e.books[T].levels[removed].clear()
            for side in ('yes','no'):self.assertIsNone(b.features(T,side))
            self.assertEqual(e.wallet.inventory(T,'yes'),0)
    def test_unfilled_entry_cancels_safely_and_releases_reservation_after_ack(self):
        for removed in ('yes','no'):
            e,b=self.setup_bot();self.warm(e,b)
            o=next(iter(e.orders.values()));e.books[T].at=208.2;e.advance(208.2)
            reserved=o.reserved;self.assertGreater(reserved,0)
            e.books[T].levels[removed].clear()
            b.step(T)
            self.assertTrue(any(item[2]=='cancel' for item in e.pending))
            self.assertEqual(o.reserved,reserved)
            e.books[T].at=208.4;e.advance(208.4);b.step(T)
            self.assertEqual(o.status,'cancelled');self.assertEqual(o.reserved,0)
            self.assertEqual(e.available(),D(1000));self.assertFalse(e.wallet.lots)
    def test_empty_book_never_creates_a_replacement(self):
        e,b=self.setup_bot();self.warm(e,b);o=next(iter(e.orders.values()))
        e.books[T].at=208.2;e.advance(208.2)
        e.books[T].levels['yes'].clear();e.books[T].levels['no'].clear()
        b.step(T);e.books[T].at=209;e.advance(209);b.step(T)
        self.assertEqual(len(e.orders),1);self.assertEqual(o.status,'cancelled')
    def test_missing_held_bid_waits_for_real_liquidation_liquidity(self):
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
        e.books[T].levels['yes'].clear();e.books[T].at=209;e.advance(209);b.step(T)
        self.assertEqual(e.wallet.inventory(T,'yes'),5)
        self.assertFalse(any(o.action=='sell' for o in e.orders.values()))
    def test_market_maker_inherits_safe_entry_cancellation(self):
        fixture=maker_fixture.MakerTests();e,b,p=fixture.bot();o=next(iter(e.orders.values()))
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        e.books[T].levels[o.side].clear();b.step(T)
        e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
        self.assertEqual(o.status,'cancelled');self.assertEqual(e.available(),D(1000))
        self.assertFalse(e.wallet.lots)

"""Paper collection uses configured size and samples weak/unknown-value states."""
import unittest,json
from decimal import Decimal as D
from services.api.tests import test_favorite_maker_entries as fixture
from services.paper_demo.shadow.core import FeePolicy
from services.paper_demo.shadow.hourly import favorite_bid

class DataMode(unittest.TestCase):
    def test_scanner_includes_a_competitive_seventy_cent_maker_quote(self):
        self.assertEqual(favorite_bid(dict(yes_bid_dollars='.69',no_bid_dollars='.29')),D('.70'))
        self.assertIsNone(favorite_bid(dict(yes_bid_dollars='.69',no_bid_dollars='.30')))
        self.assertEqual(favorite_bid(dict(yes_bid=79,no_bid=19)),D('.80'))

    def test_weak_observed_outcomes_do_not_stop_paper_sampling(self):
        e,b,_=fixture.MakerEntries().setup_bot()
        key=fixture.MakerEntries().seed(b,100,10);b.step()
        o=next(iter(e.orders.values()));a=b.attempts[o.ticker]
        self.assertEqual(o.quantity,D(10));self.assertTrue(o.maker)
        self.assertLess(a['entry_estimate']['lower'],float(o.price))
        self.assertEqual(a['entry_policy'],'favorites-paper-data-v3')
        self.assertEqual(a['entry_key'],key)
        self.assertEqual(e.wallet.cash,D(1000));self.assertFalse(e.wallet.lots)

    def test_configured_size_above_old_five_percent_cap_is_respected(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.contracts=D(100);b.step()
        o=next(iter(e.orders.values()));self.assertEqual(o.quantity,D(100))
        self.assertEqual(o.reserved,D(80));self.assertEqual(e.available(),D(920))

    def test_available_cash_and_real_series_fees_still_bound_simulated_orders(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.contracts=D(10000)
        e.fees[fixture.MakerEntries.ticker]=FeePolicy(D(1),D(1));b.step()
        o=next(iter(e.orders.values()))
        self.assertGreater(o.quantity,D(1));self.assertLessEqual(o.reserved,e.wallet.cash)
        self.assertGreater(e.fees[o.ticker].charge(o.quantity,o.price,True),0)

    def test_paper_quotes_follow_current_bid_after_minimum_rest(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        old=next(iter(e.orders.values()));self.assertEqual(old.price,D('.80'))
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}};book.at=201
        b.step();self.assertEqual(len(e.orders),1);self.assertFalse(e.pending)
        e.advance(211);book.at=211;b.step();self.assertEqual(len(e.orders),1)
        e.advance(212);book.at=212;b.step();new=list(e.orders.values())[-1]
        self.assertEqual(old.status,'cancelled');self.assertEqual(new.price,D('.86'));self.assertTrue(new.maker)
        self.assertGreater(new.price,D(b.attempts[old.ticker]['initial_ceiling']))

    def test_decision_records_policy_size_and_order_link_for_analysis(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.step();o=next(iter(e.orders.values()))
        event=[fields for kind,fields in e.audit.events if kind=='FAVORITE_ENTRY_DECISION'][-1]
        details=json.loads(event['details']);self.assertEqual(event['order_id'],o.id)
        self.assertEqual(details['policy'],'favorites-paper-data-v3');self.assertEqual(details['quantity'],'10')
        self.assertEqual(details['estimate']['samples'],0)

    def test_changed_saved_size_replaces_only_after_cancel_ack(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        old=next(iter(e.orders.values()));b.contracts=D(20);b.step();b.step()
        self.assertEqual(len(e.orders),1)
        e.advance(202);book.at=202;b.step();new=list(e.orders.values())[-1]
        self.assertEqual(old.status,'cancelled');self.assertEqual(new.quantity,D(20))

    def test_partial_fills_continue_to_requested_size_with_real_cash_accounting(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()))
        e.fill(o,D(1),o.price,'TEST');book.at=201;b.step()
        self.assertEqual(o.status,'resting');self.assertEqual(o.remaining,D(9))
        e.fill(o,D(3),o.price,'TEST');e.advance(202);book.at=202;b.step()
        self.assertEqual(o.remaining,D(6));self.assertEqual(len(e.orders),1)
        e.fill(o,D(6),o.price,'TEST');b.step()
        self.assertEqual(o.status,'filled');self.assertEqual(e.wallet.inventory(o.ticker,'yes'),D(10))
        self.assertEqual(e.wallet.cash,D(992));self.assertEqual(len(e.orders),1)

    def test_partial_order_is_cancelled_when_data_or_entry_conditions_fail(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST')
        book.valid=False;b.step();e.advance(202)
        self.assertEqual(o.status,'cancelled');self.assertEqual(e.wallet.inventory(o.ticker,'yes'),D(1))

"""Paper collection uses one-contract probes and samples weak/unknown-value states."""
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
        self.assertEqual(o.quantity,D(1));self.assertTrue(o.maker)
        self.assertLess(a['entry_estimate']['lower'],float(o.price))
        self.assertEqual(a['entry_policy'],'favorites-paper-data-v3')
        self.assertEqual(a['entry_key'],key)
        self.assertEqual(e.wallet.cash,D(1000));self.assertFalse(e.wallet.lots)

    def test_configured_size_does_not_override_one_contract_research_limit(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.contracts=D(100);b.step()
        o=next(iter(e.orders.values()));self.assertEqual(o.quantity,D(1))
        self.assertEqual(o.reserved,D('.80'));self.assertEqual(e.available(),D('999.20'))

    def test_available_cash_and_real_series_fees_still_bound_simulated_orders(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.contracts=D(10000)
        e.fees[fixture.MakerEntries.ticker]=FeePolicy(D(1),D(1));b.step()
        o=next(iter(e.orders.values()))
        self.assertEqual(o.quantity,D(1));self.assertLessEqual(o.reserved,e.wallet.cash)
        self.assertGreater(e.fees[o.ticker].charge(o.quantity,o.price,True),0)

    def test_new_bucket_keeps_older_valid_maker_queue_after_minimum_rest(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        old=next(iter(e.orders.values()));self.assertEqual(old.price,D('.80'))
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        book.at=201;b.step()
        self.assertEqual(len(e.orders),1)
        e.advance(211);book.at=211;b.step()
        active=[o for o in e.orders.values() if o.status in ('pending','resting')]
        self.assertEqual(len(active),2)
        newer=next(o for o in active if o.id!=old.id)
        self.assertEqual(newer.price,D('.86'))
        self.assertTrue(newer.maker)
        self.assertEqual(old.status,'resting')
        self.assertFalse(any(action=='cancel' and ident==old.id for _,_,action,ident in e.pending))
        e.advance(224);book.at=224;b.step()
        self.assertEqual(len(e.orders),2)
        self.assertEqual({o.status for o in e.orders.values()},{'resting'})
        self.assertFalse(any(action=='cancel' for _,_,action,_ in e.pending))

    def test_decision_records_policy_size_and_order_link_for_analysis(self):
        e,b,_=fixture.MakerEntries().setup_bot();b.step();o=next(iter(e.orders.values()))
        event=[fields for kind,fields in e.audit.events if kind=='FAVORITE_ENTRY_DECISION'][-1]
        details=json.loads(event['details']);self.assertEqual(event['order_id'],o.id)
        self.assertEqual(details['policy'],'favorites-paper-data-v3');self.assertEqual(details['quantity'],'1')
        self.assertEqual(details['estimate']['samples'],0)

    def test_changed_saved_size_replaces_only_after_cancel_ack(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        old=next(iter(e.orders.values()));b.contracts=D(20);b.step();b.step()
        self.assertEqual(len(e.orders),1)
        e.advance(202);book.at=202;b.step()
        self.assertEqual(old.status,'resting')
        self.assertEqual(old.quantity,D(1))
        self.assertEqual(len(e.orders),1)

    def test_partial_fills_continue_to_requested_size_with_real_cash_accounting(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()))
        e.fill(o,D('.4'),o.price,'TEST');book.at=201;b.step()
        self.assertEqual(o.status,'resting');self.assertEqual(o.remaining,D('.6'))
        e.fill(o,D('.3'),o.price,'TEST');e.advance(202);book.at=202;b.step()
        self.assertEqual(o.remaining,D('.3'));self.assertEqual(len(e.orders),1)
        e.fill(o,D('.3'),o.price,'TEST');b.step()
        self.assertEqual(o.status,'filled');self.assertEqual(e.wallet.inventory(o.ticker,'yes'),D(1))
        self.assertEqual(e.wallet.cash,D('999.20'));self.assertEqual(len(e.orders),1)

    def test_distinct_market_price_can_create_second_paper_entry(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201)
        first=next(iter(e.orders.values()))
        e.fill(first,D(1),first.price,'TEST')
        book.at=212;e.advance(212)
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        orders=list(e.orders.values())
        self.assertEqual(len(orders),2)
        self.assertEqual(orders[-1].price,D('.86'))
        self.assertEqual(b.attempts[first.ticker]['repeat_entries'],1)
        self.assertEqual(e.wallet.inventory(first.ticker,'yes'),D(1))
        # Once filled, an unchanged qualifying state must not create a third entry.
        e.advance(213);e.fill(orders[-1],D(1),orders[-1].price,'TEST')
        e.advance(224);book.at=224;b.step()
        self.assertEqual(len(e.orders),2)
        self.assertGreater(b.attempts[first.ticker]['repeat_duplicate_suppressed'],0)

    def test_repeated_fills_remain_distinct_cohorts_at_settlement(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201)
        first=next(iter(e.orders.values()))
        e.fill(first,D(1),first.price,'TEST')
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step();second=list(e.orders.values())[-1]
        e.advance(213);e.fill(second,D(1),second.price,'TEST')
        chunks=b.attempts[first.ticker]['entry_fills']
        self.assertEqual(len(chunks),2)
        self.assertEqual({c['order_id'] for c in chunks},{first.id,second.id})
        self.assertEqual({D(c['price']) for c in chunks},{D('.80'),D('.86')})
        e.markets[first.ticker].update(paid=True,yes_payout_confirmed='1')
        b.step()
        self.assertEqual(b.attempts[first.ticker]['timing_finalized'],True)
        self.assertTrue(all(D(c['remaining'])==0 for c in chunks))


    def test_distinct_price_bucket_while_first_bid_rests_does_not_cancel_it(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201)
        first=next(iter(e.orders.values()))
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        active=[o for o in e.orders.values() if o.status in ('pending','resting')]
        self.assertEqual(len(active),2)
        self.assertEqual({o.price for o in active},{D('.80'),D('.86')})
        self.assertEqual({o.quantity for o in active},{D(1)})
        self.assertEqual(first.status,'resting')
        self.assertFalse(any(action=='cancel' and target==first.id for _,_,action,target in e.pending))
        self.assertEqual(b.attempts[first.ticker]['repeat_entries'],1)
        self.assertEqual(e.wallet.cash,D(1000))

    def test_moving_inside_same_five_cent_bucket_does_not_stack_bids(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201);first=next(iter(e.orders.values()))
        e.advance(212);book.at=212
        book.levels={'yes':{D('.80'):D(100)},'no':{D('.18'):D(100)}}
        b.step()
        self.assertEqual(len(e.orders),1)
        self.assertEqual(first.status,'resting')
        self.assertEqual(b.attempts[first.ticker].get('repeat_entries',0),0)

    def test_filling_one_bucket_preserves_other_resting_bid_and_cohort_identity(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201);first=next(iter(e.orders.values()))
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        e.advance(213);second=list(e.orders.values())[-1]
        self.assertEqual(second.status,'resting')
        e.fill(first,D(1),first.price,'TEST')
        self.assertEqual(second.status,'resting')
        self.assertFalse(any(action=='cancel' and target==second.id for _,_,action,target in e.pending))
        book.at=213;b.step()
        e.fill(second,D(1),second.price,'TEST')
        chunks=b.attempts[first.ticker]['entry_fills']
        self.assertEqual(len(chunks),2)
        self.assertEqual({c['order_id'] for c in chunks},{first.id,second.id})
        e.markets[first.ticker].update(paid=True,yes_payout_confirmed='1')
        b.step()
        from services.paper_demo.shadow.favorite_entries import entry_key,estimate
        from services.paper_demo.shadow.favorite_timing import clock
        rows=b.exit_evidence.cells
        keys={chunk['key'] for chunk in chunks}
        self.assertEqual(len(keys),2)
        self.assertTrue(all(estimate(rows,key)['samples']==1 for key in keys))
        from services.paper_demo.shadow.favorite_collection_quality import collection_quality
        self.assertEqual(collection_quality([b],e.now)['unique_verified_outcomes'],1)

    def test_resting_orders_plus_positions_respect_five_contract_market_cap(self):
        e,b,book=fixture.MakerEntries().setup_bot(paper_repeat_inventory_multiplier=1)
        b.step();e.advance(201);first=next(iter(e.orders.values()))
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        self.assertEqual(len(e.orders),1)
        self.assertEqual(first.status,'resting')
        self.assertGreater(b.attempts[first.ticker]['repeat_risk_suppressed'],0)

    def test_partial_fill_in_old_bucket_can_keep_remainder_and_new_bucket(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        b.step();e.advance(201);first=next(iter(e.orders.values()))
        e.fill(first,D('.4'),first.price,'TEST')
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        self.assertEqual(first.status,'resting')
        self.assertEqual(first.remaining,D('.6'))
        active=[o for o in e.orders.values() if o.status in ('pending','resting')]
        self.assertEqual(len(active),2)
        self.assertEqual(sum((o.remaining for o in active),D(0)),D('1.6'))
        self.assertEqual(e.wallet.inventory(first.ticker,'yes'),D('.4'))

    def test_calibrated_favorites_stays_single_entry_per_market(self):
        maker=fixture.MakerEntries()
        e,b,book=maker.setup_bot(paper_exploration=False)
        maker.seed(b);b.step();e.advance(201)
        first=next(iter(e.orders.values()))
        e.fill(first,D(1),first.price,'TEST')
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        self.assertEqual(len(e.orders),1)

    def test_repeat_entry_stops_at_bounded_market_inventory(self):
        e,b,book=fixture.MakerEntries().setup_bot(paper_repeat_inventory_multiplier=1)
        b.step();e.advance(201)
        first=next(iter(e.orders.values()))
        e.fill(first,D(1),first.price,'TEST')
        e.advance(212);book.at=212
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step()
        self.assertEqual(len(e.orders),1)
        self.assertGreater(b.attempts[first.ticker]['repeat_risk_suppressed'],0)

    def test_partial_order_is_cancelled_when_data_or_entry_conditions_fail(self):
        e,b,book=fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D('.4'),o.price,'TEST')
        book.valid=False;b.step();e.advance(202)
        self.assertEqual(o.status,'cancelled');self.assertEqual(e.wallet.inventory(o.ticker,'yes'),D('.4'))

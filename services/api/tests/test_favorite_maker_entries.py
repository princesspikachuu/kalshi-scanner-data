"""Maker-only favorites: actual costs, changing evidence, expiry and queue races."""
import json
import unittest
from decimal import Decimal as D
from services.api.tests.test_strategy_folders import QuietAudit,market,profile
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.favorites import FavoritesStrategy
from services.paper_demo.shadow.favorite_entries import entry_key,observe,estimate


class MakerEntries(unittest.TestCase):
    ticker='KXBTCD-test'

    def setup_bot(self, **settings):
        e=Engine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0)
        e.advance(200)
        book=market(e,self.ticker,yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites'),**settings)
        b=FavoritesStrategy(e,p);e.strategy=b;e.fill_callback=b.on_fill
        return e,b,book

    def seed(self,b,n=200,wins=200):
        key=entry_key('KXBTCD','yes',D('.79'),800)
        for i in range(n):observe(b.exit_evidence.cells,key,str(i),int(i<wins))
        return key

    def test_unknown_probability_joins_bid_with_one_demo_contract(self):
        e,b,book=self.setup_bot();b.step();o=next(iter(e.orders.values()))
        self.assertEqual((o.price,o.quantity,o.maker,o.expiry),(D('.79'),D(1),True,215))
        self.assertEqual(b.attempts[self.ticker]['entry_mode'],'paper_exploration')
        self.assertIn('probability unknown',b.last_reason)
        self.assertFalse(any(not x.maker for x in e.orders.values()))

    def test_exploration_can_be_disabled_without_inventing_an_edge(self):
        e,b,_=self.setup_bot(paper_exploration=False);b.step();self.assertFalse(e.orders)

    def test_supported_estimate_can_use_configured_size_after_all_costs(self):
        e,b,_=self.setup_bot();self.seed(b)
        e.fees[self.ticker]=FeePolicy(D(1),D(1));b.step()
        o=next(iter(e.orders.values()));a=b.attempts[self.ticker]
        self.assertEqual(o.quantity,D(10));self.assertTrue(o.maker)
        cost=o.price+e.fees[self.ticker].charge(o.quantity,o.price,True)/o.quantity
        self.assertLessEqual(cost+D('.02'),D(str(a['entry_estimate']['lower'])))

    def test_weak_evidence_blocks_even_a_high_market_price(self):
        e,b,_=self.setup_bot();self.seed(b,100,75);b.step()
        self.assertFalse(e.orders)

    def test_series_fees_can_eliminate_the_entry(self):
        e,b,_=self.setup_bot();self.seed(b);e.fees[self.ticker]=FeePolicy(D(1),D(100))
        b.step();self.assertFalse(e.orders)

    def test_maker_cannot_cross_after_submission_latency(self):
        e,b,book=self.setup_bot();b.step();o=next(iter(e.orders.values()))
        book.levels['no']={D('.22'):D(100)}
        e.advance(201)
        self.assertEqual(o.status,'rejected');self.assertFalse(e.wallet.lots)

    def test_stale_data_cancels_resting_bid_before_its_expiry(self):
        e,b,book=self.setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));book.valid=False;b.step();e.advance(202)
        self.assertEqual(o.status,'cancelled');self.assertFalse(e.wallet.lots)

    def test_expiry_rechecks_but_does_not_chase_a_higher_bid(self):
        e,b,book=self.setup_bot();b.step();old=next(iter(e.orders.values()))
        e.advance(215);book.at=215
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.13'):D(100)}}
        b.step();new=list(e.orders.values())[-1]
        self.assertEqual(old.status,'expired');self.assertLessEqual(new.price,D('.79'))
        self.assertEqual(new.expiry,230)
        e.advance(260);book.at=260;b.step()
        self.assertTrue(b.attempts[self.ticker]['recorded'])
        self.assertFalse(any(o.status in ('pending','resting') for o in e.orders.values()))

    def test_evidence_deterioration_cancels_without_stacking_replacement(self):
        e,b,book=self.setup_bot();key=self.seed(b);b.step();e.advance(201)
        for i in range(200,500):observe(b.exit_evidence.cells,key,str(i),0)
        b.step();b.step();self.assertEqual(len(e.orders),1)
        e.advance(202);self.assertEqual(next(iter(e.orders.values())).status,'cancelled')

    def test_partial_fill_stops_repricing_and_keeps_protective_exits(self):
        e,b,book=self.setup_bot();self.seed(b);b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST');e.advance(202)
        book.at=202;b.step()
        self.assertTrue(b.attempts[self.ticker]['first'])
        self.assertEqual(len(e.orders),1);self.assertEqual(o.status,'cancelled')
        self.assertEqual(e.wallet.inventory(self.ticker,'yes'),D(1))

    def test_only_confirmed_settlement_teaches_entry_model_and_survives_json(self):
        e,b,_=self.setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST')
        key=b.attempts[self.ticker]['entry_key']
        b.step();self.assertNotIn(key,b.exit_evidence.cells)
        e.markets[self.ticker].update(paid=True,yes_payout_confirmed='1');b.step();b.step()
        cells=json.loads(json.dumps(b.exit_evidence.cells))
        self.assertEqual(estimate(cells,key)['samples'],1)
        self.assertEqual(cells[key]['events'],{'TEST':1})

    def test_correlated_thresholds_do_not_inflate_confidence(self):
        cells={}
        for i in range(40):observe(cells,'key','same-event',1)
        self.assertEqual(estimate(cells,'key')['samples'],1)
        observe(cells,'key','same-event',0)
        self.assertEqual(cells['key']['events']['same-event'],0)

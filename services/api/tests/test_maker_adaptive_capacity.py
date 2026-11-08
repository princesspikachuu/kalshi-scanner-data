"""Maker expansion uses measured shared headroom; transport savings preserve execution."""
import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.monitoring import maker_entry_limit
from services.paper_demo.shadow.market_maker import MM_FOLDERS
from services.api.tests import test_maker_activity_lifecycle as lifecycle

class MakerAdaptiveCapacityTests(unittest.TestCase):
    def stats(self,level=0,own=0,other=0,subscribed=0):
        return dict(level=level,total=32+8*level,entry_candidates=12+4*level,
            entry_markets=own+other,subscribed_markets=subscribed,categories=dict(market_maker=own))
    def test_eight_twelve_sixteen_targets_with_unused_shared_headroom(self):
        for level,want in enumerate((8,12,16)):self.assertEqual(maker_entry_limit(self.stats(level)),want)
    def test_existing_strategies_and_two_free_slots_bound_maker_allocation(self):
        self.assertEqual(maker_entry_limit(self.stats(own=4,other=5,subscribed=20)),5)
        self.assertEqual(maker_entry_limit(self.stats(own=4,other=1,subscribed=32)),2)
    def test_more_than_four_actual_maker_markets_can_be_admitted_without_duplicate_streams(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite()
        for i in range(16):
            m=dict(payload['market'],ticker='POL-'+str(i))
            s.handle('maker_market',dict(payload,market=m),200)
        self.assertEqual(len(s.feed_markets()),16)
        self.assertTrue(all(len(s.portfolios[f][0].markets)==16 for f in MM_FOLDERS))
        self.assertEqual(s.monitoring_snapshot(200)['maker_entry_limit'],16)  # fixture level 2
    def test_serialized_admission_honors_cap_and_overload_without_evicting_existing_markets(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite()
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=True,level=0)
        for i in range(9):s.handle('maker_market',dict(payload,market=dict(payload['market'],ticker='POL-'+str(i))),200)
        self.assertEqual(len(s.feed_markets()),8)
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=False,level=0)
        s.handle('maker_market',dict(payload,market=dict(payload['market'],ticker='POL-NEW')),201)
        self.assertEqual(len(s.feed_markets()),8);self.assertEqual(s.monitoring_snapshot(201)['maker_slots_free'],0)

class MakerTransportTests(unittest.TestCase):
    def suite(self):
        s,p=lifecycle.MakerActivityLifecycleTests().suite();s.handle('maker_market',p,200);return s
    def frame(self,s,at,seq,ticker='POL-X',kind='orderbook_snapshot'):
        s.handle('kalshi',dict(type=kind,sid=1,seq=seq,msg=dict(market_ticker=ticker,
            yes_dollars_fp=[['.42','100']],no_dollars_fp=[['.52','100']],side='yes',price_dollars='.42',delta_fp='1')),at)
    def test_unrelated_frames_skip_work_but_preserve_shared_sequence_and_real_book_updates(self):
        s=self.suite();self.frame(s,200,1);e=s.portfolios[MM_FOLDERS[0]][0]
        calls=s.processing_costs[MM_FOLDERS[0]]['calls']
        self.frame(s,200.1,2,ticker='CRYPTO-X',kind='orderbook_delta')
        self.assertEqual(s.processing_costs[MM_FOLDERS[0]]['calls'],calls)
        self.assertEqual(e.sequences[1],2);self.assertEqual(e.unrelated_inputs_skipped,1)
        self.frame(s,200.2,3,kind='orderbook_delta')
        self.assertTrue(e.books['POL-X'].valid);self.assertEqual(e.books['POL-X'].levels['yes'][D('.42')],101)
    def test_missing_unrelated_frame_still_invalidates_books_until_replacement_snapshot(self):
        s=self.suite();self.frame(s,200,1);e=s.portfolios[MM_FOLDERS[0]][0]
        self.frame(s,200.1,3,ticker='CRYPTO-X',kind='orderbook_delta')
        self.assertFalse(e.books['POL-X'].valid)
        self.frame(s,200.2,4);self.assertTrue(e.books['POL-X'].valid)
    def test_live_orders_and_inventory_keep_the_full_causal_execution_path(self):
        for inventory in (False,True):
            s=self.suite();self.frame(s,200,1);e=s.portfolios[MM_FOLDERS[0]][0]
            if inventory:e.wallet.fill('POL-X','yes','buy',D(1),D('.42'),D(0),1,'entry')
            else:e.place('POL-X','yes','buy',D(1),D('.41'),maker=True)
            calls=s.processing_costs[MM_FOLDERS[0]]['calls']
            self.frame(s,200.1,2,ticker='CRYPTO-X',kind='orderbook_delta')
            self.assertEqual(s.processing_costs[MM_FOLDERS[0]]['calls'],calls+1)

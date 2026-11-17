"""Maker expansion uses measured shared headroom; transport savings preserve execution."""
import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.monitoring import maker_entry_limit
from services.paper_demo.shadow.market_maker import MM_FOLDERS
from services.api.tests import test_maker_activity_lifecycle as lifecycle

class FavoritesUnrelatedInputTests(unittest.TestCase):
    def suite(self):
        s,_=lifecycle.MakerActivityLifecycleTests().suite()
        return s

    def frame(self,seq,ticker='NOT-ADMITTED',kind='orderbook_delta'):
        return dict(type=kind,sid=101,seq=seq,
                    msg=dict(market_ticker=ticker,side='yes',
                             price_dollars='.42',delta_fp='1',
                             yes_dollars_fp=[['.42','100']],
                             no_dollars_fp=[['.52','100']]))

    def test_favorites_with_open_inventory_skip_unrelated_frames_but_advance_clock(self):
        s=self.suite()
        stats=s.portfolios['favorites_statistics'][0]
        stats.markets['HELD']=dict(ticker='HELD',close=10000)
        stats.wallet.fill('HELD','yes','buy',D(1),D('.42'),D(0),1,'held')
        for n in (1,2,3):
            s.handle('kalshi',self.frame(n,kind='orderbook_snapshot' if n==1 else 'orderbook_delta'),200+n)
        for folder in ('favorites','favorites_statistics'):
            e=s.portfolios[folder][0]
            self.assertEqual(e.unrelated_inputs_skipped,3)
            self.assertEqual(e.sequences[101],3)
            self.assertEqual(e.now,203)
            self.assertEqual(s.processing_costs.get(folder,{}).get('calls',0),0)
        self.assertEqual(stats.wallet.inventory('HELD','yes'),1)

    def test_gap_pending_actions_admitted_tickers_and_market_close_take_full_path(self):
        s=self.suite()
        s.handle('kalshi',self.frame(1,kind='orderbook_snapshot'),201)
        for folder in ('favorites','favorites_statistics'):
            e=s.portfolios[folder][0]
            e.pending.append((202,'buy','yes','missing'))
            self.assertFalse(s.skip_unrelated_favorites(e,'kalshi',self.frame(2),202))
            e.pending.clear()
            e.markets['ADMITTED']=dict(ticker='ADMITTED',close=10000)
            self.assertFalse(s.skip_unrelated_favorites(e,'kalshi',self.frame(2,ticker='ADMITTED'),202))
            e.markets['ADMITTED']['close']=202
            self.assertFalse(s.skip_unrelated_favorites(e,'kalshi',self.frame(2),202))
            e.markets.pop('ADMITTED')
            self.assertFalse(s.skip_unrelated_favorites(e,'kalshi',self.frame(3),203))
            self.assertEqual(e.sequences[101],1)
        s.handle('kalshi',self.frame(3),203)
        for folder in ('favorites','favorites_statistics'):
            e=s.portfolios[folder][0]
            self.assertEqual(e.sequences[101],3)
            self.assertEqual(e.unrelated_inputs_skipped,1)
            self.assertGreaterEqual(s.processing_costs[folder]['calls'],1)

class MakerAdaptiveCapacityTests(unittest.TestCase):
    def stats(self,level=0,own=0,other=0,subscribed=0):
        return dict(level=level,total=32+8*level,entry_candidates=15+4*level,
            entry_markets=own+other,subscribed_markets=subscribed,categories=dict(market_maker=own))
    def test_ten_fourteen_eighteen_targets_with_unused_shared_headroom(self):
        for level,want in enumerate((10,14,18)):self.assertEqual(maker_entry_limit(self.stats(level)),want)
    def test_existing_strategies_and_two_free_slots_bound_maker_allocation(self):
        self.assertEqual(maker_entry_limit(self.stats(own=4,other=5,subscribed=20)),8)
        self.assertEqual(maker_entry_limit(self.stats(own=4,other=1,subscribed=32)),2)
    def test_more_than_four_actual_maker_markets_can_be_admitted_without_duplicate_streams(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite()
        for i in range(18):
            m=dict(payload['market'],ticker='POL-'+str(i))
            s.handle('maker_market',dict(payload,market=m),200)
        self.assertEqual(len(s.feed_markets()),18)
        self.assertTrue(all(len(s.portfolios[f][0].markets)==18 for f in MM_FOLDERS))
        self.assertEqual(s.monitoring_snapshot(200)['maker_entry_limit'],18)  # fixture level 2
    def test_serialized_admission_honors_cap_and_overload_without_evicting_existing_markets(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite()
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=15,per_category=4,admitting=True,level=0)
        for i in range(11):s.handle('maker_market',dict(payload,market=dict(payload['market'],ticker='POL-'+str(i))),200)
        self.assertEqual(len(s.feed_markets()),10)
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=15,per_category=4,admitting=False,level=0)
        s.handle('maker_market',dict(payload,market=dict(payload['market'],ticker='POL-NEW')),201)
        self.assertEqual(len(s.feed_markets()),10);self.assertEqual(s.monitoring_snapshot(201)['maker_slots_free'],0)

    def test_overload_blocks_new_admission_but_does_not_pause_existing_maker_execution(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite()
        s.handle('maker_market',payload,200)
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=False,level=0)
        s.handle('clock',{},201)
        for folder in MM_FOLDERS:
            _,fleet,_=s.portfolios[folder]
            self.assertTrue(all(getattr(bot,'resource_paused',False) is False for bot in fleet.bots.values()))
        blocked=dict(payload,market=dict(payload['market'],ticker='POL-NEW'))
        s.handle('maker_market',blocked,201)
        self.assertNotIn('POL-NEW',s.feed_markets())

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

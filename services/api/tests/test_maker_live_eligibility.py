"""Near misses stay in discovery; scarce streams require currently tradable quotes."""
import time,unittest
from unittest.mock import Mock,AsyncMock
from services.api.tests import test_market_maker as fixtures
from services.api.tests import test_maker_activity_lifecycle as lifecycle
from services.paper_demo.shadow.market_maker import maker_once,profiles,quotable,MM_FOLDERS,activity_deadline
from services.paper_demo.shadow.core import FeePolicy
T=fixtures.T

class MakerLiveEligibilityTests(unittest.TestCase):
    def test_both_sides_and_variant_spreads_are_evaluated_without_threshold_changes(self):
        base,competitive=list(profiles())[0],list(profiles())[4]
        self.assertFalse(quotable(dict(yes=.1,no=.89),base['config']))
        self.assertFalse(quotable(dict(yes=.1,no=.85),competitive['config']))
        self.assertTrue(quotable(dict(yes=.15,no=.75),base['config']))
        self.assertFalse(quotable(dict(yes=.4,no=.58),base['config']))
        self.assertTrue(quotable(dict(yes=.4,no=.58),competitive['config']))
    def test_transient_unquotable_market_recovers_but_sustained_one_stops_new_buys(self):
        e,b,_=fixtures.MakerTests().bot();e.now=230;e.books[T].at=230
        e.books[T].levels={'yes':{fixtures.D('.1'):fixtures.D(100)},'no':{fixtures.D('.89'):fixtures.D(100)}}
        b.step(T);self.assertEqual(e.markets[T]['maker_unquotable_since'],230)
        self.assertFalse(e.markets[T]['maker_entry_blocked'])
        e.now=291;e.books[T].at=291;b.step(T);self.assertTrue(e.markets[T]['maker_entry_blocked'])
        e.books[T].levels={'yes':{fixtures.D('.42'):fixtures.D(100)},'no':{fixtures.D('.52'):fixtures.D(100)}}
        e.now=292;e.books[T].at=292;b.step(T)
        self.assertNotIn('maker_unquotable_since',e.markets[T]);self.assertFalse(e.markets[T]['maker_entry_blocked'])
    def test_normal_rotation_releases_a_flat_market_only_when_both_variants_are_unquotable(self):
        s,payload=lifecycle.MakerActivityLifecycleTests().suite();s.handle('maker_market',payload,200)
        for folder in MM_FOLDERS:s.portfolios[folder][0].markets['POL-X']['maker_unquotable_since']=300
        s.rotate_candidates(350);self.assertIn('POL-X',s.feed_markets())
        s.portfolios[MM_FOLDERS[1]][0].markets['POL-X'].pop('maker_unquotable_since')
        s.rotate_candidates(361);self.assertIn('POL-X',s.feed_markets())
        s.portfolios[MM_FOLDERS[1]][0].markets['POL-X']['maker_unquotable_since']=300
        s.rotate_candidates(361);self.assertNotIn('POL-X',s.feed_markets())

class MakerLiveDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_event_price_cannot_admit_a_currently_unquotable_book(self):
        now=time.time();suite=Mock();suite.portfolios={};suite.enabled_profiles.return_value=[next(profiles())]
        suite.monitoring_snapshot.return_value=dict(admitting=True);suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        raw=dict(ticker='POL-X',event_ticker='POL',open_time=fixtures.iso(now-86400),close_time=fixtures.iso(now+172800),
            status='active',yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000')
        suite.maker_discovery=dict(cursor='',candidates={},reads=0,next_at=0,incentive_at=now+1000,incentives={},settlement_at={},rejected={})
        host=Mock();host.experiments=suite;host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=FeePolicy())
        responses={'/events':dict(events=[dict(category='Politics',title='Election',series_ticker='POL',markets=[raw])]),
            '/markets/trades':dict(trades=[dict(created_time=fixtures.iso(now-100),yes_price_dollars='.45')]*30),
            '/markets/POL-X/orderbook':dict(orderbook_fp=dict(yes_dollars=[['.10','100']],no_dollars=[['.89','100']]))}
        host.verified_data.call.side_effect=lambda method,path,params=None:responses[path]
        await maker_once(host)
        self.assertEqual(host.verified_data.call.call_count,3);host.put.assert_not_called();host.fee_policy.assert_not_called()
        self.assertEqual(suite.maker_discovery['candidates']['POL-X']['reason'],'current_price_or_spread_not_eligible')

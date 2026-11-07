"""Hourly discovery catches listed favorites and can revisit changed candidates."""
import unittest,json,time
from datetime import datetime,timezone
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests import test_strategy_scope as scope
from services.api.tests.test_strategy_folders import market
from services.paper_demo.shadow.hourly import hourly_once
from services.paper_demo.shadow.experiments import ExperimentSuite

class Scan(unittest.IsolatedAsyncioTestCase):
    def setup_host(self):
        suite,_=scope.ScopeTests().suite();host=Mock();host.experiments=suite;host.put=AsyncMock()
        host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        selected=[p for p in suite.enabled_profiles('hourly') if p['series'] in ('KXBTCD','KXETHD','KXSOLD')]
        original=suite.enabled_profiles
        suite.enabled_profiles=lambda asset:selected if asset=='hourly' else original(asset)
        return host,suite

    async def test_pass_reaches_third_series_and_filters_unusable_quotes(self):
        host,suite=self.setup_host();now=1000
        def call(method,path,query=None):
            if path.startswith('/series/'):return dict(series=dict(frequency='hourly'))
            series=query['series_ticker'];good=series=='KXSOLD'
            date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
            return dict(markets=[dict(ticker=series+'-listed',event_ticker=series+'-event',status='active',open_time=date(100),close_time=date(2800),
                yes_bid_dollars='.81' if good else '.50',no_bid_dollars='.15' if good else '.48',volume_fp='8000')])
        host.verified_data.call.side_effect=call
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=now):await hourly_once(host)
        host.put.assert_awaited_once();host.fee_policy.assert_awaited_once()
        self.assertEqual(host.put.await_args.args[1]['market']['series_ticker'],'KXSOLD')
        self.assertEqual(suite.hourly_scan['checked_series'],3)
        self.assertEqual(suite.hourly_scan['eligible_markets'],1)
        self.assertEqual(suite.hourly_scan['subscribed'],1)
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=1006):await hourly_once(host)
        self.assertEqual(host.verified_data.call.call_count,6) # Backoff avoids redundant reads.
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=1016):await hourly_once(host)
        metadata=[c for c in host.verified_data.call.call_args_list if c.args[1].startswith('/series/')]
        self.assertEqual(len(metadata),3) # Frequency cache never substitutes for live quotes/fees.
        self.assertEqual(host.fee_policy.await_count,2)

    async def test_capacity_pause_makes_no_new_market_or_fee_requests(self):
        host,suite=self.setup_host();suite.search_capacity=lambda *args:False
        await hourly_once(host)
        host.verified_data.call.assert_not_called();host.fee_policy.assert_not_awaited()
        self.assertEqual(suite.hourly_scan['reason'],'Admission paused by measured capacity')

    async def test_existing_series_candidate_cannot_be_duplicated_within_batch(self):
        host,suite=self.setup_host();e=suite.portfolios['favorites'][0]
        market(e,'KXBTCD-existing',close=time.time()+1000);e.markets['KXBTCD-existing']['hourly_price']=True
        host.verified_data.call.return_value=dict(series=dict(frequency='daily'))
        await hourly_once(host)
        self.assertFalse(any(c.args[1]=='/series/KXBTCD' for c in host.verified_data.call.call_args_list))
        host.put.assert_not_awaited()

class Revisit(unittest.TestCase):
    def test_readmission_waits_for_snapshot_and_uses_exploration_policy(self):
        suite,_=scope.ScopeTests().suite();e,f,_=suite.portfolios['favorites'];e.now=200
        t='KXHIGHNY-retry';market(e,t,close=10000)
        e.markets[t].update(weather_category='weather_daily',discovered_at=100,bot_id='fav_kxhighny')
        b=f.owner(t);b.attempts[t]=dict(first=False,recorded=False,side='yes',price='.79',quantity='1',
            initial_ceiling='.79',entry_deadline=9000,loss_budget='5',price_band='70–79¢')
        suite.extra[t]=t;suite.rotate_candidates(250)
        self.assertTrue(e.markets[t]['entry_parked']);self.assertFalse(suite.candidate_allowed(t,300))
        self.assertTrue(suite.candidate_allowed(t,311))
        payload=dict(market=dict(ticker=t,event_ticker='TEST',open=100,close=10000,weather_category='weather_daily',discovered_at=311),taker_multiplier='1',maker_multiplier='0')
        suite.handle('weather_market',payload,311)
        self.assertFalse(e.markets[t]['entry_parked']);self.assertFalse(e.books[t].valid)
        self.assertFalse(b.attempts[t]['recorded']);self.assertEqual(b.attempts[t]['initial_ceiling'],'.79')
        b.step();self.assertFalse(e.orders)
        suite.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker=t,
            yes_dollars_fp=[['.85','100']],no_dollars_fp=[['.13','100']])),312)
        self.assertTrue(e.orders);self.assertTrue(all(o.price<=D('.95') for o in e.orders.values()))
        self.assertTrue(all(o.quantity==D(10) for o in e.orders.values()))

    def test_completed_hourly_entry_is_not_rearmed_after_cooldown(self):
        suite,_=scope.ScopeTests().suite();e,f,_=suite.portfolios['favorites'];t='KXSOLD-done'
        market(e,t);f.owner(t).attempts[t]=dict(first=True,recorded=True)
        self.assertFalse(suite.candidate_allowed(t,500))

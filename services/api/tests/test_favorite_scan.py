"""Hourly discovery catches listed favorites and can revisit changed candidates."""
import unittest,json,time
from datetime import datetime,timezone
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests import test_strategy_scope as scope
from services.api.tests.test_strategy_folders import market
from services.paper_demo.shadow.hourly import hourly_once,balanced_hourly_profiles,next_hourly_profile
from services.paper_demo.shadow.weather import candidates as weather_candidates,weather_once
from services.paper_demo.shadow.experiments import ExperimentSuite

class Scan(unittest.IsolatedAsyncioTestCase):
    def setup_host(self):
        suite,_=scope.ScopeTests().suite();host=Mock();host.experiments=suite;host.put=AsyncMock()
        host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        selected=[p for p in suite.enabled_profiles('hourly') if p['series'] in ('KXBTCD','KXETHD','KXSOLD')]
        original=suite.enabled_profiles
        suite.enabled_profiles=lambda asset:selected if asset=='hourly' else original(asset)
        return host,suite

    def test_hourly_profile_order_reaches_finance_without_increasing_scan_budget(self):
        profiles=[dict(series=s) for s in ('KXBTCD','KXETHD','KXSOLD',
            'KXGOLDH','KXSILVERH','KXUSDCADAH','KX10YRRATEAH')]
        order=balanced_hourly_profiles(profiles)
        self.assertEqual(len(order),len(profiles))
        self.assertEqual(len({p['series'] for p in order}),len(profiles))
        self.assertEqual([p['series'] for p in order[:3]],['KXBTCD','KXGOLDH','KXUSDCADAH'])

    def test_free_hourly_slot_prioritizes_unrepresented_finance_then_falls_back_on_cooldown(self):
        profiles=[dict(series=s) for s in ('KXETHD','KXUSDCADAH','KXGOLDH')]
        active=['KXBTCD-live','KXSOLD-live','KXSILVERH-live']
        p,_=next_hourly_profile(profiles,active,0,active)
        self.assertEqual(p['series'],'KXUSDCADAH')
        p,_=next_hourly_profile(profiles,active+['KXUSDCADAH-cooldown'],0,active)
        self.assertEqual(p['series'],'KXGOLDH')

    def test_weather_usable_maker_book_ranks_ahead_of_one_sided_extreme(self):
        date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        now=datetime(2026,11,21,4,tzinfo=timezone.utc).timestamp()
        base=dict(status='active',open_time=date(now-100),close_time=date(now+3600))
        rows=[dict(base,ticker='KXHIGHNY-26NOV20-one',yes_bid_dollars='.90',no_bid_dollars='0'),
              dict(base,ticker='KXHIGHNY-26NOV20-two',yes_bid_dollars='.80',no_bid_dollars='.18')]
        self.assertEqual(weather_candidates(rows,'KXHIGHNY',now)[0]['ticker'],'KXHIGHNY-26NOV20-two')

    def test_daily_weather_favorites_with_less_than_an_hour_are_candidates(self):
        date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        now=datetime(2026,11,21,4,30,tzinfo=timezone.utc).timestamp()
        rows=[dict(ticker='KXHIGHNY-26NOV20-eligible',status='active',open_time=date(now-100),
                   close_time=date(now+5400),yes_bid_dollars='.83',no_bid_dollars='.13'),
              dict(ticker='KXHIGHNY-26NOV20-too-late',status='active',open_time=date(now-100),
                   close_time=date(now+50))]
        self.assertEqual([m['ticker'] for m in weather_candidates(rows,'KXHIGHNY',now)],
                         ['KXHIGHNY-26NOV20-eligible'])

    async def test_daily_weather_discovery_gets_first_shared_capacity_opportunity(self):
        host=Mock();suite=Mock();host.experiments=suite
        host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        suite.feed_markets.return_value={};suite.weather_cursor={};suite.weather_pages={};suite.weather_scan_log_at=0
        suite.search_capacity.side_effect=[True,False]
        suite.enabled_profiles.side_effect=lambda category:[dict(series='KXHIGHNY')] if category=='weather_daily' else [dict(series='KXHIGHNYH')]
        suite.candidate_allowed.return_value=True
        suite.settlement_markets.return_value={}
        date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        now=datetime(2026,11,21,4,tzinfo=timezone.utc).timestamp()
        host.verified_data.call.return_value=dict(markets=[dict(ticker='KXHIGHNY-26NOV20-eligible',
            event_ticker='KXHIGHNY-26NOV20',status='active',open_time=date(now-100),
            close_time=date(now+7200),yes_bid_dollars='.83',no_bid_dollars='.13')])
        with patch('services.paper_demo.shadow.weather.time.time',return_value=now):
            await weather_once(host)
        self.assertEqual(suite.search_capacity.call_args_list[0].args[0],'weather_daily')
        host.put.assert_awaited_once()
        self.assertEqual(host.put.await_args.args[1]['market']['weather_category'],'weather_daily')

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

    async def test_capacity_pause_still_records_listing_coverage_without_subscribing(self):
        host,suite=self.setup_host();suite.search_capacity=lambda *args:False
        date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        def call(method,path,query=None):
            if path.startswith('/series/'):return dict(series=dict(frequency='hourly'))
            series=query['series_ticker']
            return dict(markets=[dict(ticker=series+'-listed',event_ticker='event',status='active',open_time=date(100),
                close_time=date(2800),yes_bid_dollars='.81',no_bid_dollars='.15')])
        host.verified_data.call.side_effect=call
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=1000):await hourly_once(host)
        host.fee_policy.assert_not_awaited();host.put.assert_not_awaited()
        self.assertEqual(suite.hourly_scan['checked_series'],3)
        self.assertEqual(suite.hourly_scan['subscribed'],0)
        self.assertEqual(suite.hourly_coverage['KXBTCD']['active_markets'],1)
        self.assertEqual(suite.hourly_coverage['KXBTCD']['eligible_markets'],1)
        self.assertIn('capacity paused',suite.hourly_coverage['KXBTCD']['reason'])
        e,f,ps=suite.portfolios['favorites'];p=next(p for p in ps if p['series']=='KXBTCD')
        self.assertIn('capacity paused',suite.data_message(e,f.bots[p['series']],p,1000))
        self.assertIn('scan delayed',suite.data_message(e,f.bots[p['series']],p,1201))

    async def test_existing_series_candidate_cannot_be_duplicated_within_batch(self):
        host,suite=self.setup_host();e=suite.portfolios['favorites'][0]
        market(e,'KXBTCD-existing',close=time.time()+1000);e.markets['KXBTCD-existing']['hourly_price']=True
        host.verified_data.call.return_value=dict(series=dict(frequency='daily'))
        await hourly_once(host)
        self.assertFalse(any(c.args[1]=='/series/KXBTCD' for c in host.verified_data.call.call_args_list))
        host.put.assert_not_awaited()

class Revisit(unittest.TestCase):
    def test_readmission_waits_for_snapshot_and_uses_exploration_policy(self):
        suite,_=scope.ScopeTests().suite();e,f,_=suite.portfolios['favorites'];base=datetime(2026,11,21,3,tzinfo=timezone.utc).timestamp();e.now=base+200
        t='KXHIGHNY-26NOV20-retry';market(e,t,close=base+10000)
        e.markets[t].update(weather_category='weather_daily',discovered_at=base+100,bot_id='fav_kxhighny')
        b=f.owner(t);b.attempts[t]=dict(first=False,recorded=False,side='yes',price='.79',quantity='1',
            initial_ceiling='.79',entry_deadline=base+7000,loss_budget='5',price_band='70–79¢')
        suite.extra[t]=t;suite.rotate_candidates(base+250)
        self.assertTrue(e.markets[t]['entry_parked']);self.assertFalse(suite.candidate_allowed(t,base+300))
        self.assertTrue(suite.candidate_allowed(t,base+311))
        payload=dict(market=dict(ticker=t,event_ticker='KXHIGHNY-26NOV20',open=base+100,close=base+10000,weather_category='weather_daily',discovered_at=base+311),taker_multiplier='1',maker_multiplier='0')
        suite.handle('weather_market',payload,base+311)
        self.assertFalse(e.markets[t]['entry_parked']);self.assertFalse(e.books[t].valid)
        self.assertFalse(b.attempts[t]['recorded']);self.assertEqual(b.attempts[t]['initial_ceiling'],'.79')
        b.step();self.assertFalse(e.orders)
        suite.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker=t,
            yes_dollars_fp=[['.85','100']],no_dollars_fp=[['.13','100']])),base+312)
        self.assertTrue(e.orders);self.assertTrue(all(o.price<=D('.95') for o in e.orders.values()))
        self.assertTrue(all(o.quantity==D(10) for o in e.orders.values()))

    def test_completed_hourly_entry_is_not_rearmed_after_cooldown(self):
        suite,_=scope.ScopeTests().suite();e,f,_=suite.portfolios['favorites'];t='KXSOLD-done'
        market(e,t);f.owner(t).attempts[t]=dict(first=True,recorded=True)
        self.assertFalse(suite.candidate_allowed(t,500))

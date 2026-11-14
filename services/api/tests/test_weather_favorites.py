"""Weather coverage, isolated ownership, inventory retention and real settlement."""
import unittest,time
from datetime import datetime,timezone
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests import test_strategy_folders as existing
market=existing.market
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.paper_demo.shadow.weather import weather_profiles,candidates,weather_once,initialize_weather

class WeatherSuite(unittest.TestCase):
    def suite(self):
        suite,rows=existing.SuiteTests().suite()
        rows += [dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in weather_profiles()]
        suite.host.engine.markets={}
        return existing.ready_suite(suite.host,rows),rows
    def test_weather_profiles_cover_hourly_and_daily_without_duplicate_ids(self):
        ps=weather_profiles()
        self.assertEqual(len(ps),15);self.assertEqual(len({p['id'] for p in ps}),15)
        self.assertEqual(sum(p['asset']=='weather' for p in ps),8)
        self.assertEqual(sum(p['asset']=='weather_daily' for p in ps),7)
    def test_weather_market_routes_only_to_favorites_and_can_enter_both_thresholds(self):
        suite,rows=self.suite();e,f,ps=suite.portfolios['favorites']
        for ticker in ('KXHIGHNY-TEST-B80','KXHIGHNY-TEST-B82'):
            suite.handle('weather_market',dict(market=dict(ticker=ticker,event_ticker='SAME',open=100,close=80000,weather_category='weather_daily',discovered_at=200),taker_multiplier='1',maker_multiplier='0'),200)
            e.books[ticker].levels={'yes':{D('.79'):D(100)},'no':{D('.19'):D(100)}};e.books[ticker].valid=True;e.books[ticker].at=200
        f.step()
        self.assertEqual(len(e.orders),2)
        self.assertTrue(all(o.side=='yes' and o.maker for o in e.orders.values()))
        self.assertFalse(suite.portfolios['sequential'][0].markets)
        self.assertFalse(suite.portfolios['complete_set'][0].markets)
        self.assertEqual(e.markets['KXHIGHNY-TEST-B80']['bot_id'],'fav_kxhighny')
    def test_rotation_keeps_filled_weather_and_shared_basket_subscription(self):
        suite,rows=self.suite();e,f,ps=suite.portfolios['favorites'];e.now=1000
        for suffix,filled in (('EMPTY',False),('HELD',True)):
            t='KXHIGHNY-'+suffix
            market(e,t,close=80000);e.markets[t].update(weather_category='weather_daily',discovered_at=100,bot_id='fav_kxhighny')
            if filled:e.wallet.fill(t,'yes','buy',D(1),D('.8'),D(0),100,'fill')
            f.bots['KXHIGHNY'].attempts[t]=dict(first=filled)
            suite.extra[t]=t
        # A second portfolio still needs the same unfilled favorite's ticker.
        other=suite.portfolios['complete_set'][0];market(other,'KXHIGHNY-EMPTY',close=80000);other.now=1000
        suite.maintain()
        self.assertNotIn('KXHIGHNY-EMPTY',e.markets)
        self.assertIn('KXHIGHNY-HELD',e.markets)
        self.assertIn('KXHIGHNY-EMPTY',suite.extra)
        self.assertEqual(suite.summary['favorites']['fav_kxhighny']['attempts'],1)
    def test_settlement_pays_only_confirmed_result(self):
        suite,rows=self.suite();e,f,ps=suite.portfolios['favorites'];e.now=200
        t='KXHIGHNY-TEST';market(e,t,close=250);e.markets[t]['weather_category']='weather_daily'
        e.wallet.fill(t,'yes','buy',D(1),D('.8'),D(0),200,'fill')
        suite.handle('clock',{},300);self.assertEqual(e.wallet.cash,D('999.2'))
        suite.handle('experiment_settlement',dict(ticker=t,result='yes',status='settled'),301)
        self.assertEqual(e.wallet.cash,D('1000.2'));self.assertTrue(e.markets[t]['paid'])

class WeatherDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_discovers_each_category_with_24h_filter_and_verified_fees(self):
        suite,rows=WeatherSuite().suite();host=Mock();host.experiments=suite;host.engine.markets={}
        host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        now=time.time()
        def call(method,path,query):
            series=query['series_ticker'];t=series+'-TEST'
            date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
            return dict(markets=[dict(ticker=t,event_ticker=series+'-EVENT',status='active',open_time=date(now-100),close_time=date(now+7200),yes_bid=80)])
        host.verified_data.call.side_effect=call
        await weather_once(host)
        self.assertEqual(host.put.await_count,2);self.assertEqual(host.fee_policy.await_count,2)
        categories={c.args[1]['market']['weather_category'] for c in host.put.await_args_list}
        self.assertEqual(categories,{'weather','weather_daily'})
        for c in host.verified_data.call.call_args_list:
            self.assertEqual(c.args[0:2],('GET','/markets'))
            self.assertLessEqual(c.args[2]['max_close_ts']-now,86400)
    async def test_paused_weather_does_not_subscribe_and_still_checks_due_settlements(self):
        suite,rows=WeatherSuite().suite();host=Mock();host.experiments=suite;host.engine.markets={};host.put=AsyncMock()
        e,f,ps=suite.portfolios['favorites']
        for b in f.bots.values():b.enabled=False
        market(e,'KXHIGHNY-DUE',close=time.time()-10);e.markets['KXHIGHNY-DUE']['weather_category']='weather_daily'
        host.verified_data.call.return_value=dict(market=dict(ticker='KXHIGHNY-DUE',status='closed',result='yes'))
        await weather_once(host);host.put.assert_not_awaited()
        host.verified_data.call.return_value=dict(market=dict(ticker='KXHIGHNY-DUE',status='settled',result='yes'))
        await weather_once(host);host.put.assert_awaited_once()
    async def test_inventory_rejects_wrong_series_future_and_long_horizon(self):
        now=time.time();date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        row=dict(ticker='KXHIGHNY-OK',status='active',open_time=date(now-10),close_time=date(now+3600))
        bad=[dict(row,ticker='OTHER-X'),dict(row,open_time=date(now+10)),dict(row,close_time=date(now+90000)),dict(row,status='settled')]
        self.assertEqual(candidates([row]+bad,'KXHIGHNY',now),[row])

@unittest.skipUnless(__import__('services.api.tests.test_demo_postgres',fromlist=['URL']).URL,'Disposable PostgreSQL required')
class WeatherMigration(unittest.TestCase):
    setUp=existing.FolderPostgres.setUp;tearDown=existing.FolderPostgres.tearDown;seed=existing.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):existing.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):existing.FolderPostgres.tearDownClass.__func__(cls)
    def test_weather_migration_preserves_balances_session_and_paused_controls(self):
        self.seed();before=self.demo.get('shadow/folder/favorites')
        self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id='favorites'))
        initialize_weather(self.demo,lambda:None);initialize_weather(self.demo,lambda:None)
        after=self.demo.get('shadow/folder/favorites')
        self.assertEqual(before['progress'],after['progress'])
        rows=self.demo.rows('shadow/bot/',200)
        self.assertEqual(len(rows),100)
        weather=[r for r in rows if r['parameters'].get('asset') in ('weather','weather_daily')]
        self.assertEqual(len(weather),15);self.assertTrue(all(r['progress']['desired']=='paused' for r in weather))
        data=self.client.get('/demo/shadow/workspace').json()
        self.assertEqual(len(data['bots']),100)

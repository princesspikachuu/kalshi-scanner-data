import unittest,time
from decimal import Decimal as D
from datetime import datetime,timezone
from unittest.mock import Mock,AsyncMock
from services.paper_demo.shadow.sports import live_gate,sports_profiles,initialize_sports,sports_once
from services.paper_demo.shadow.weather import initialize_weather
from services.paper_demo.shadow.favorites import FavoritesStrategy
from services.api.tests import test_strategy_folders as existing
from services.api.tests import test_weather_favorites as weather
from services.api.tests import test_demo_postgres as fixture
from services.paper_demo.shadow.experiments import ExperimentSuite

def inputs(now=10000):
    raw=dict(ticker='KXNBAGAME-TEST-YES',event_ticker='KXNBAGAME-TEST',status='active',open_time=9000,close_time=200000,expected_expiration_time=13600)
    milestone=dict(id='game-id',category='Sports',start_date=6400,related_event_tickers=[raw['event_ticker']])
    live=dict(live_data=dict(milestone_id='game-id',details=dict(status='live',last_updated_ts=now)))
    return raw,milestone,live

class SportsGates(unittest.TestCase):
    def test_linked_live_game_in_final_two_estimated_hours_is_eligible(self):
        self.assertTrue(live_gate(*inputs(),10000)['sports_live'])
        raw,m,l=inputs();raw['close_time']=900000
        self.assertTrue(live_gate(raw,m,l,10000)['sports_live']) # late settlement date is irrelevant
    def test_pregame_early_finished_delayed_stale_and_unlinked_games_are_blocked(self):
        for state in ('scheduled','closed','postponed','suspended','finished','unknown'):
            raw,m,l=inputs();l['live_data']['details']['status']=state
            self.assertFalse(live_gate(raw,m,l,10000)['sports_live'],state)
        for patch in (dict(last_updated_ts=9900),dict(last_updated_ts=None),dict(live_data_delayed=True),dict(winner='team'),dict(result_pending=True)):
            raw,m,l=inputs();l['live_data']['details'].update(patch)
            self.assertFalse(live_gate(raw,m,l,10000)['sports_live'])
        for change in ('early','pregame','missing_end','wrong_event','wrong_id'):
            raw,m,l=inputs()
            if change=='early':raw['expected_expiration_time']=18000
            if change=='pregame':m['start_date']=11000
            if change=='missing_end':raw['expected_expiration_time']=None
            if change=='wrong_event':m['related_event_tickers']=['OTHER']
            if change=='wrong_id':l['live_data']['milestone_id']='other'
            self.assertFalse(live_gate(raw,m,l,10000)['sports_live'],change)
    def test_no_fallback_from_missing_game_end_to_market_close(self):
        raw,m,l=inputs();raw['expected_expiration_time']=None;raw['close_time']=11000
        self.assertFalse(live_gate(raw,m,l,10000)['sports_live'])
    def test_sports_order_expires_before_its_live_verification_becomes_stale(self):
        e=existing.Engine(existing.QuietAudit(),cash='1000');e.advance(10000)
        p=dict(sports_profiles()[0],revision=1);p['series']='KXNBAGAME'
        b=FavoritesStrategy(e,p);ticker='KXNBAGAME-TEST-YES'
        existing.market(e,ticker,yes='.79',no='.19',close=200000)
        e.markets[ticker].update(live_gate(*inputs(),10000));b.step()
        order=next(iter(e.orders.values()))
        self.assertEqual(order.expiry,10030)
        e.advance(10031);b.step();self.assertEqual(order.status,'expired')
    def test_early_game_cannot_enter_even_with_a_fresh_book(self):
        e=existing.Engine(existing.QuietAudit(),cash='1000');e.advance(10000)
        b=FavoritesStrategy(e,dict(existing.profile('KXNBAGAME','fav_sport','favorites'),asset='sports'))
        t='KXNBAGAME-TEST';existing.market(e,t,yes='.79',no='.19',close=200000)
        e.markets[t].update(sports=True,sports_live=True,sports_start=9000,sports_expected_end=19000,sports_verified_until=10030)
        b.step();self.assertFalse(e.orders)

class SportsDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_verified_late_game_uses_read_only_milestone_and_live_endpoints(self):
        suite,rows=weather.WeatherSuite().suite()
        rows += [dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in sports_profiles()]
        suite=weather.existing.ready_suite(suite.host,rows);host=Mock();host.experiments=suite;host.engine.markets={}
        host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        now=time.time();date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        def call(method,path,query=None):
            self.assertEqual(method,'GET')
            if path=='/markets':return dict(markets=[dict(ticker=query['series_ticker']+'-TEST',event_ticker='EVENT',status='active',open_time=date(now-1000),close_time=date(now+86400),expected_expiration_time=date(now+3600))])
            if path=='/milestones':return dict(milestones=[dict(id='game-id',category='Sports',start_date=date(now-2000),related_event_tickers=['EVENT'])])
            if path=='/live_data/milestone/game-id':return dict(live_data=dict(milestone_id='game-id',details=dict(status='live',last_updated_ts=now)))
            raise AssertionError(path)
        host.verified_data.call.side_effect=call
        await sports_once(host);host.put.assert_awaited_once()
        source,payload=host.put.await_args.args;self.assertEqual(source,'sports_market');self.assertTrue(payload['market']['sports_live'])
        suite.handle(source,payload,time.time())
        self.assertIn(payload['market']['ticker'],suite.portfolios['favorites'][0].markets)
        self.assertFalse(suite.portfolios['sequential'][0].markets)

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL required')
class SportsMigration(unittest.TestCase):
    setUp=existing.FolderPostgres.setUp;tearDown=existing.FolderPostgres.tearDown;seed=existing.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):existing.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):existing.FolderPostgres.tearDownClass.__func__(cls)
    def test_adds_seven_paused_sports_bots_without_resetting_existing_session(self):
        self.seed();initialize_weather(self.demo,lambda:None)
        before=self.demo.get('shadow/folder/favorites')['progress']
        self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id='favorites'))
        initialize_sports(self.demo,lambda:None);initialize_sports(self.demo,lambda:None)
        self.assertEqual(before,self.demo.get('shadow/folder/favorites')['progress'])
        rows=self.demo.rows('shadow/bot/',200);self.assertEqual(len(rows),107)
        sports=[r for r in rows if r['parameters'].get('asset')=='sports']
        self.assertEqual(len(sports),7);self.assertTrue(all(r['progress']['desired']=='paused' for r in sports))

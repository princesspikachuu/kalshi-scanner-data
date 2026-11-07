import unittest,time
from decimal import Decimal as D
from datetime import datetime,timezone
from unittest.mock import Mock,AsyncMock
from services.api.tests import test_strategy_folders as fixture
from services.api.tests import test_demo_postgres as pg
from services.api.tests.test_sports_favorites import inputs
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.paper_demo.shadow.scope import initialize_scope,hourly_profiles,sequential_profiles
from services.paper_demo.shadow.weather import initialize_weather
from services.paper_demo.shadow.sports import initialize_sports,live_gate
from services.paper_demo.shadow.hourly import hourly_once
from services.paper_demo.shadow.favorites import FavoritesStrategy
from services.paper_demo.shadow.sequential import SequentialStrategy,PairModel

class ScopeTests(unittest.TestCase):
    def suite(self):
        old,rows=fixture.SuiteTests().suite()
        rows += [dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in sequential_profiles()+hourly_profiles()]
        # Include favorites on the same series to verify shared transport and
        # distinct paper engines, rather than an accidental transfer of inventory.
        rows += [dict(parameters=dict(p,id='fav_'+p['series'].lower(),folder_id='favorites',strategy='favorites',revision=1),progress=dict(desired='running')) for p in sequential_profiles()]
        old.host.engine.markets={}
        return fixture.ready_suite(old.host,rows),rows
    def test_weather_shared_feed_retains_independent_engines_and_ownership(self):
        s,rows=self.suite();t='KXHIGHNY-TEST'
        s.handle('weather_market',dict(market=dict(ticker=t,event_ticker='EVENT',open=100,close=10000,weather_category='weather_daily',discovered_at=200),taker_multiplier='1',maker_multiplier='0'),200)
        seq=s.portfolios['sequential'][0];fav=s.portfolios['favorites'][0]
        self.assertEqual(seq.markets[t]['bot_id'],'seq_kxhighny');self.assertEqual(fav.markets[t]['bot_id'],'fav_kxhighny')
        seq.wallet.fill(t,'yes','buy',D(1),D('.45'),D(0),1,'test')
        self.assertEqual(fav.wallet.cash,D(1000));self.assertFalse(fav.wallet.lots)
        s.maintain();self.assertIn(t,s.extra)
    def test_new_sequential_bot_joins_existing_held_weather_subscription(self):
        s,rows=self.suite();fav=s.portfolios['favorites'][0];t='KXHIGHNY-HELD'
        fixture.market(fav,t,close=time.time()+3600)
        fav.markets[t].update(weather_category='weather_daily',bot_id='fav_kxhighny')
        fav.wallet.fill(t,'yes','buy',D(2),D('.8'),D(0),1,'old')
        cash=fav.wallet.cash;s.share_external_markets();seq=s.portfolios['sequential'][0]
        self.assertEqual(seq.markets[t]['bot_id'],'seq_kxhighny')
        self.assertFalse(seq.books[t].valid);self.assertFalse(seq.wallet.lots)
        self.assertEqual(fav.wallet.cash,cash)
    def test_unfilled_favorite_keeps_shared_game_view_when_sequential_holds_it(self):
        s,rows=self.suite();t='KXNBAGAME-TEST'
        s.handle('sports_market',dict(market=dict(ticker=t,event_ticker='EVENT',open=100,close=10000,
            discovered_at=100,sports=True,sports_live=False),taker_multiplier='1',maker_multiplier='0'),200)
        seq=s.portfolios['sequential'][0];fav=s.portfolios['favorites'][0]
        seq.wallet.fill(t,'yes','buy',D(1),D('.45'),D(0),1,'test')
        seq.now=fav.now=1000;s.maintain()
        self.assertIn(t,fav.markets);self.assertIn(t,s.extra)
    def test_sequential_allows_early_live_and_overtime_while_favorites_blocks_both(self):
        for end in (18000,9900):
            raw,m,l=inputs();raw['expected_expiration_time']=end
            gate=live_gate(raw,m,l,10000,late_hours=None);self.assertTrue(gate['sports_live'])
            e=fixture.Engine(fixture.QuietAudit());e.now=10000
            seq=SequentialStrategy(e,dict(fixture.profile('KXNBAGAME'),asset='sports'),PairModel())
            fav=FavoritesStrategy(e,dict(fixture.profile('KXNBAGAME',strategy='favorites'),asset='sports'))
            self.assertTrue(seq.entry_allowed(gate,10000));self.assertFalse(fav.entry_allowed(gate,10000))
            gate['sports_live']=False;self.assertFalse(seq.entry_allowed(gate,10000))
    def test_retired_favorites_block_entries_but_keep_risk_exit_permissions(self):
        e=fixture.Engine(fixture.QuietAudit());e.now=200
        b=FavoritesStrategy(e,dict(fixture.profile(strategy='favorites'),retired=True))
        t='KXBTC15M-TEST';fixture.market(e,t,yes='.79',no='.19')
        b.step();self.assertFalse(e.orders)
        self.assertTrue(b.exit_allowed(Mock(ticker=t)))
    def test_pausing_one_profile_does_not_cancel_another_profiles_entries(self):
        s,rows=self.suite();e,f,ps=s.portfolios['sequential'];e.advance(200)
        t='KXHIGHNY-TEST';fixture.market(e,t);e.place(t,'yes','buy',D(1),D('.45'));e.advance(201)
        rows[0]['progress']['desired']='paused';s.control(rows)
        self.assertFalse(e.pending)

class HourlyDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_hourly_frequency_is_required_and_15m_is_rejected(self):
        s,rows=ScopeTests().suite();host=Mock();host.experiments=s;host.engine.markets={};host.put=AsyncMock()
        host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        now=time.time();date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        frequency='15_min'
        def call(method,path,query=None):
            if path.startswith('/series/'):return dict(series=dict(frequency=frequency))
            series=query['series_ticker']
            return dict(markets=[dict(ticker=series+'-TEST',event_ticker='EVENT',status='active',open_time=date(now-100),close_time=date(now+1800),yes_bid=80)])
        host.verified_data.call.side_effect=call
        await hourly_once(host);host.put.assert_not_awaited()
        s.hourly_metadata={};s.hourly_retry_at={}
        original=s.enabled_profiles
        s.enabled_profiles=lambda asset:original(asset)[:1]
        frequency='hourly';await hourly_once(host);host.put.assert_awaited_once()
        source,payload=host.put.await_args.args;self.assertEqual(source,'hourly_market')
        s.handle(source,payload,time.time());t=payload['market']['ticker']
        self.assertIn(t,s.portfolios['favorites'][0].markets);self.assertNotIn(t,s.portfolios['sequential'][0].markets)

@unittest.skipUnless(pg.URL,'Disposable PostgreSQL required')
class ScopeMigration(unittest.TestCase):
    setUp=fixture.FolderPostgres.setUp;tearDown=fixture.FolderPostgres.tearDown;seed=fixture.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):fixture.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.FolderPostgres.tearDownClass.__func__(cls)
    def test_scope_preserves_sessions_and_prevents_retired_resume(self):
        self.seed();initialize_weather(self.demo,lambda:None);initialize_sports(self.demo,lambda:None)
        before={r['parameters']['id']:r['progress'] for r in self.demo.rows('shadow/folder/',10)}
        initialize_scope(self.demo,lambda:None);initialize_scope(self.demo,lambda:None)
        rows=self.demo.rows('shadow/bot/',200);self.assertEqual(len(rows),154)
        retired=[r for r in rows if r['parameters'].get('retired')]
        self.assertEqual(len(retired),28)
        self.assertTrue(all(r['progress']['desired']=='paused' for r in retired))
        self.assertEqual(before,{r['parameters']['id']:r['progress'] for r in self.demo.rows('shadow/folder/',10)})
        self.assertEqual(self.client.post('/demo/shadow/bulk',json=dict(action='resume',folder_id='favorites')).status_code,200)
        self.assertTrue(all(self.demo.get('shadow/bot/'+r['parameters']['id'])['progress']['desired']=='paused' for r in retired))
        r=retired[0]
        self.assertEqual(self.client.post('/demo/shadow/bots/'+r['parameters']['id'],json=dict(revision=r['parameters']['revision'],desired='running')).status_code,409)
        data=self.client.get('/demo/shadow/workspace').json();self.assertEqual(len(data['bots']),154)

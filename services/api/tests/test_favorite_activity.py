"""New discovery capacity and verified recovery without rewriting gap history."""
import unittest,time
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock
from datetime import datetime,timezone
from services.api.tests import test_favorite_maker_entries as maker_fixture
from services.api.tests.test_strategy_folders import market,profile,QuietAudit
from services.api.tests import test_weather_favorites as weather_fixture
from services.paper_demo.shadow.core import Engine
from services.paper_demo.shadow.state import encode,restore
from services.paper_demo.shadow.experiments import ExperimentFleet
from services.paper_demo.shadow.sequential import PairModel
from services.paper_demo.shadow.discovery_budget import candidate_markets,next_profile
from services.paper_demo.shadow.weather import weather_once
from services.paper_demo.shadow.monitoring import MonitoringBudget


def snapshot(ticker,seq=1):
    return dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker=ticker,
        yes_dollars_fp=[['.79','100']],no_dollars_fp=[['.19','100']]))

class Recovery(unittest.TestCase):
    def test_gap_needs_full_snapshot_and_never_relabels_history(self):
        e,b,book=maker_fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        e.data_gap(maker_fixture.MakerEntries.ticker,'stream disconnected');e.advance(202)
        b.step();self.assertFalse(any(o.status=='pending' for o in e.orders.values()))
        book.valid=True;book.at=202;b.step() # Merely touching data is insufficient.
        self.assertFalse(any(o.status=='pending' for o in e.orders.values()))
        e.handle('kalshi',snapshot(maker_fixture.MakerEntries.ticker),203)
        self.assertTrue(any(o.status=='pending' for o in e.orders.values()))
        self.assertFalse(e.wallet.stat(maker_fixture.MakerEntries.ticker).valid)
        self.assertIn('stream disconnected',e.gap_reasons[maker_fixture.MakerEntries.ticker])
        e.data_gap(maker_fixture.MakerEntries.ticker,'new gap');self.assertEqual(book.snapshot_at,0)

    def test_fresh_snapshot_does_not_override_pause_or_explicit_halt(self):
        for paused in (True,False):
            e,b,book=maker_fixture.MakerEntries().setup_bot()
            e.data_gap(maker_fixture.MakerEntries.ticker,'gap')
            if paused:b.enabled=False
            else:b.halted.add(maker_fixture.MakerEntries.ticker)
            e.handle('kalshi',snapshot(maker_fixture.MakerEntries.ticker),201)
            self.assertFalse(e.orders)

    def test_restart_waits_for_verified_snapshot_then_clears_only_recovery_halt(self):
        p=profile(series='KXBTCD',strategy='favorites');t=maker_fixture.MakerEntries.ticker
        e=Engine(QuietAudit());e.advance(200);f=ExperimentFleet(e,[p],PairModel())
        market(e,t,yes='.79',no='.19');saved=encode(e,f)
        fresh=Engine(QuietAudit());ff=ExperimentFleet(fresh,[p],PairModel())
        restore(fresh,ff,saved)
        self.assertIn(t,ff.halted);ff.step();self.assertFalse(fresh.orders)
        fresh.handle('kalshi',snapshot(t),201)
        self.assertNotIn(t,ff.halted);self.assertTrue(fresh.orders)
        self.assertFalse(fresh.wallet.stat(t).valid)

    def test_pending_cancellation_is_not_revived_by_lease_renewal(self):
        e,b,book=maker_fixture.MakerEntries().setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.cancel(o.id)
        b.step();e.advance(202)
        self.assertEqual(o.status,'cancelled')

class Discovery(unittest.TestCase):
    def test_owned_market_keeps_subscription_without_consuming_candidate_slot(self):
        suite,_=weather_fixture.WeatherSuite().suite();e,_,_=suite.portfolios['favorites'];e.now=200
        t='KXHIGHNY-held';market(e,t);e.markets[t]['weather_category']='weather_daily'
        e.wallet.fill(t,'yes','buy',D(1),D('.8'),D(0),1,'test')
        self.assertEqual(candidate_markets(suite,suite.feed_markets(),'weather_daily',200),[])
        self.assertIn(t,suite.feed_markets())

    def test_idle_unfilled_candidate_rotates_despite_extended_entry_window(self):
        suite,_=weather_fixture.WeatherSuite().suite();e,f,ps=suite.portfolios['favorites'];e.now=1000
        t='KXHIGHNY-idle';market(e,t,close=10000)
        e.markets[t].update(weather_category='weather_daily',discovered_at=100,bot_id='fav_kxhighny')
        f.bots['KXHIGHNY'].attempts[t]=dict(first=False,recorded=False,entry_deadline=9000)
        suite.extra[t]=t;suite.maintain()
        self.assertNotIn(t,e.markets)

    def test_discovery_budget_expands_but_remains_bounded(self):
        suite,_=weather_fixture.WeatherSuite().suite();suite.monitoring=MonitoringBudget()
        for now in range(0,241,5):suite.monitoring.observe(now,0,.01,1)
        self.assertEqual(suite.monitoring_snapshot(240)['total'],48)
        e=suite.portfolios['favorites'][0]
        for i in range(19):
            t='KXHIGHNY-'+str(i);market(e,t,close=1000)
            e.markets[t]['weather_category']='weather_daily';suite.extra[t]=t
        self.assertTrue(suite.extra_capacity(['last'],240))
        self.assertFalse(suite.extra_capacity(['last','overflow'],240))
        suite.monitoring.observe(245,600,.01,1)
        self.assertFalse(suite.extra_capacity(['last'],245))

    def test_rotation_serves_unrepresented_series_first(self):
        choices=[dict(series='A'),dict(series='B'),dict(series='C')]
        p,c=next_profile(None,choices,['A-live','B-live'],0)
        self.assertEqual((p['series'],c),('C',3))
        self.assertEqual(next_profile(None,choices,['A-live','B-live','C-live'],0),(None,0))

    def test_unrelated_feed_event_does_not_check_every_portfolios_fee(self):
        suite,_=weather_fixture.WeatherSuite().suite();e,_,_=suite.portfolios['favorites'];e.now=200
        for i in range(20):market(e,'KXHIGHNY-'+str(i))
        suite.host.verified_fees=Mock();suite.host.verified_fees.schedule.return_value=('quadratic',1)
        suite.prepare(e,'kalshi',dict(type='orderbook_delta',msg=dict(market_ticker='OTHER')),200)
        suite.host.verified_fees.schedule.assert_not_called()
        suite.prepare(e,'kalshi',dict(type='orderbook_snapshot',msg=dict(market_ticker='KXHIGHNY-0')),200)
        suite.host.verified_fees.schedule.assert_called_once_with('KXHIGHNY-0',200)
        suite.host.verified_fees.schedule.reset_mock();suite.prepare(e,'clock',{},200)
        self.assertEqual(suite.host.verified_fees.schedule.call_count,20)

class ExpandedDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_weather_discovers_a_third_series_instead_of_stopping_at_two(self):
        suite,_=weather_fixture.WeatherSuite().suite();e,f,ps=suite.portfolios['favorites'];now=time.time()
        suite.monitoring.observe(now,0,.01,1)
        ps=[p for p in ps if p.get('asset')=='weather']
        for p in ps[:2]:
            t=p['series']+'-old';market(e,t,close=now+3600)
            e.markets[t]['weather_category']='weather'
        host=Mock();host.experiments=suite;host.engine.markets={};host.put=AsyncMock()
        host.fee_policy=AsyncMock(return_value=Mock(taker_multiplier=D(1),maker_multiplier=D(0)))
        def call(method,path,query):
            s=query['series_ticker'];date=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
            return dict(markets=[dict(ticker=s+'-new',event_ticker=s+'-event',status='active',open_time=date(now-100),close_time=date(now+3600),yes_bid=80)])
        host.verified_data.call.side_effect=call
        await weather_once(host)
        weather=[c for c in host.put.await_args_list if c.args[1]['market']['weather_category']=='weather']
        self.assertEqual(len(weather),1)
        self.assertNotIn(weather[0].args[1]['market']['series_ticker'],{p['series'] for p in ps[:2]})

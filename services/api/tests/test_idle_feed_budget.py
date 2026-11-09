"""Paused empty portfolios release duplicate feed work and resnapshot on resume."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from types import SimpleNamespace
from services.api.tests.test_strategy_scope import ScopeTests
from services.api.tests.test_strategy_folders import market
from services.paper_demo.shadow.core import Lot

class IdleFeedBudget(unittest.TestCase):
    def fixture(self):
        suite,host=ScopeTests().suite();suite.host.suspend_idle_feeds=True
        for e,f,ps in suite.portfolios.values():
            for b in f.bots.values():b.enabled=False
        return suite
    def test_paused_empty_portfolios_do_not_process_depth_bursts(self):
        suite=self.fixture()
        for e,f,ps in suite.portfolios.values():e.handle=Mock()
        for n in range(200):suite.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=n,msg=dict(market_ticker='OTHER')),1000)
        for e,f,ps in suite.portfolios.values():e.handle.assert_not_called()
        suite.handle('kalshi',dict(type='market_lifecycle_v2',msg={}),1001)
        for e,f,ps in suite.portfolios.values():e.handle.assert_called_once()
    def test_paused_empty_portfolios_skip_high_frequency_clock_ticks(self):
        suite=self.fixture()
        for e,f,ps in suite.portfolios.values():e.handle=Mock()
        for n in range(100):suite.handle('clock',{},1000+n/10)
        for e,f,ps in suite.portfolios.values():e.handle.assert_not_called()
        # Lifecycle/settlement classes remain eligible even while entry work is idle.
        suite.handle('kalshi',dict(type='market_lifecycle_v2',msg={}),1011)
        for e,f,ps in suite.portfolios.values():e.handle.assert_called_once()

    def test_ticker_pause_contract_applies_to_every_strategy_owner(self):
        suite=self.fixture();ticker='KXBTC15M-test'
        for folder,(e,f,ps) in suite.portfolios.items():
            e.now=200;market(e,ticker)
            self.assertFalse(suite.ticker_feed_needed(e,f,ticker),folder)
            payload=dict(type='orderbook_snapshot',sid=11,seq=1,msg=dict(market_ticker=ticker))
            self.assertTrue(suite.skip_paused_ticker_input(e,f,'kalshi',payload,201),folder)
            self.assertFalse(e.books[ticker].valid,folder)

    def test_paused_unexposed_ticker_is_skipped_beside_exposed_ticker(self):
        suite=self.fixture();e,f,ps=suite.portfolios['favorites'];e.now=200
        held='KXBTC15M-held';idle='KXBTC15M-idle';market(e,held);market(e,idle)
        e.wallet.lots=[Lot('lot',held,'yes',D(1),D('.8'),D(0),1)]
        self.assertTrue(suite.ticker_feed_needed(e,f,held))
        self.assertFalse(suite.ticker_feed_needed(e,f,idle))
        self.assertFalse(suite.skip_paused_ticker_input(e,f,'kalshi',
            dict(type='orderbook_snapshot',sid=12,seq=1,msg=dict(market_ticker=held)),201))
        self.assertTrue(suite.skip_paused_ticker_input(e,f,'kalshi',
            dict(type='orderbook_snapshot',sid=12,seq=2,msg=dict(market_ticker=idle)),202))

    def test_running_owner_skips_expensive_exposure_scan_on_hot_feed(self):
        suite=self.fixture();e,_,_=suite.portfolios['favorites'];e.now=200
        ticker='KXBTC15M-hot';market(e,ticker)
        owner=SimpleNamespace(enabled=True,profile=dict(paused_markets=[]))
        fleet=SimpleNamespace(owner=lambda _:owner,bots={'owner':owner})
        # A running owner needs the feed regardless of unrelated held lots.
        for i in range(100):
            e.wallet.lots.append(Lot('lot'+str(i),'OTHER-'+str(i),'yes',D(1),D('.8'),D(0),1))
        with patch.object(suite,'ticker_exposed',wraps=suite.ticker_exposed) as exposed:
            self.assertTrue(suite.ticker_feed_needed(e,fleet,ticker))
            exposed.assert_not_called()

    def test_per_market_pause_releases_feed_while_category_bot_remains_running(self):
        suite=self.fixture();e,f,ps=suite.portfolios['favorites'];e.now=200
        ticker='KXBTC15M-paused';market(e,ticker)
        owner=SimpleNamespace(enabled=True,profile=dict(paused_markets=[ticker]))
        fleet=SimpleNamespace(owner=lambda _:owner,bots={'owner':owner})
        self.assertFalse(suite.ticker_feed_needed(e,fleet,ticker))
        e.wallet.lots=[Lot('lot',ticker,'yes',D(1),D('.8'),D(0),1)]
        self.assertTrue(suite.ticker_feed_needed(e,fleet,ticker))

    def test_paused_portfolio_with_exposure_keeps_feed_and_risk_processing(self):
        suite=self.fixture();e,f,ps=suite.portfolios['favorites']
        e.wallet.lots=[Lot('lot','KXBTC15M-test','yes',D(1),D('.8'),D(0),1)]
        e.handle=Mock()
        suite.handle('kalshi',dict(type='trade',msg=dict(market_ticker='KXBTC15M-test')),1000)
        e.handle.assert_called_once();self.assertFalse(suite.idle_feed(e,f))
    def test_outstanding_orders_keep_feed_until_cancellation_acknowledged(self):
        suite=self.fixture();e,f,ps=suite.portfolios['favorites'];e.now=200;market(e)
        ident=e.place('KXBTC15M-test','yes','buy',D(1),D('.1'))
        self.assertFalse(suite.idle_feed(e,f));e.cancel(ident)
        self.assertFalse(suite.idle_feed(e,f));e.advance(201)
        self.assertTrue(suite.idle_feed(e,f))
    def test_resume_requires_full_snapshot_after_idle_sequence_was_skipped(self):
        suite=self.fixture();e,f,ps=suite.portfolios['favorites'];e.now=200
        t='KXBTC15M-test';market(e,t);e.sequences[1]=1
        suite.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=2,msg=dict(market_ticker=t)),201)
        self.assertTrue(e.idle_feed_suspended)
        f.bots['KXBTC15M'].enabled=True;e.handle=Mock()
        suite.handle('book_heartbeat',dict(sid=1),202)
        self.assertFalse(e.books[t].valid);self.assertEqual(e.sequences,{})
        self.assertFalse(e.idle_feed_suspended);e.handle.assert_called_once()

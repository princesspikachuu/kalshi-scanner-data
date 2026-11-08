"""Paused empty portfolios release duplicate feed work and resnapshot on resume."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
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

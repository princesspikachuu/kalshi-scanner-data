"""Paused paper portfolios retain risk/history without cloning new market books.

These tests intentionally exercise the real ExperimentSuite routing, not a
mocked order-placement path. They do not access Kalshi or a live account.
"""
import time
import unittest
from decimal import Decimal as D

from services.api.tests.test_strategy_scope import ScopeTests
from services.api.tests.test_strategy_folders import QuietAudit, ready_suite
from services.paper_demo.shadow.core import Engine, FeePolicy
from services.paper_demo.shadow.market_maker import profiles as maker_profiles


class PausedMarketDiscoveryTests(unittest.TestCase):
    def suite(self):
        suite, rows = ScopeTests().suite()
        suite.host.suspend_idle_feeds = True
        # Collector remains active; every other strategy is paused.
        for row in rows:
            row['progress']['desired'] = (
                'running' if row['parameters'].get('folder_id') == 'favorites' else 'paused'
            )
        suite.control(rows)
        return suite, rows

    @staticmethod
    def weather(now, suffix='NEW'):
        return dict(
            market=dict(
                ticker='KXHIGHNY-' + suffix, event_ticker='WEATHER-EVENT-' + suffix,
                open=now - 60, close=now + 3600, discovered_at=now,
                weather_category='weather_daily',
            ),
            taker_multiplier='1', maker_multiplier='0',
        )

    def test_paused_folders_do_not_clone_discovered_weather_or_shared_markets(self):
        suite, _ = self.suite()
        now = time.time()
        ticker = self.weather(now)['market']['ticker']
        before = {folder: len(e.markets) for folder, (e, _, _) in suite.portfolios.items()}
        suite.handle('weather_market', self.weather(now), now)
        self.assertIn(ticker, suite.portfolios['favorites'][0].markets)
        for folder in ('sequential', 'sequential_flexible', 'sequential_adaptive',
                       'favorites_statistics', 'volatility_scalper'):
            self.assertNotIn(ticker, suite.portfolios[folder][0].markets, folder)
            self.assertEqual(len(suite.portfolios[folder][0].markets), before[folder])
        # Startup/backfill sharing must honor pauses as well.
        suite.share_external_markets()
        self.assertNotIn(ticker, suite.portfolios['sequential'][0].markets)
        self.assertGreater(suite.paused_discovery_skipped, 0)
        self.assertGreater(suite.paused_market_copies_skipped, 0)
        snapshot = suite.monitoring_snapshot(now)
        self.assertEqual(snapshot['paused_new_market_discoveries_skipped'], suite.paused_discovery_skipped)
        self.assertEqual(snapshot['paused_new_market_copies_skipped'], suite.paused_market_copies_skipped)

    def test_resuming_strategy_immediately_joins_existing_shared_market(self):
        suite, rows = self.suite()
        now = time.time()
        t = self.weather(now, 'RESUME')['market']['ticker']
        suite.handle('weather_market', self.weather(now, 'RESUME'), now)
        e, fleet, _ = suite.portfolios['sequential']
        self.assertNotIn(t, e.markets)
        before_cash = e.wallet.cash
        for row in rows:
            if row['parameters'].get('folder_id') == 'sequential' and row['parameters']['series'] == 'KXHIGHNY':
                row['progress']['desired'] = 'running'
        suite.control(rows)
        self.assertIn(t, e.markets)
        self.assertFalse(e.books[t].valid, 'resumed strategy needs its own fresh orderbook snapshot')
        self.assertTrue(fleet.bots['KXHIGHNY'].enabled)
        self.assertTrue(suite.ticker_feed_needed(e, fleet, t))
        self.assertEqual(e.wallet.cash, before_cash)
        self.assertFalse(e.wallet.lots)

    def test_paused_held_market_keeps_inventory_and_settlement_feed(self):
        suite, rows = self.suite()
        now = time.time()
        t = self.weather(now, 'HELD')['market']['ticker']
        # Register in both portfolios while running, then pause Sequential.
        for row in rows:
            if row['parameters'].get('folder_id') == 'sequential' and row['parameters']['series'] == 'KXHIGHNY':
                row['progress']['desired'] = 'running'
        suite.control(rows)
        suite.handle('weather_market', self.weather(now, 'HELD'), now)
        e, fleet, _ = suite.portfolios['sequential']
        self.assertIn(t, e.markets)
        e.wallet.fill(t, 'yes', 'buy', D('1'), D('.8'), D('0'), 1, 'held')
        original_lots = [(lot.ticker, lot.quantity) for lot in e.wallet.lots]
        original_cash = e.wallet.cash
        for row in rows:
            if row['parameters'].get('folder_id') == 'sequential' and row['parameters']['series'] == 'KXHIGHNY':
                row['progress']['desired'] = 'paused'
        suite.control(rows)
        self.assertTrue(suite.ticker_feed_needed(e, fleet, t))
        suite.handle('weather_market', self.weather(now, 'HELD'), now + 2)
        self.assertEqual([(lot.ticker, lot.quantity) for lot in e.wallet.lots], original_lots)
        self.assertEqual(e.wallet.cash, original_cash)
        self.assertIn(t, e.markets, 'pausing never discards an existing market with inventory')

    def test_legacy_15m_backfill_excludes_paused_then_joins_on_resume(self):
        suite, rows = self.suite()
        now = time.time()
        t = 'KXBTC15M-26NOV21-MT020'
        suite.host.engine.add_market(
            dict(ticker=t, event_ticker='KXBTC15M-26NOV21', open=now - 30, close=now + 900),
            FeePolicy(),
        )
        suite.share_legacy_markets()
        self.assertIn(t, suite.portfolios['favorites'][0].markets)
        self.assertNotIn(t, suite.portfolios['sequential'][0].markets)
        for row in rows:
            if row['parameters'].get('folder_id') == 'sequential' and row['parameters']['series'] == 'KXBTC15M':
                row['progress']['desired'] = 'running'
        suite.control(rows)
        e = suite.portfolios['sequential'][0]
        self.assertIn(t, e.markets)
        self.assertFalse(e.books[t].valid)

    def test_maker_market_does_not_allocate_a_paused_sibling_portfolio(self):
        from services.paper_demo.shadow.market_maker import MM_FOLDERS
        ps = [dict(profile, revision=1) for profile in maker_profiles()
              if profile['market_category'] == 'politics']
        rows = [dict(parameters=p, progress=dict(desired=(
            'running' if p['folder_id'] == 'market_maker' else 'paused'
        ))) for p in ps]
        from unittest.mock import Mock
        host = Mock()
        host.audit = QuietAudit()
        host.engine = Engine(host.audit, cash='1000')
        host.model_worker_latency = False
        host.suspend_idle_feeds = True
        suite = ready_suite(host, rows)
        now = time.time()
        t = 'MAKER-MT020'
        payload = dict(market=dict(ticker=t, event_ticker='MAKER-MT020-EVENT',
            market_maker=True, market_category='politics',
            open=now - 30, close=now + 7200, discovered_at=now),
            taker_multiplier='1', maker_multiplier='0')
        suite.handle('maker_market', payload, now)
        self.assertIn(t, suite.portfolios['market_maker'][0].markets)
        self.assertNotIn(t, suite.portfolios['maker_competitive'][0].markets)
        self.assertGreater(suite.paused_discovery_skipped, 0)
        self.assertTrue(set(MM_FOLDERS).issubset(suite.portfolios))


class PausedFavoritesTimingCacheTests(unittest.TestCase):
    def fixture(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        bot = SimpleNamespace(enabled=False, hold_only=True,
            exit_evidence=SimpleNamespace(cells={'seed': {'observations': 3}}))
        engine = SimpleNamespace(wallet=SimpleNamespace(lots=[]), orders={})
        build = Mock(side_effect=lambda cells, hold_only: [
            dict(size=len(cells), hold_only=hold_only, value=cells['seed']['observations'])
        ])
        return bot, engine, build

    def test_unchanged_paused_history_reuses_display_not_source_research(self):
        from unittest.mock import patch
        from services.paper_demo.shadow.experiments import (
            favorite_timing_status_rows, PAUSED_FAVORITE_TIMING_CACHE_SECONDS
        )
        bot, engine, build = self.fixture()
        with patch('services.paper_demo.shadow.experiments.favorite_timing_rows', build):
            first = favorite_timing_status_rows(bot, engine, 100)
            self.assertIs(first, favorite_timing_status_rows(bot, engine, 105))
            self.assertEqual(build.call_count, 1)
            self.assertEqual(PAUSED_FAVORITE_TIMING_CACHE_SECONDS, 30)
            self.assertEqual(bot.exit_evidence.cells, {'seed': {'observations': 3}})
            bot.exit_evidence.cells['seed']['observations'] = 4
            self.assertIsNot(first, favorite_timing_status_rows(bot, engine, 131))
            self.assertEqual(build.call_count, 2)

    def test_research_shape_and_policy_changes_invalidate_before_ttl(self):
        from unittest.mock import patch
        from services.paper_demo.shadow.experiments import favorite_timing_status_rows
        bot, engine, build = self.fixture()
        with patch('services.paper_demo.shadow.experiments.favorite_timing_rows', build):
            favorite_timing_status_rows(bot, engine, 100)
            bot.exit_evidence.cells['new'] = {'observations': 1}
            favorite_timing_status_rows(bot, engine, 101)
            bot.hold_only = False
            favorite_timing_status_rows(bot, engine, 102)
        self.assertEqual(build.call_count, 3)

    def test_resumed_or_exposed_portfolios_never_use_paused_display_cache(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from services.paper_demo.shadow.experiments import favorite_timing_status_rows
        bot, engine, build = self.fixture()
        with patch('services.paper_demo.shadow.experiments.favorite_timing_rows', build):
            favorite_timing_status_rows(bot, engine, 100)
            engine.wallet.lots = [object()]
            favorite_timing_status_rows(bot, engine, 101)
            engine.wallet.lots = []
            engine.orders['active'] = SimpleNamespace(status='resting')
            favorite_timing_status_rows(bot, engine, 102)
            engine.orders.clear()
            bot.enabled = True
            favorite_timing_status_rows(bot, engine, 103)
        self.assertEqual(build.call_count, 4)
        self.assertFalse(hasattr(bot, '_paused_favorite_timing'))



if __name__ == '__main__':
    unittest.main()

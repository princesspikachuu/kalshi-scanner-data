"""Paused research views can be reused without caching wallet execution state."""
import unittest
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import Mock

from services.paper_demo.shadow.experiments import (
    PAUSED_SCALPER_STATUS_CACHE_SECONDS, scalper_status_snapshot,
)


class PausedScalperStatusCacheTests(unittest.TestCase):
    def fixture(self):
        bot = SimpleNamespace(
            enabled=False,
            config={'approach': 'fixed', 'maker_profit_exits': False},
            research={'totals': {'completed': 1, 'net': 4}, 'cells': {'a': {}}, 'recent': []},
            research_snapshot=Mock(side_effect=lambda: {'snapshot': object()}),
        )
        engine = SimpleNamespace(
            wallet=SimpleNamespace(cash=D(100), deposits=D(100), lots=[]),
            orders={}, tape=SimpleNamespace(calculations=2),
        )
        return bot, engine

    def test_idle_reuses_snapshot_for_30_seconds(self):
        bot, engine = self.fixture()
        first = scalper_status_snapshot(bot, engine, 100)
        self.assertEqual(first, scalper_status_snapshot(bot, engine, 105))
        self.assertEqual(bot.research_snapshot.call_count, 1)
        self.assertIsNot(first, scalper_status_snapshot(bot, engine, 131))
        self.assertEqual(bot.research_snapshot.call_count, 2)
        self.assertEqual(PAUSED_SCALPER_STATUS_CACHE_SECONDS, 30)

    def test_recomputes_after_research_or_wallet_change(self):
        bot, engine = self.fixture()
        scalper_status_snapshot(bot, engine, 100)
        bot.research['totals']['completed'] = 2
        scalper_status_snapshot(bot, engine, 101)
        engine.wallet.cash = D(99)
        scalper_status_snapshot(bot, engine, 102)
        engine.tape.calculations += 1
        refreshed = scalper_status_snapshot(bot, engine, 103)
        self.assertEqual(refreshed['shared_feature_calculations'], 3)
        self.assertEqual(bot.research_snapshot.call_count, 3)

    def test_unrelated_tape_activity_does_not_rebuild_heavy_research(self):
        bot, engine = self.fixture()
        scalper_status_snapshot(bot, engine, 100)
        for i in range(100):
            engine.tape.calculations += 1
            view = scalper_status_snapshot(bot, engine, 100+i*.1)
            self.assertEqual(view['shared_feature_calculations'], 3+i)
        self.assertEqual(bot.research_snapshot.call_count, 1)

    def test_position_order_and_running_bot_bypass_cache(self):
        bot, engine = self.fixture()
        scalper_status_snapshot(bot, engine, 100)
        engine.wallet.lots = [object()]
        scalper_status_snapshot(bot, engine, 101)
        engine.wallet.lots = []
        engine.orders['active'] = SimpleNamespace(status='resting')
        scalper_status_snapshot(bot, engine, 102)
        engine.orders.clear()
        bot.enabled = True
        scalper_status_snapshot(bot, engine, 103)
        self.assertEqual(bot.research_snapshot.call_count, 4)
        self.assertFalse(hasattr(bot, '_paused_scalper_status'))

    def test_config_and_reset_invalidate(self):
        bot, engine = self.fixture()
        scalper_status_snapshot(bot, engine, 100)
        bot.config['maker_profit_exits'] = True
        scalper_status_snapshot(bot, engine, 101)
        bot.research = {'totals': {'completed': 0, 'net': 0},
                        'cells': {}, 'recent': []}
        scalper_status_snapshot(bot, engine, 102)
        self.assertEqual(bot.research_snapshot.call_count, 3)


if __name__ == '__main__':
    unittest.main()

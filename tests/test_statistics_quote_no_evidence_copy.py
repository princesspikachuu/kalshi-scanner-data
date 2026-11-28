"""Avoid allocating the full shared evidence dictionary for every statistics quote."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.paper_demo.shadow.statistics_favorites import StatisticsFavoritesStrategy


class StatisticsQuoteHotPathTests(unittest.TestCase):
    def test_cached_groups_avoid_per_quote_source_copy(self):
        strategy = StatisticsFavoritesStrategy.__new__(StatisticsFavoritesStrategy)
        strategy.e = SimpleNamespace(log=Mock())
        strategy.profile = {"series": "KXTEST"}
        strategy.contracts = 2
        strategy.decisions = {}
        strategy.decision_counts = {}
        strategy._decision_signatures = {}
        groups = {("global", ()): {"events": {"event": 1}}}
        strategy.statistics_groups = Mock(return_value=groups)
        strategy._source_cells = Mock(side_effect=AssertionError("raw cells should not be re-copied"))
        with patch("services.paper_demo.shadow.statistics_favorites.statistics_quote",
                   return_value=(None, {"reason": "no_valid_maker_spread", "samples": 0})) as quote:
            self.assertIsNone(strategy.entry_quote("EXAMPLE", "yes"))
        strategy._source_cells.assert_not_called()
        quote.assert_called_once_with(strategy.e, strategy.profile, 2, "EXAMPLE", "yes",
                                      {}, None, groups)
        self.assertEqual(strategy.decision_counts["no_valid_maker_spread"], 1)
        strategy.e.log.assert_called_once()


if __name__ == "__main__":
    unittest.main()

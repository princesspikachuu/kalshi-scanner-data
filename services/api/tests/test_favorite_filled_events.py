"""MT-031: actual regular Favorites BUY-fill event counts, never order/contract counts."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from services.paper_demo.shadow.favorite_filled_events import (
    FavoriteFilledEvents, category_for,
)


class FavoriteFilledEventsTests(unittest.TestCase):
    profiles = [
        dict(id='wx1', series='KXHIGHNY', asset='weather_daily'),
        dict(id='wx2', series='KXHIGHCHI', asset='weather_daily'),
        dict(id='btc', series='KXBTC15M', asset='crypto'),
    ]

    def fill(self, tracker, now, bot='wx1', event='KXHIGHNY-26NOV21'):
        tracker.observe(SimpleNamespace(action='buy'), now, dict(
            bot_id=bot, event_ticker=event))

    def test_filled_events_deduplicate_contracts_partials_and_related_bots(self):
        tracker = FavoriteFilledEvents(now=1000)
        self.fill(tracker, 4600)
        self.fill(tracker, 4610)
        self.fill(tracker, 4620, 'wx2')
        self.fill(tracker, 4625, 'btc', 'KXBTC15M-26NOV21T1700')
        not_a_fill = SimpleNamespace(action='sell')
        tracker.observe(not_a_fill, 4650, dict(
            bot_id='wx1', event_ticker='unrelated-sell'))
        reports = tracker.report(4700, self.profiles)
        self.assertEqual(reports['by_bot']['wx1']['1H']['count'], 1)
        self.assertEqual(reports['by_bot']['wx2']['1H']['count'], 1)
        self.assertEqual(reports['by_category']['weather-daily']['1H']['count'], 1)
        self.assertEqual(reports['by_category']['crypto-15m']['1H']['count'], 1)
        self.assertEqual(reports['total']['1H']['count'], 2)
        self.assertTrue(reports['total']['1H']['complete'])
        self.assertEqual(reports['total']['24H']['count'], 2)
        self.assertFalse(reports['total']['24H']['complete'])
        self.assertNotIn('KXHIGHNY-26NOV21', str(reports))

    def test_periods_change_with_actual_fill_timestamps_not_settlement(self):
        tracker = FavoriteFilledEvents(now=2000)
        self.fill(tracker, 2010, event='earlier')
        self.fill(tracker, 5600, event='newer')
        reports = tracker.report(5700, self.profiles, {
            'wx1': {'historic-verified-settled'},
        })
        self.assertEqual(reports['by_bot']['wx1']['all']['count'], 3)
        self.assertFalse(reports['by_bot']['wx1']['all']['complete'])
        self.assertEqual(reports['by_bot']['wx1']['1H']['count'], 1)
        self.assertEqual(reports['by_bot']['wx1']['6H']['count'], 2)
        self.assertEqual(reports['by_bot']['wx1']['24H']['count'], 2)
        self.assertTrue(reports['by_bot']['wx1']['1H']['complete'])
        self.assertFalse(reports['by_bot']['wx1']['6H']['complete'])
        self.assertNotIn('historic-verified-settled',
                         str(reports['by_bot']['wx1']['1H']))

    def test_state_round_trip_preserves_identity_and_source_immutability(self):
        tracker = FavoriteFilledEvents(now=1000)
        self.fill(tracker, 2000, 'wx1', 'one')
        self.fill(tracker, 2100, 'wx2', 'one')
        state = tracker.export()
        original = deepcopy(state)
        restored = FavoriteFilledEvents(state, now=2500)
        self.assertEqual(restored.export(), original)
        self.fill(restored, 2600, 'wx1', 'one')
        self.assertEqual(state, original)
        self.assertEqual(restored.report(2650, self.profiles)
                         ['by_category']['weather-daily']['all']['count'], 1)
        self.assertEqual(restored.report(2650, self.profiles)
                         ['by_bot']['wx1']['all']['count'], 1)
        self.assertEqual(restored.report(2650, self.profiles)
                         ['by_bot']['wx2']['all']['count'], 1)

    def test_missing_event_identity_never_becomes_fabricated_zero(self):
        tracker = FavoriteFilledEvents(now=3000)
        tracker.observe(SimpleNamespace(action='buy'), 3100,
                        dict(bot_id='wx1'))
        result = tracker.report(9000, self.profiles)
        self.assertFalse(result['total']['1H']['complete'])
        self.assertEqual(result['total']['1H']['count'], 0)
        self.assertEqual(result['unknown_fill_events'], 1)

    def test_bounded_retention_discloses_truncated_window(self):
        with patch('services.paper_demo.shadow.favorite_filled_events.MAX_TRACKED_EVENTS', 2):
            tracker = FavoriteFilledEvents(now=1000)
            self.fill(tracker, 1500, event='a')
            self.fill(tracker, 1600, event='b')
            self.fill(tracker, 1700, event='c')
            self.assertEqual(len(tracker.events), 2)
            report = tracker.report(2000, self.profiles)
            self.assertEqual(report['total']['all']['count'], 2)
            self.assertFalse(report['total']['1H']['complete'])
            self.assertNotIn('a', str(report))
            reloaded = FavoriteFilledEvents(tracker.export(), now=2000)
            self.assertEqual(reloaded.export(), tracker.export())

    def test_market_types_match_regular_dashboard_grouping(self):
        self.assertEqual(category_for(self.profiles[0]), 'weather-daily')
        self.assertEqual(category_for(dict(series='KXBTC15M', asset='crypto')),
                         'crypto-15m')
        self.assertEqual(category_for(dict(series='KXBTCH', asset='hourly')),
                         'crypto-hourly')
        self.assertEqual(category_for(dict(series='KXWTIH', asset='hourly')),
                         'commodities-hourly')
        self.assertEqual(category_for(dict(series='KXUSDCADH', asset='hourly')),
                         'finance-hourly')
        self.assertEqual(category_for(dict(series='KXNBAGAME', asset='sports')),
                         'sports')


if __name__ == '__main__':
    unittest.main()

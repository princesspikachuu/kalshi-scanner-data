"""MT-037: bounded, durable regular Favorites paper maker BUY attempt counts."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from services.paper_demo.shadow.favorite_order_attempts import (
    FavoriteOrderAttempts, category_for,
)


class FavoriteOrderAttemptsTests(unittest.TestCase):
    profiles = [
        {'id': 'hourly-btc', 'asset': 'hourly', 'series': 'KXBTCH'},
        {'id': 'hourly-eth', 'asset': 'hourly', 'series': 'KXETHH'},
        {'id': '15m-btc', 'asset': 'crypto', 'series': 'KXBTC15M'},
    ]

    def submit(self, counter, at, bot='hourly-btc', ident='order-1',
               action='buy', maker=True):
        order = SimpleNamespace(id=ident, action=action, maker=maker)
        counter.observe(order, at, {'bot_id': bot})

    def test_attempts_are_distinct_orders_not_venue_events_or_fills(self):
        counter = FavoriteOrderAttempts(now=1000)
        self.submit(counter, 4600, ident='one')
        self.submit(counter, 4600, ident='one')  # duplicate audit delivery
        self.submit(counter, 4610, ident='two')  # second bid on same event
        self.submit(counter, 4620, bot='hourly-eth', ident='three')
        self.submit(counter, 4630, bot='15m-btc', ident='four')
        self.submit(counter, 4630, ident='sell', action='sell')
        self.submit(counter, 4630, ident='taker', maker=False)
        self.submit(counter, 4630, ident='unknown', bot='')
        report = counter.report(4700, self.profiles)
        self.assertEqual(report['total']['1H']['count'], 4)
        self.assertEqual(report['by_bot']['hourly-btc']['1H']['count'], 2)
        self.assertEqual(report['by_category']['crypto-hourly']['1H']['count'], 3)
        self.assertEqual(report['by_category']['crypto-15m']['1H']['count'], 1)
        self.assertEqual(report['total']['all']['count'], 4)
        self.assertFalse(report['total']['all']['complete'])
        self.assertFalse(report['total']['1H']['complete'],
                         'unattributable submissions must mark partial coverage')
        self.assertEqual(report['unknown_submissions'], 1)
        self.assertNotIn('order-1', str(report))
        self.assertNotIn('hourly-btc', str(report['total']))

    def test_exact_time_windows_and_coverage_progression(self):
        counter = FavoriteOrderAttempts(now=1000)
        self.submit(counter, 1010, ident='old')
        self.submit(counter, 4600, ident='new')
        report = counter.report(4700, self.profiles)
        self.assertEqual(report['total']['1H']['count'], 1)
        self.assertEqual(report['total']['6H']['count'], 2)
        self.assertFalse(report['total']['1H']['complete'] is False)
        self.assertFalse(report['total']['24H']['complete'])
        self.assertEqual(counter.report(9000, self.profiles)['total']['1H']['count'], 0)

    def test_export_round_trip_and_historical_checkpoint_compatibility(self):
        counter = FavoriteOrderAttempts(now=1000)
        self.submit(counter, 1200, ident='one')
        self.submit(counter, 1300, ident='two')
        state = counter.export()
        old = deepcopy(state)
        restored = FavoriteOrderAttempts(state, now=1500)
        self.assertEqual(restored.export(), state)
        self.submit(restored, 1600, ident='one')
        self.submit(restored, 1700, ident='three')
        self.assertEqual(restored.report(1800, self.profiles)['total']['all']['count'], 3)
        self.assertEqual(state, old, 'restored tracker cannot mutate source checkpoint')
        upgrade = FavoriteOrderAttempts(None, now=1800)
        missing = upgrade.report(1810, self.profiles)
        self.assertEqual(missing['total']['1H']['count'], 0)
        self.assertFalse(missing['total']['1H']['complete'])
        self.assertTrue(upgrade.report(6000, self.profiles)['total']['1H']['complete'])

    def test_retention_pruning_marks_only_affected_windows_partial(self):
        with patch('services.paper_demo.shadow.favorite_order_attempts.MAX_TRACKED_ATTEMPTS', 2):
            counter = FavoriteOrderAttempts(now=1000)
            self.submit(counter, 1100, ident='a')
            self.submit(counter, 1200, ident='b')
            self.submit(counter, 1300, ident='c')
            self.assertEqual(len(counter.recent), 2)
            report = counter.report(1400, self.profiles)
            self.assertEqual(report['total']['all']['count'], 3)
            self.assertFalse(report['total']['1H']['complete'])
            restored = FavoriteOrderAttempts(counter.export(), now=1500)
            self.assertEqual(restored.export(), counter.export())
            self.assertEqual(restored.report(5000, self.profiles)['total']['1H']['count'], 0)
            self.assertTrue(restored.report(5000, self.profiles)['total']['1H']['complete'])

    def test_invalid_action_and_missing_identity_dont_fabricate_attempt(self):
        counter = FavoriteOrderAttempts(now=1000)
        self.submit(counter, 1200, ident='sell', action='sell')
        self.submit(counter, 1201, ident='not-maker', maker=False)
        self.submit(counter, float('nan'), ident='nonfinite')
        self.submit(counter, 1202, ident=None)
        self.assertEqual(counter.report(1300, self.profiles)['total']['all']['count'], 0)
        self.assertEqual(counter.report(1300, self.profiles)['unknown_submissions'], 1)
        self.assertFalse(counter.report(1300, self.profiles)['total']['1H']['complete'])


if __name__ == '__main__':
    unittest.main()

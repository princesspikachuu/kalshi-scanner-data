"""Preview samples are bounded and reproducible without changing full membership."""
from dataclasses import replace
import unittest

from services.research.sample import select_preview_candidates
from test_evidence import CANDIDATE


def market(series, event, strike, minute=0):
    return replace(CANDIDATE, series=series, event_ticker=event,
                   ticker=f'{series}-{event}-{strike}',
                   close_time=f'2026-10-25T12:{minute:02d}:00Z')


class PreviewSampleTests(unittest.TestCase):
    def test_spreads_first_picks_by_series_and_event_and_is_permutation_independent(self):
        full = tuple(market(series, f'E{i}', strike, i % 60)
                     for series in ('A', 'B', 'C') for i in range(20) for strike in range(3))
        selected = select_preview_candidates(full, limit=30)
        self.assertEqual(len(selected), 30)
        self.assertEqual({series: sum(c.series == series for c in selected) for series in ('A', 'B', 'C')},
                         {'A': 10, 'B': 10, 'C': 10})
        self.assertEqual(len({(c.series, c.event_ticker) for c in selected}), 30)
        self.assertEqual([c.ticker for c in selected],
                         [c.ticker for c in select_preview_candidates(reversed(full), limit=30)])
        self.assertTrue(all(any(c is original for original in full) for c in selected))
        self.assertEqual(len(full), 180)

    def test_extra_strikes_are_unique_and_cap_cannot_exceed_one_hundred(self):
        full = tuple(market('A', f'E{event}', strike) for event in range(4) for strike in range(35))
        selected = select_preview_candidates(full)
        self.assertEqual(len(selected), 100)
        self.assertEqual(len({c.ticker for c in selected}), 100)
        self.assertEqual(len({c.event_ticker for c in selected}), 4)
        self.assertEqual(len(select_preview_candidates(full, limit=2)), 2)
        for bad in (0, 101, True):
            with self.assertRaises(ValueError):
                select_preview_candidates(full, limit=bad)

    def test_shortfall_and_duplicate_membership_are_explicit(self):
        full = (market('A', 'E1', 1), market('B', 'E2', 1))
        self.assertEqual(select_preview_candidates(full, limit=100), full)
        self.assertEqual(select_preview_candidates((), limit=100), ())
        with self.assertRaises(ValueError):
            select_preview_candidates(full + (full[0],))
        with self.assertRaises(ValueError):
            select_preview_candidates((replace(full[0], close_time='2026-10-25T12:00:00'),))

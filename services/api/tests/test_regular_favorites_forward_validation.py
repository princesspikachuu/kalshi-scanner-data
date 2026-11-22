"""MT-033: fixed, future-only regular Favorites held-ROI validation."""
import copy
import unittest
from decimal import Decimal as D

from services.paper_demo.shadow.favorite_forward_validation import (
    summarize_forward_regular_favorites, FROZEN_COHORTS,
)
from services.paper_demo.shadow.regular_favorites_hold_research import (
    regular_favorites_held_bots,
)


def _row(event, win, *, price='.70', horizon='10–15m', estimated=False,
         market_type='15m_price', cost=None, net=None, outcome_known=True):
    amount = D(price) if cost is None else D(str(cost))
    proceeds = D(int(win)) - amount if net is None else D(str(net))
    return dict(
        market_type=market_type, clock='market_close', price=price,
        horizon=horizon, contracts='1', cost=str(amount), resolved='1',
        winners='1' if win else '0', unverified='0', net=str(proceeds),
        outcome_events={event: int(win)} if outcome_known else {},
        return_events={event: dict(cost=str(amount), net=str(proceeds),
                                   estimated=estimated)},
        return_policy='hold_only',
    )


class ForwardRegularFavoritesValidationTests(unittest.TestCase):
    def summarize(self, rows, asset='hourly', series='KXGOLD15M'):
        bots = {'bot': {'entry_timing': rows}}
        profiles = {'bot': dict(asset=asset, series=series)}
        snapshot = copy.deepcopy(bots)
        held = regular_favorites_held_bots(bots)
        out = summarize_forward_regular_favorites(
            held, profiles,
            lambda p: ('commodities-15m' if p['series'] == 'KXGOLD15M'
                       else 'crypto-15m' if p['series'] == 'KXBTC15M'
                       else 'finance-15m'),
        )
        self.assertEqual(bots, snapshot)
        self.assertEqual(tuple((c['category'], c['price_band_cents'], c['time_bucket'])
                               for c in out['cells']), FROZEN_COHORTS)
        return out['cells']

    def test_past_and_cutoff_events_never_validate_future(self):
        rows = [_row('KXGOLD15M-26NOV211030', True),
                _row('KXGOLD15M-26NOV221030', False),
                _row('KXGOLD15M-26NOV231030', True),
                _row('bad-date-code', True)]
        cell = self.summarize(rows)[0]
        self.assertEqual(cell['independent_held_return_events'], 1)
        self.assertEqual(cell['historical_cohort_appearances_excluded'], 2)
        self.assertEqual(cell['unparseable_cohort_appearances_excluded'], 1)
        self.assertEqual(cell['confidence_status'], 'under_minimum')
        self.assertIsNone(cell['held_roi_ci90_low_pct'])

    def test_different_prices_and_horizons_do_not_contaminate_frozen_cell(self):
        rows = [_row('KXGOLD15M-26NOV231030', True),
                _row('KXGOLD15M-26NOV231045', True, price='.75'),
                _row('KXGOLD15M-26NOV231100', True, horizon='5–10m'),
                _row('KXGOLD15M-26NOV231115', True, price='.80')]
        cells = self.summarize(rows)
        self.assertEqual([r['independent_held_return_events'] for r in cells], [1, 1, 0, 0])

    def test_one_exchange_event_across_repeated_rows_is_one_return(self):
        event = 'KXGOLD15M-26NOV231030'
        rows = [_row(event, True, cost='.70', net='.30'),
                _row(event, True, cost='.70', net='.30')]
        cell = self.summarize(rows)[0]
        self.assertEqual(cell['resolved_events'], 1)
        self.assertEqual(cell['independent_held_return_events'], 1)
        self.assertEqual(D(cell['held_roi_mean_pct']), D(100) * D('.60')/D('1.40'))

    def test_unknown_outcomes_and_incomplete_cost_never_count(self):
        rows = [_row('KXGOLD15M-26NOV231030', True, outcome_known=False),
                _row('KXGOLD15M-26NOV231045', False)]
        rows[1]['return_events'] = {'KXGOLD15M-26NOV231045': {'cost': 'NaN', 'net': '-.70'}}
        cell = self.summarize(rows)[0]
        self.assertEqual(cell['resolved_events'], 1)
        self.assertEqual(cell['incomplete_settled_events'], 1)
        self.assertEqual(cell['independent_held_return_events'], 0)

    def test_exactly_fifty_future_event_returns_enable_nominal_interval(self):
        rows = [_row(f'KXGOLD15M-26NOV23{i//60:02d}{i%60:02d}',
                     i < 35, estimated=i % 3 == 0)
                for i in range(50)]
        before = self.summarize(rows[:-1])[0]
        after = self.summarize(rows)[0]
        self.assertEqual(before['independent_held_return_events'], 49)
        self.assertEqual(before['confidence_status'], 'under_minimum')
        self.assertIsNone(before['held_roi_ci90_low_pct'])
        self.assertEqual(after['independent_held_return_events'], 50)
        self.assertEqual(after['estimated_held_return_events'], 17)
        self.assertEqual(after['confidence_status'], 'available')
        self.assertLess(D(after['held_roi_ci90_low_pct']), D(after['held_roi_mean_pct']))
        self.assertGreater(D(after['held_roi_ci90_high_pct']), D(after['held_roi_mean_pct']))

    def test_fifty_winners_are_not_fake_zero_uncertainty(self):
        rows = [_row(f'KXGOLD15M-26NOV23{i//60:02d}{i%60:02d}', True)
                for i in range(50)]
        after = self.summarize(rows)[0]
        self.assertEqual(after['confidence_status'], 'insufficient_gain_loss_variation')
        self.assertIsNone(after['held_roi_ci90_low_pct'])

    def test_unparseable_invalid_clock_is_not_forward_event(self):
        rows = [_row('KXGOLD15M-26NOV232460', True),
                _row('KXGOLD15M-26NOV232359', False)]
        cell = self.summarize(rows)[0]
        self.assertEqual(cell['independent_held_return_events'], 1)
        self.assertEqual(cell['unparseable_cohort_appearances_excluded'], 1)


if __name__ == '__main__':
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from loss_risk import analyze_risk, summarize, boundary, wilson


def row(ticker='A', event=None, minute=10, won=0, side='yes', day='2026-10-01', bid='.65'):
    return {'date': day, 'ticker': ticker, 'event_ticker': event or ticker,
            'series': 'TEST', 'side': side, 'maker_bid': bid,
            'minutes_before_close': str(minute), 'price_band': '60-70',
            'won': str(won), 'quote_age_seconds': '0',
            'close_time': '1970-01-01T00:20:00Z'}


class ConditionalRiskTests(unittest.TestCase):
    def record(self, rows, paths, decision=5):
        scope = analyze_risk(rows, paths, 'test')
        return next(r for r in scope['records'] if r['decision_minutes_remaining'] == decision and r['minutes_before_close'] == 10)

    def test_single_quote_and_outcome_are_enough_without_future_path_or_seven_days(self):
        r = self.record([row()], {('2026-10-01', 'A'): {'close_ts': 1200, 'bars': [[900, 45, 50]]}})
        self.assertEqual(r['observed_events'], 1)
        self.assertEqual(r['bins'][0]['loss_rate_percent'], 100)
        self.assertLess(r['bins'][0]['loss_lower_percent'], 50)
        self.assertEqual(r['boundary']['status'], 'unresolved')

    def test_no_future_stale_null_or_entry_quote_is_used(self):
        for bars in ([[901, 45, 50]], [[839, 45, 50]], [[900, None, 50]], [[600, 45, 50]]):
            self.assertEqual(self.record([row()], {('2026-10-01', 'A'): {'close_ts': 1200, 'bars': bars}})['observed_events'], 0)

    def test_explicit_null_does_not_backfill_an_earlier_path_quote(self):
        bars = [[880, 40, 50], [900, None, 50]]
        self.assertEqual(self.record([row()], {('2026-10-01', 'A'): {'close_ts': 1200, 'bars': bars}})['observed_events'], 0)

    def test_no_side_and_zero_bid_remain_risk_observations(self):
        r = self.record([row(side='no', won=1)], {('2026-10-01', 'A'): {'close_ts': 1200, 'bars': [[900, 90, 0]]}})
        self.assertEqual(r['bins'][0]['mean_bid_cents'], 0)
        self.assertEqual(r['bins'][0]['losses'], 0)
        self.assertEqual(r['bins'][0]['zero_bid_events'], 1)
        self.assertIsNone(r['bins'][0]['sale_advantage_cents'])

    def test_correlated_contracts_and_repeat_dates_do_not_inflate_event_count(self):
        rows = [row('A', event='EVENT'), row('B', event='EVENT'), row('A', event='EVENT', day='2026-10-02')]
        paths = {(r['date'], r['ticker']): {'close_ts': 1200, 'bars': [[900, 45, 50]]} for r in rows}
        self.assertEqual(self.record(rows, paths)['observed_events'], 1)
        # Changing the losing labels cannot change the outcome-blind representative.
        rows[1]['won'] = '1'
        self.assertEqual(self.record(rows, paths)['bins'][0]['losses'], 1)

    def test_saved_same_side_checkpoint_reused_without_fabricating_complement_bid(self):
        rows = [row(), row(minute=5, bid='.55')]
        record = self.record(rows, {})
        self.assertEqual(record['observed_events'], 1)
        self.assertEqual(record['saved_checkpoint_events'], 1)
        self.assertAlmostEqual(record['bins'][0]['mean_bid_cents'], 55)
        rows[1]['side'] = 'no'
        self.assertEqual(self.record(rows, {})['observed_events'], 0)

    def test_saved_checkpoint_quote_freshness_is_respected(self):
        rows = [row(), row(minute=5, bid='.55')]
        rows[1]['quote_age_seconds'] = '61'
        self.assertEqual(self.record(rows, {})['observed_events'], 0)

    def test_series_are_not_silently_pooled(self):
        rows = [row(), dict(row('B'), series='OTHER')]
        paths = {(r['date'], r['ticker']): {'close_ts': 1200, 'bars': [[900, 45, 50]]} for r in rows}
        records = [r for r in analyze_risk(rows, paths, 'test')['records'] if r['decision_minutes_remaining'] == 5]
        self.assertEqual(len(records), 2)
        self.assertEqual([r['observed_events'] for r in records], [1, 1])

    def test_loss_likelihood_differs_from_sell_advantage(self):
        items = [{'bid': 55, 'won': int(i >= 5), 'entry': 65} for i in range(10)]
        b = summarize(items)[0]
        self.assertEqual(b['loss_rate_percent'], 50)
        self.assertEqual(b['sale_advantage_cents'], 3)
        # Entry cost cancels in the current sale-versus-hold comparison.
        self.assertEqual(summarize([dict(x, entry=95) for x in items])[0]['sale_advantage_cents'], 3)

    def test_crossings_are_bracketed_not_interpolated_across_missing_bins(self):
        def bin(low, rate):
            return {'bid_low_cents': low, 'bid_high_cents': low+10, 'events': 10,
                    'loss_rate_percent': rate, 'loss_lower_percent': max(0, rate-20), 'loss_upper_percent': min(100, rate+20)}
        r = boundary([bin(50, 60), bin(60, 40)])
        self.assertEqual(r['status'], 'estimated')
        self.assertEqual((r['ranges'][0]['low_cents'], r['ranges'][0]['high_cents']), (50, 70))
        self.assertFalse(r['ranges'][0]['clear_at_95_percent'])
        self.assertEqual(boundary([bin(30, 80), bin(60, 40)])['status'], 'unresolved')
        self.assertEqual(boundary([bin(40, 40), bin(50, 80), bin(60, 40)])['status'], 'ambiguous')

    def test_intervals_never_claim_zero_risk_from_zero_observed_losses(self):
        low, high = wilson(0, 10)
        self.assertAlmostEqual(low, 0)
        self.assertGreater(high, .25)


if __name__ == '__main__':
    unittest.main()

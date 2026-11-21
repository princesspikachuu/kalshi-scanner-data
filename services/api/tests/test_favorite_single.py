import unittest
from decimal import Decimal as D

from services.paper_demo.shadow.favorite_single import summarize_single


class SingleFavoritesBucketTests(unittest.TestCase):
    def row(self, event='event-a', cost='7.5', net='2.5', outcome=1,
            price='.75', horizon='5–10m', estimated=False):
        return dict(price=price, horizon=horizon,
            outcome_events={event: outcome},
            return_events={event: dict(cost=cost, net=net, estimated=estimated)})

    def summary(self, bots, profiles=None):
        profiles = profiles or {
            bot: dict(series='KXBTC15M', asset='crypto')
            for bot in bots
        }
        return summarize_single(bots, profiles,
            lambda p: 'crypto-15m' if p['series'].endswith('15M') else 'crypto-hourly')

    def test_repeated_event_in_two_price_time_cohorts_is_one_observation(self):
        a = self.row(cost='7.5', net='2.5')
        b = self.row(cost='8', net='-8', price='.80', horizon='<3m')
        result = self.summary({'btc': dict(entry_timing=[a, b])})
        for bucket in (result['rows']['crypto-15m'], result['by_bot']['btc']):
            self.assertEqual(bucket['resolved_events'], 1)
            self.assertEqual(bucket['return_observations'], 1)
            self.assertEqual(bucket['event_wins'], 1)
            self.assertEqual(D(bucket['average_return_pct']), D(100)*D('-5.5')/D('15.5'))
            self.assertIsNone(bucket['uncertainty90_pct'])

    def test_pools_distinct_events_and_estimates_actual_roi_uncertainty(self):
        bots = {'btc': dict(entry_timing=[
            self.row(), self.row('event-b', net='-7.5', outcome=0),
            self.row('event-c', net='2.5', estimated=True),
            self.row('event-d', net='-7.5', outcome=0),
        ])}
        result = self.summary(bots)['rows']['crypto-15m']
        self.assertEqual(result['return_observations'], 4)
        self.assertEqual(result['resolved_events'], 4)
        self.assertEqual(result['event_wins'], 2)
        self.assertEqual(result['estimated_return_observations'], 1)
        self.assertAlmostEqual(float(result['average_return_pct']), -33.33333333333333)
        self.assertGreater(float(result['uncertainty90_pct']), 0)
        avg = float(result['average_return_pct'])
        self.assertAlmostEqual(avg-float(result['ci90_low_pct']),float(result['uncertainty90_pct']))
        self.assertAlmostEqual(float(result['ci90_high_pct'])-avg,float(result['uncertainty90_pct']))

    def test_unattributed_or_invalid_event_in_any_cohort_is_excluded_from_roi(self):
        first = self.row()
        second = self.row(price='.85')
        second['return_events'] = {}
        invalid = self.row('event-b', cost='0', net='1')
        summary = self.summary({'btc': dict(entry_timing=[first,second,invalid])})['rows']['crypto-15m']
        self.assertEqual(summary['resolved_events'], 2)
        self.assertEqual(summary['return_observations'], 0)
        self.assertEqual(summary['incomplete_events'], 2)
        self.assertIsNone(summary['average_return_pct'])
        self.assertIsNone(summary['uncertainty90_pct'])

    def test_different_bots_same_event_count_once_per_category(self):
        bots = {'btc': dict(entry_timing=[self.row()]),
                'eth': dict(entry_timing=[self.row(cost='7',net='3')])}
        summary = self.summary(bots)
        self.assertEqual(summary['rows']['crypto-15m']['return_observations'], 1)
        self.assertEqual(summary['by_bot']['btc']['return_observations'], 1)
        self.assertEqual(summary['by_bot']['eth']['return_observations'], 1)
        self.assertAlmostEqual(float(summary['rows']['crypto-15m']['average_return_pct']),
                               100*5.5/14.5)

    def test_15_minute_and_hourly_samples_remain_separate(self):
        bots = {'short':dict(entry_timing=[self.row()]),
                'hour':dict(entry_timing=[self.row()])}
        result = self.summary(bots, {
            'short':dict(series='KXBTC15M',asset='crypto'),
            'hour':dict(series='KXBTCD',asset='hourly'),
        })
        self.assertEqual(result['rows']['crypto-15m']['return_observations'],1)
        self.assertEqual(result['rows']['crypto-hourly']['return_observations'],1)

    def test_single_unvarying_sample_or_no_sample_never_invents_precision(self):
        bots = {'btc':dict(entry_timing=[
            self.row('a'),self.row('b',cost='7.5',net='2.5'),
        ]),'empty':dict(entry_timing=[])}
        result = self.summary(bots)
        self.assertIsNone(result['by_bot']['btc']['uncertainty90_pct'])
        self.assertEqual(result['by_bot']['empty']['return_observations'],0)
        self.assertIsNone(result['by_bot']['empty']['uncertainty90_pct'])


if __name__ == '__main__':
    unittest.main()

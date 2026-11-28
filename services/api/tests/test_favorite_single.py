import unittest
from decimal import Decimal as D

from copy import deepcopy
from services.paper_demo.shadow.favorite_single import (
    summarize_single, summarize_regular_attribution_subsets,
)


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
        self.assertEqual(result['uncertainty_min_samples'], 50)
        self.assertIsNone(result['uncertainty90_pct'])
        self.assertIsNone(result['ci90_low_pct'])
        self.assertIsNone(result['ci90_high_pct'])

    def test_fifty_distinct_returns_required_before_numeric_interval(self):
        # A small number of mixed winners/losers can yield misleadingly
        # confident Student-t intervals; keep their observed mean visible.
        rows=[self.row('win-'+str(i),cost='8',net='2') for i in range(48)]
        rows.append(self.row('loss-a',cost='8',net='-8',outcome=0))
        early=self.summary({'btc':dict(entry_timing=rows)})['rows']['crypto-15m']
        self.assertEqual(early['return_observations'],49)
        self.assertGreater(D(early['average_return_pct']),0)
        self.assertIsNone(early['uncertainty90_pct'])
        rows.append(self.row('loss-b',cost='8',net='-8',outcome=0))
        enough=self.summary({'btc':dict(entry_timing=rows)})['rows']['crypto-15m']
        self.assertEqual(enough['return_observations'],50)
        self.assertEqual(enough['uncertainty_min_samples'],50)
        self.assertIsNotNone(enough['uncertainty90_pct'])
        mean=D(enough['average_return_pct'])
        error=D(enough['uncertainty90_pct'])
        self.assertGreater(error,0)
        self.assertAlmostEqual(float(mean-error),float(enough['ci90_low_pct']),places=10)
        self.assertAlmostEqual(float(mean+error),float(enough['ci90_high_pct']),places=10)

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

    def test_only_winning_returns_with_different_prices_do_not_imply_90_percent_certainty(self):
        bots={'btc':dict(entry_timing=[
            self.row('a',cost='7.5',net='2.5'),
            self.row('b',cost='8.5',net='1.5',price='.85'),
            self.row('c',cost='9',net='1',price='.90'),
        ])}
        result=self.summary(bots)['by_bot']['btc']
        self.assertEqual(result['return_observations'],3)
        self.assertGreater(D(result['average_return_pct']),D(0))
        self.assertIsNone(result['uncertainty90_pct'])
        self.assertIsNone(result['ci90_low_pct'])
        self.assertIsNone(result['ci90_high_pct'])

    def test_single_unvarying_sample_or_no_sample_never_invents_precision(self):
        bots = {'btc':dict(entry_timing=[
            self.row('a'),self.row('b',cost='7.5',net='2.5'),
        ]),'empty':dict(entry_timing=[])}
        result = self.summary(bots)
        self.assertIsNone(result['by_bot']['btc']['uncertainty90_pct'])
        self.assertEqual(result['by_bot']['empty']['return_observations'],0)
        self.assertIsNone(result['by_bot']['empty']['uncertainty90_pct'])



    def test_attribution_sensitivity_pools_events_and_excludes_partial_attribution(self):
        # One estimated cohort makes the whole repeated event estimated.
        a=self.row('repeated',cost='8',net='2')
        b=self.row('repeated',cost='8',net='-8',estimated=True,price='.85')
        c=self.row('exact-event',cost='8',net='2')
        d=self.row('estimated-event',cost='8',net='-8',estimated=True,outcome=0)
        e=self.row('missing-event',cost='8',net='2')
        f=self.row('missing-event',cost='8',net='2',price='.90')
        f['return_events']={}
        bots={'btc':dict(entry_timing=[a,b,c,d,e,f])}
        original=deepcopy(bots)
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        subset=summarize_regular_attribution_subsets(
            bots,profiles,lambda p:'crypto-15m')['crypto-15m']
        combined=self.summary(bots)['rows']['crypto-15m']
        self.assertEqual(bots,original)
        self.assertEqual(combined['resolved_events'],4)
        self.assertEqual(combined['return_observations'],3)
        self.assertEqual(combined['estimated_return_observations'],2)
        exact,estimated=subset['exact_only'],subset['estimated_only']
        self.assertEqual(exact['return_observations'],1)
        self.assertEqual(exact['positive_return_events'],1)
        self.assertEqual(exact['negative_return_events'],0)
        self.assertEqual(D(exact['average_return_pct']),25)
        self.assertEqual(estimated['return_observations'],2)
        self.assertEqual(estimated['positive_return_events'],0)
        self.assertEqual(estimated['negative_return_events'],2)
        self.assertEqual(D(estimated['average_return_pct']),D('-68.75'))
        self.assertEqual(exact['return_observations']+estimated['return_observations'],
                         combined['return_observations'])
        self.assertIsNone(exact['uncertainty90_pct'])
        self.assertIsNone(estimated['uncertainty90_pct'])

    def test_exact_only_uses_fifty_event_threshold_and_requires_gains_and_losses(self):
        rows=[self.row('exact-'+str(i),cost='8',net='2') for i in range(48)]
        rows.append(self.row('loss-one',cost='8',net='-8',outcome=0))
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        def exact():
            return summarize_regular_attribution_subsets(
                {'btc':dict(entry_timing=rows)},profiles,
                lambda p:'crypto-15m')['crypto-15m']['exact_only']
        early=exact()
        self.assertEqual(early['return_observations'],49)
        self.assertIsNone(early['uncertainty90_pct'])
        rows.append(self.row('loss-two',cost='8',net='-8',outcome=0))
        ready=exact()
        self.assertEqual(ready['return_observations'],50)
        self.assertEqual(ready['positive_return_events'],48)
        self.assertEqual(ready['negative_return_events'],2)
        self.assertIsNotNone(ready['uncertainty90_pct'])
        self.assertLess(D(ready['ci90_low_pct']),D(ready['average_return_pct']))
        self.assertGreater(D(ready['ci90_high_pct']),D(ready['average_return_pct']))
        all_wins=[self.row('win-'+str(i),cost='8',net='2') for i in range(60)]
        rows[:]=all_wins
        no_losses=exact()
        self.assertEqual(no_losses['return_observations'],60)
        self.assertIsNone(no_losses['uncertainty90_pct'])

    def test_exact_attribution_counts_one_event_per_category_not_contract(self):
        bots={'btc':dict(entry_timing=[self.row('same',cost='8',net='2')]),
              'eth':dict(entry_timing=[self.row('same',cost='16',net='4')]),
              'hour':dict(entry_timing=[self.row('same',cost='8',net='-8',outcome=0)])}
        profiles={'btc':dict(series='KXBTC15M',asset='crypto'),
                  'eth':dict(series='KXETH15M',asset='crypto'),
                  'hour':dict(series='KXBTCD',asset='hourly')}
        subset=summarize_regular_attribution_subsets(
            bots,profiles,lambda p:'crypto-15m' if p['series'].endswith('15M') else 'crypto-hourly')
        self.assertEqual(subset['crypto-15m']['exact_only']['return_observations'],1)
        self.assertEqual(subset['crypto-hourly']['exact_only']['return_observations'],1)
        self.assertEqual(D(subset['crypto-15m']['exact_only']['average_return_pct']),25)
        self.assertEqual(D(subset['crypto-hourly']['exact_only']['average_return_pct']),-100)
        self.assertEqual(subset['crypto-15m']['estimated_only']['return_observations'],0)


if __name__ == '__main__':
    unittest.main()

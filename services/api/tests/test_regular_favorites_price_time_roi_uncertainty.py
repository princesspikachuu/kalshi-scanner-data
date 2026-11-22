"""MT-032 — event-based held-ROI 90% uncertainty for regular Favorites only.

No trading-day gate: one verified exchange event is one observation in a
given cohort, even if it generated repeated fills. A separate cohort may
reuse that event; those cells must never be added as independent trials.
"""
import copy
import unittest
from decimal import Decimal as D

from services.api.shadow import favorite_collector_timed_totals
from services.paper_demo.shadow.favorite_single import (
    MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
    summarize_single,
)
from services.paper_demo.shadow.favorite_wide import summarize_wide
from services.paper_demo.shadow.observation_returns import summarize_regular_held_events
from services.paper_demo.shadow.regular_favorites_hold_research import regular_favorites_held_bots


def settled(event, *, win, price='.75', policy='hold_only', estimated=False,
            recorded_net=None, horizon='5–10m', contracts='1', cost=None):
    cost = D(cost) if cost is not None else D(price)*D(contracts)
    quantity = D(contracts)
    net = quantity*D(int(win))-cost if recorded_net is None else D(recorded_net)
    return dict(
        series='KXBTC15M', market_type='15m_price',clock='market_close',
        price=price,horizon=horizon,contracts=str(contracts),cost=str(cost),
        net=str(net),resolved=str(contracts),winners=str(contracts if win else '0'),
        outcome_events={event:int(win)},
        return_events={event:dict(cost=str(cost),net=str(net),estimated=estimated)},
        return_policy=policy,
    )


def regular_reports(rows):
    bots={'btc':dict(entry_timing=rows)}
    profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
    held=regular_favorites_held_bots(bots)
    detailed=favorite_collector_timed_totals(held,profiles,held_view=True)['rows']['crypto-15m']
    wider=summarize_wide(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m']
    single=summarize_single(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m']
    return detailed,wider,single


class RegularFavoritesPriceTimeROIConfidenceTests(unittest.TestCase):
    def test_one_event_return_count_not_contract_count(self):
        repeats={
            'KXBTC15M-26NOV201200':dict(cost='7.50',net='2.50',estimated=True),
            'KXBTC15M-26NOV201215':dict(cost='.75',net='-.75'),
        }
        sample=summarize_regular_held_events(repeats)
        self.assertEqual(sample['return_observations'],2)
        self.assertEqual(sample['estimated_return_observations'],1)
        self.assertEqual(sample['uncertainty_min_samples'],50)
        self.assertIsNone(sample['uncertainty90_pct'])
        self.assertEqual(sample['roi_interval_status'],'under_minimum')

    def test_exactly_fifty_distinct_events_matches_single_in_all_three_views(self):
        # All 50 different exchange events share a single market date. A
        # calendar-day minimum must NOT suppress event-level uncertainty.
        rows=[settled(f'KXBTC15M-26NOV20{i:04d}',win=i<40)
              for i in range(50)]
        before=copy.deepcopy(rows)
        detailed,wider,single=regular_reports(rows)
        self.assertEqual(rows,before,'the API summary is read only')
        self.assertEqual(len(detailed),1)
        self.assertEqual(len(wider),1)
        for r in (detailed[0],wider[0],single):
            self.assertEqual(r['return_observations'],50)
            self.assertEqual(r['estimated_return_observations'],0)
            self.assertIsNotNone(r['uncertainty90_pct'])
            self.assertLess(D(r['ci90_low_pct']),D(r['average_return_pct']))
            self.assertGreater(D(r['ci90_high_pct']),D(r['average_return_pct']))
        for r in (detailed[0],wider[0]):
            self.assertEqual(r['roi_interval_status'],'available')
            self.assertEqual(D(r['average_return_pct']),D(single['average_return_pct']))
            self.assertAlmostEqual(float(D(r['uncertainty90_pct'])),
                                   float(D(single['uncertainty90_pct'])),places=10)
            self.assertAlmostEqual(float(D(r['ci90_low_pct'])),
                                   float(D(single['ci90_low_pct'])),places=10)

    def test_missing_settlement_and_unattributed_returns_do_not_reach_minimum(self):
        rows=[settled(f'known-{i}',win=i<35) for i in range(49)]
        # Cost evidence exists but outcome not yet confirmed.
        missing=settled('pending',win=True)
        missing['outcome_events']={}
        # Outcome is confirmed but stored event-level cost attribution is
        # explicitly invalid; never reconstruct a fabricated exact return.
        incomplete=settled('settled-but-incomplete',win=False)
        incomplete['return_events']={'settled-but-incomplete':dict(cost='NaN',net='-.75')}
        rows.extend([missing,incomplete])
        d,w,s=regular_reports(rows)
        for r in (d[0],w[0],s):
            self.assertEqual(r['return_observations'],49)
            self.assertIsNone(r['uncertainty90_pct'])
        for r in (d[0],w[0]):
            self.assertEqual(r['roi_interval_status'],'under_minimum')

    def test_numerical_error_needs_observed_both_winners_and_losers(self):
        rows=[settled(f'winner-{i}',win=True) for i in range(60)]
        d,w,s=regular_reports(rows)
        for r in (d[0],w[0]):
            self.assertEqual(r['return_observations'],60)
            self.assertIsNone(r['uncertainty90_pct'])
            self.assertIsNone(r['ci90_low_pct'])
            self.assertEqual(r['roi_interval_status'],'insufficient_gain_loss_variation')
        self.assertIsNone(s['uncertainty90_pct'])

    def test_known_historical_exit_is_hold_valued_and_original_cash_preserved(self):
        rows=[settled(f'regular-{i}',win=i<35) for i in range(49)]
        original_exit=settled('historical-exit',win=True,
                              policy='all_executions',recorded_net='-.40')
        rows.append(original_exit)
        saved=copy.deepcopy(rows)
        detailed,wider,single=regular_reports(rows)
        self.assertEqual(rows,saved)
        self.assertEqual(original_exit['net'],'-0.40')
        self.assertEqual(detailed[0]['return_observations'],50)
        self.assertEqual(wider[0]['return_observations'],50)
        self.assertEqual(D(detailed[0]['average_return_pct']),
                         D(single['average_return_pct']))
        self.assertEqual(detailed[0]['roi_interval_status'],'available')
        self.assertIsNotNone(wider[0]['uncertainty90_pct'])

    def test_repeat_fill_costs_pool_before_event_equal_roi(self):
        rows=[settled('repeat',win=True,contracts='2',cost='1.52'),
              settled('repeat',win=True,contracts='1',price='.76',cost='.76')]
        rows.extend(settled(f'other-{i}',win=i<30) for i in range(49))
        d,w,s=regular_reports(rows)
        for r in (d[0],w[0],s):
            self.assertEqual(r['return_observations'],50)
            self.assertIsNotNone(r['uncertainty90_pct'])
        # Three purchased contracts in the repeated event are one trial,
        # and their entry fees are still reflected in ROI.
        expected=(D(3)-D('2.28'))/D('2.28')
        other_event_rois=sum(
            (D('.25')/D('.75') if i<30 else D(-1))
            for i in range(49)
        )
        event_equal_average=D(100)*(expected+other_event_rois)/D(50)
        self.assertAlmostEqual(float(D(d[0]['average_return_pct'])),
                               float(event_equal_average),places=8)

    def test_estimated_event_attribution_remains_flagged_not_discarded(self):
        rows=[settled(f'event-{i}',win=i<35,estimated=i%3==0)
              for i in range(50)]
        d,w,s=regular_reports(rows)
        self.assertEqual(d[0]['estimated_return_observations'],17)
        self.assertEqual(w[0]['estimated_return_observations'],17)
        self.assertEqual(s['estimated_return_observations'],17)
        self.assertIsNotNone(d[0]['uncertainty90_pct'])
        self.assertIsNotNone(w[0]['uncertainty90_pct'])

    def test_price_time_cohorts_are_not_pooled_as_independent_trials(self):
        rows=[settled(f'event-{i}',win=i<35) for i in range(50)]
        duplicates=[settled(f'event-{i}',win=i<35,horizon='10–15m')
                    for i in range(50)]
        d,w,s=regular_reports(rows+duplicates)
        self.assertEqual(len(d),2)
        self.assertEqual(sum(r['return_observations'] for r in d),100)
        self.assertEqual(s['return_observations'],50,
            'same market event in two cohorts is not a second overall trial')
        self.assertEqual(w[0]['return_observations'],50)
        self.assertEqual(w[1]['return_observations'],50)

    def test_empty_and_zero_cost_groups_never_fabricate_interval(self):
        value=summarize_regular_held_events({})
        self.assertEqual(value['return_observations'],0)
        self.assertEqual(value['roi_interval_status'],'under_minimum')
        self.assertIsNone(value['ci90_low_pct'])
        invalid=summarize_regular_held_events({'bad':dict(cost='0',net='.25')})
        self.assertEqual(invalid['return_observations'],0)
        self.assertIsNone(invalid['uncertainty90_pct'])


if __name__=='__main__':
    unittest.main()

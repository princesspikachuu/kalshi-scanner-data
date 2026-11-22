"""MT-023: honest event-level coverage of regular Favorites, without raw IDs."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from services.api import shadow
from services.paper_demo.shadow.favorite_research_coverage import (
    summarize_regular_favorites_coverage,
)
from services.paper_demo.shadow.favorite_single import (
    MIN_HOLD_RETURN_UNCERTAINTY_EVENTS, summarize_single,
)


class RegularFavoritesCoverageTests(unittest.TestCase):
    def test_cohort_counts_do_not_masquerade_as_independent_events(self):
        detailed = dict(
            rows={'crypto-15m': [
                dict(price='.80', horizon='5–10m', events='8',
                     return_observations=5, average_return_pct='10'),
                dict(price='.85', horizon='3–5m', events='3',
                     return_observations=2, average_return_pct='-10')],
                'finance-hourly': []},
            coverage={'crypto-15m': dict(bots_total=9, bots_with_rows=9,
                                        purchased='5000'),
                      'finance-hourly': dict(bots_total=11, bots_with_rows=0,
                                             purchased='0')})
        wide = dict(rows={'crypto-15m':[
            dict(events=3,return_observations=2)],
            'finance-hourly':[]},
            coverage={'crypto-15m':dict(excluded_legacy_observations=4,
                                        excluded_price_observations=2)})
        single = dict(rows={'crypto-15m': dict(
            resolved_events=8,return_observations=5,incomplete_events=3,
            estimated_return_observations=2,average_return_pct='20',
            ci90_low_pct=None,ci90_high_pct=None),
            'finance-hourly':dict(resolved_events=0,return_observations=0,
                                  incomplete_events=0,
                                  estimated_return_observations=0)})
        origin={'btc':dict(entry_timing=[
            dict(contracts='12',events=1,resolved='3',outcome_events={}),
            dict(contracts='3',events=1,resolved='3',
                 outcome_events={'private-market-id':1})])}
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        original=copy.deepcopy([detailed,wide,single,origin])
        result=summarize_regular_favorites_coverage(
            detailed,wide,single,held_bots=origin,profiles=profiles,
            category_for=lambda p:'crypto-15m')
        self.assertEqual([detailed,wide,single,origin],original)
        self.assertEqual(result['confidence_target'],MIN_HOLD_RETURN_UNCERTAINTY_EVENTS)
        summary=result['categories']['crypto-15m']
        self.assertEqual(summary['independent_resolved_events'],8)
        self.assertEqual(summary['independent_held_return_events'],5)
        self.assertEqual(summary['incomplete_settled_events'],3)
        self.assertEqual(summary['estimated_held_return_events'],2)
        self.assertEqual(summary['need_to_minimum'],MIN_HOLD_RETURN_UNCERTAINTY_EVENTS-5)
        self.assertEqual(summary['detailed_cohort_event_appearances'],11)
        self.assertEqual(summary['detailed_cohort_return_appearances'],7)
        self.assertEqual(summary['wider_cohort_event_appearances'],3)
        self.assertEqual(summary['wider_legacy_cohort_exclusions'],4)
        self.assertEqual(summary['wider_price_cohort_exclusions'],2)
        self.assertEqual(summary['entry_cohort_rows'],2)
        self.assertEqual(summary['entry_cohorts_without_confirmed_outcome'],1)
        self.assertEqual(summary['legacy_claimed_resolved_without_event_ids'],1)
        self.assertEqual(summary['top_sampled_detailed_cohorts'][0]['time_bucket'],'5–10m')
        no_finance=result['categories']['finance-hourly']
        self.assertEqual(no_finance['bots_total'],11)
        self.assertEqual(no_finance['independent_held_return_events'],0)
        self.assertEqual(no_finance['confidence_state'],'under_minimum')
        self.assertNotIn('private-market-id',json.dumps(result))
        self.assertNotIn('5000',json.dumps(summary),
                         'purchased contract quantity is not an observation count')

    def test_nominal_confidence_is_not_available_under_fifty_or_without_variance(self):
        def record(n,lo,hi):
            return dict(resolved_events=n,return_observations=n,incomplete_events=0,
                estimated_return_observations=0,average_return_pct='10',
                ci90_low_pct=lo,ci90_high_pct=hi)
        reports={'not_enough':record(49,'2','18'),
            'same_sign':record(60,None,None),
            'positive':record(61,'1.12','18'),
            'negative':record(50,'-22','-1'),
            'unclear':record(52,'-8','30')}
        result=summarize_regular_favorites_coverage(
            dict(rows={},coverage={}),dict(rows={},coverage={}),
            dict(rows=reports))['categories']
        states={name:item['confidence_state'] for name,item in result.items()}
        self.assertEqual(states,dict(not_enough='under_minimum',
            same_sign='no_numerical_interval',
            positive='nominal_interval_above_zero',
            negative='nominal_interval_below_zero',
            unclear='nominal_interval_overlaps_zero'))
        self.assertEqual(result['not_enough']['need_to_minimum'],1)
        self.assertEqual(result['positive']['need_to_minimum'],0)
        self.assertEqual(result['positive']['ci90_low_pct'],'1.12')

    def test_inconsistent_evidence_is_flagged_not_silently_repaired(self):
        single=dict(rows={'weather-hourly':dict(resolved_events=3,
            return_observations=5,incomplete_events=2,
            estimated_return_observations=6)})
        result=summarize_regular_favorites_coverage({}, {}, single)
        cell=result['categories']['weather-hourly']
        self.assertIn('invalid_single_evidence_counts',cell['flags'])
        self.assertIn('resolved_events_not_placed_in_detailed',cell['flags'])

    def test_workspace_emits_coverage_only_for_regular_favorites(self):
        row=dict(price='.80',horizon='5–10m',market_type='15m_price',
            clock='market_close',contracts='2',cost='1.60',resolved='2',
            winners='2',outcome_events={'private-ticker':1},
            return_events={'private-ticker':dict(cost='1.60',net='.40')},
            return_policy='hold_only')
        metric=dict(entry_timing=[row])
        payload=dict(status={},bots=[dict(id='btc',folder_id='favorites',
            series='KXBTC15M',asset='crypto',experiment=metric)],
            folders=[dict(id='favorites',bots={'btc':metric}),
                     dict(id='favorites_statistics',bots={'btc':metric})])
        original=copy.deepcopy(payload)
        log=io.StringIO()
        with patch.object(shadow,'FAVORITES_ROLLUP_LOG_AT',0):
            with redirect_stdout(log):
                response=shadow.workspace_response(payload)
        self.assertEqual(payload,original)
        self.assertEqual(response.status_code,200)
        lines=[json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
        reports=[line for line in lines if line.get('event')=='favorites_timed_rollup']
        self.assertEqual(len(reports),1)
        evidence=reports[0]['research_evidence']
        self.assertEqual(list(evidence['categories']),['crypto-15m'])
        self.assertEqual(evidence['categories']['crypto-15m']['independent_resolved_events'],1)
        self.assertEqual(evidence['categories']['crypto-15m']['independent_held_return_events'],1)
        self.assertNotIn('private-ticker',log.getvalue())
        self.assertNotIn('statistics',json.dumps(evidence))
        sensitivity=evidence['categories']['crypto-15m']['attribution_sensitivity']
        self.assertEqual(sensitivity['exact_only']['independent_held_return_events'],1)
        self.assertEqual(sensitivity['estimated_only']['independent_held_return_events'],0)
        self.assertEqual(sensitivity['exact_only']['held_roi_mean_pct'],'25.00')
        self.assertEqual(sensitivity['exact_only']['confidence_state'],'under_minimum')
        self.assertIn('nonrandom_subsets',evidence['attribution_note'])


    def test_attribution_sensitivity_tracks_nonrandom_exact_and_estimated_sets(self):
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        rows=[
            dict(contracts='1',price='.80',outcome_events={'sensitive-exact-id':1},
                 return_events={'sensitive-exact-id':dict(cost='.80',net='.20')},
                 return_policy='hold_only'),
            dict(contracts='1',price='.80',outcome_events={'sensitive-estimated-id':0},
                 return_events={'sensitive-estimated-id':dict(cost='.80',net='-.80',
                                                               estimated=True)},
                 return_policy='hold_only'),
            dict(contracts='1',price='.80',outcome_events={'sensitive-incomplete-id':1},
                 return_events={},return_policy='hold_only'),
        ]
        bots={'btc':dict(entry_timing=rows)}
        single=summarize_single(bots,profiles,lambda p:'crypto-15m')
        before=copy.deepcopy([bots,profiles,single])
        summary=summarize_regular_favorites_coverage(
            dict(rows={},coverage={}),dict(rows={},coverage={}),single,
            held_bots=bots,profiles=profiles,category_for=lambda p:'crypto-15m')
        self.assertEqual([bots,profiles,single],before)
        cat=summary['categories']['crypto-15m']
        self.assertEqual(cat['independent_resolved_events'],3)
        self.assertEqual(cat['independent_held_return_events'],2)
        self.assertEqual(cat['estimated_held_return_events'],1)
        self.assertEqual(cat['incomplete_settled_events'],1)
        split=cat['attribution_sensitivity']
        self.assertEqual(split['exact_only']['independent_held_return_events'],1)
        self.assertEqual(split['exact_only']['held_roi_mean_pct'],'25.00')
        self.assertEqual(split['estimated_only']['independent_held_return_events'],1)
        self.assertEqual(split['estimated_only']['held_roi_mean_pct'],'-100.00')
        self.assertEqual(split['exact_only']['positive_return_events'],1)
        self.assertEqual(split['estimated_only']['negative_return_events'],1)
        self.assertEqual(split['estimated_only']['confidence_state'],'under_minimum')
        self.assertIsNone(split['exact_only']['ci90_low_pct'])
        self.assertNotIn('attribution_subsets_do_not_reconcile',cat['flags'])
        redacted=json.dumps(summary)
        for key in ('sensitive-exact-id','sensitive-estimated-id','sensitive-incomplete-id'):
            self.assertNotIn(key,redacted)

    def test_attribution_sensitivity_flags_mismatched_event_attribution(self):
        # Never silently present a split as complete when the source totals
        # disagree with the event-level evidence.
        profile={'btc':dict(series='KXBTC15M',asset='crypto')}
        bots={'btc':dict(entry_timing=[dict(
            contracts='1',price='.80',outcome_events={'only':1},
            return_events={'only':dict(cost='.80',net='.20')})])}
        incorrect=dict(rows={'crypto-15m':dict(
            resolved_events=3,return_observations=3,
            estimated_return_observations=1,incomplete_events=0)})
        result=summarize_regular_favorites_coverage(
            {},{},incorrect,held_bots=bots,profiles=profile,
            category_for=lambda p:'crypto-15m')
        flags=result['categories']['crypto-15m']['flags']
        self.assertIn('attribution_subsets_do_not_reconcile',flags)
        self.assertIn('estimated_attribution_subsets_do_not_reconcile',flags)


if __name__=='__main__':
    unittest.main()

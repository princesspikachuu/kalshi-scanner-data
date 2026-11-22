"""MT-029: correlation changes confidence, never trading or original evidence."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from services.api import shadow
from services.paper_demo.shadow.favorite_event_correlation import (
    event_date_label, summarize_regular_favorites_event_correlation,
)


def row(event, *, net='.20', cost='.80', outcome=1, has_return=True):
    return dict(
        price='.80', horizon='5–10m', market_type='15m_price',
        clock='market_close', contracts='1', cost=cost, resolved='1',
        winners='1' if outcome else '0',
        outcome_events={event: outcome},
        return_events={event:dict(cost=cost,net=net)} if has_return else {},
        return_policy='hold_only',
    )


def audit(bots, categories=None, known=None):
    categories = categories or {}
    profiles = {
        name:dict(series='KXBTC15M',asset='crypto',category=categories.get(name,'crypto-15m'))
        for name in bots
    }
    return summarize_regular_favorites_event_correlation(
        bots,profiles,lambda p:p['category'],known_single=known)


class RegularFavoritesCorrelationTests(unittest.TestCase):
    def test_realistic_exchange_date_labels_and_unknowns(self):
        self.assertEqual(event_date_label('KXHIGHNY-26NOV20'), '2026-11-20')
        self.assertEqual(event_date_label('KXHIGHNY-26NOV20-B80'),'2026-11-20')
        self.assertEqual(event_date_label('KXBTC15M-26NOV21T1715'),'2026-11-21')
        # The actual short-window exchange convention omits the T separator:
        # YYMONDDHHMM, with an optional additional market-strike suffix.
        self.assertEqual(event_date_label('KXBTC15M-26NOV021815'),'2026-11-02')
        self.assertEqual(event_date_label('KXBTC15M-26NOV021815-15'),'2026-11-02')
        self.assertEqual(event_date_label('KXGOLD15M-26NOV211745'),'2026-11-21')
        self.assertIsNone(event_date_label('KXBTC15M-26NOV022415'))
        self.assertIsNone(event_date_label('KXBTC15M-26NOV021860'))
        self.assertIsNone(event_date_label('KXBTC15M-26NOV0218152'))
        self.assertEqual(event_date_label('KXNBAGAME-TEST'),None)
        self.assertEqual(event_date_label('KXFOO-26FEB29'),None)
        self.assertEqual(event_date_label('KXBTC15M-26BAD21'),None)
        self.assertEqual(event_date_label('KXBTC15M-26NOV211'),None)
        self.assertEqual(event_date_label(None),None)

    def test_same_exchange_event_across_cohorts_is_one_event(self):
        shared='KXHIGHNY-26NOV20'
        unique='KXBTC15M-26NOV20T1830'
        bots={
            'one':dict(entry_timing=[
                row(shared,net='.20',cost='.80'),
                row(shared,net='.20',cost='.80')]),
            'two':dict(entry_timing=[
                row(shared,net='-.80',cost='.80',outcome=0),
                row(unique,net='.20',cost='.80')]),
        }
        original=copy.deepcopy(bots)
        r=audit(bots,{'one':'weather-daily','two':'crypto-15m'})
        self.assertEqual(bots,original)
        self.assertEqual(r['distinct_event_identities_across_categories'],2)
        self.assertEqual(r['event_ids_shared_between_categories'],1)
        self.assertEqual(r['excess_cross_category_event_appearances'],1)
        self.assertEqual(r['categories']['weather-daily']['independent_settled_return_events'],1)
        self.assertEqual(r['categories']['crypto-15m']['independent_settled_return_events'],2)
        self.assertNotIn(shared,json.dumps(r))
        self.assertNotIn(unique,json.dumps(r))

    def test_same_day_dependencies_widen_cluster_interval(self):
        # 20 date-labelled event days, 3 different events/day. Within each
        # date all ROI signs match. The naive 60-event t interval understates
        # the day-cluster uncertainty on exactly the same 60 events.
        entries=[]
        for day in range(1,21):
            for slot in (0, 1, 2):
                ident=f'KXBTC15M-26NOV{day:02d}T{slot:04d}'
                gain=(day % 2 == 0)
                entries.append(row(ident, cost='1',net='1' if gain else '-1',
                                   outcome=int(gain)))
        bots={'btc':dict(entry_timing=entries)}
        before=copy.deepcopy(bots)
        summary=audit(bots)['categories']['crypto-15m']
        self.assertEqual(bots,before)
        self.assertEqual(summary['independent_settled_return_events'],60)
        self.assertEqual(summary['distinct_event_dates'],20)
        self.assertEqual(summary['with_parseable_event_date'],60)
        self.assertEqual(summary['events_in_multi_event_dates'],60)
        self.assertEqual(summary['largest_date_event_count'],3)
        self.assertEqual(summary['cluster_interval_status'],'available')
        self.assertGreater(float(summary['cluster_90pct_error_pp']),
                           float(summary['nominal_90pct_error_dated_subset_pp']))
        self.assertGreater(float(summary['cluster_vs_iid_error_ratio_pct']),150)
        exact=summary['attribution_date_clusters']['exact_only']
        estimated=summary['attribution_date_clusters']['estimated_only']
        self.assertEqual(exact['independent_settled_return_events'],60)
        self.assertEqual(exact['cluster_interval_status'],'available')
        self.assertEqual(estimated['independent_settled_return_events'],0)
        self.assertIsNone(estimated['cluster_90pct_error_pp'])
        self.assertLess(float(summary['cluster_90pct_low_roi_pct']),0)
        self.assertGreater(float(summary['cluster_90pct_high_roi_pct']),0)

    def test_mixed_estimated_and_exact_date_clusters_remain_separate(self):
        # Different event IDs on the same date may be correlated, even when
        # one has fully exact entry sizing and the other is reconstructed.
        entries=[]
        for day in range(1,26):
            for slot,estimated in enumerate((False,True)):
                ident=f'KXBTC15M-26NOV{day:02d}T{slot:04d}'
                item=row(ident,cost='1',net='1' if day%2 else '-1',
                         outcome=int(day%2))
                item['return_events'][ident]['estimated']=estimated
                entries.append(item)
        bots={'btc':dict(entry_timing=entries)}
        original=copy.deepcopy(bots)
        report=audit(bots)['categories']['crypto-15m']
        self.assertEqual(bots,original)
        self.assertEqual(report['independent_settled_return_events'],50)
        self.assertEqual(report['distinct_event_dates'],25)
        exact=report['attribution_date_clusters']['exact_only']
        estimated=report['attribution_date_clusters']['estimated_only']
        self.assertEqual(exact['independent_settled_return_events'],25)
        self.assertEqual(estimated['independent_settled_return_events'],25)
        self.assertEqual(exact['cluster_interval_status'],'under_50_events')
        self.assertEqual(estimated['cluster_interval_status'],'under_50_events')
        self.assertEqual(report['flags'],[])

    def test_compact_close_times_across_days_are_eligible_for_proxy_clusters(self):
        rows=[]
        for day in range(1,26):
            for hour in (12,13):
                ident=f'KXBTC15M-26NOV{day:02d}{hour:02d}15'
                gain=bool(day%2)
                rows.append(row(ident,cost='1',net='1' if gain else '-1',
                                outcome=int(gain)))
        report=audit({'btc':dict(entry_timing=rows)})['categories']['crypto-15m']
        self.assertEqual(report['with_parseable_event_date'],50)
        self.assertEqual(report['distinct_event_dates'],25)
        self.assertEqual(report['event_date_coverage_pct'],'100.00')
        self.assertEqual(report['cluster_interval_status'],'available')
        self.assertIsNotNone(report['cluster_90pct_error_pp'])

    def test_clustering_cannot_fake_fifty_independent_days(self):
        rows=[row(f'KXBTC15M-26NOV20T{i:04d}',cost='1',
                  net='1' if i%2 else '-1',
                  outcome=int(i%2)) for i in range(60)]
        s=audit({'btc':dict(entry_timing=rows)})['categories']['crypto-15m']
        self.assertEqual(s['independent_settled_return_events'],60)
        self.assertEqual(s['distinct_event_dates'],1)
        self.assertEqual(s['cluster_interval_status'],'under_20_date_clusters')
        self.assertIsNone(s['cluster_90pct_error_pp'])
        self.assertEqual(s['largest_date_share_pct'],'100.00')

    def test_unknown_date_coverage_is_reported_not_silently_guessed(self):
        rows=[
            row(f'KXBTC15M-26NOV{i%20+1:02d}T{i:04d}',
                cost='1', net='1' if i%2 else '-1',outcome=i%2)
            for i in range(30)
        ] + [
            row(f'UNPARSEABLE-EVENT-{i}',cost='1',
                net='1' if i%2 else '-1',outcome=i%2)
            for i in range(20)
        ]
        s=audit({'btc':dict(entry_timing=rows)})['categories']['crypto-15m']
        self.assertEqual(s['independent_settled_return_events'],50)
        self.assertEqual(s['without_parseable_event_date'],20)
        self.assertEqual(s['event_date_coverage_pct'],'60.00')
        self.assertEqual(s['cluster_interval_status'],'less_than_80pct_date_coverage')
        self.assertIsNone(s['cluster_90pct_low_roi_pct'])

    def test_incomplete_events_excluded_and_single_count_checked(self):
        bots={'btc':dict(entry_timing=[
            row('KXBTC15M-26NOV20T1700',has_return=True),
            row('KXBTC15M-26NOV20T1715',has_return=False),
        ])}
        s=audit(bots,known={'rows':{'crypto-15m':dict(return_observations=1)}})
        self.assertEqual(s['categories']['crypto-15m']['independent_settled_return_events'],1)
        self.assertEqual(s['categories']['crypto-15m']['flags'],[])
        bad=audit(bots,known={'rows':{'crypto-15m':dict(return_observations=2)}})
        self.assertEqual(bad['categories']['crypto-15m']['flags'],
                         ['different_from_single_deduplicated_return_events'])

    def test_workspace_log_excludes_statistics_and_original_records_unchanged(self):
        entry=row('KXHIGHNY-26NOV20',cost='.80',net='.20')
        metric=dict(entry_timing=[entry])
        payload=dict(status={},bots=[dict(id='regular',folder_id='favorites',
            series='KXHIGHNY',asset='weather_daily',experiment=metric)],
            folders=[dict(id='favorites',bots={'regular':metric}),
                     dict(id='favorites_statistics',bots={'regular':metric})])
        original=copy.deepcopy(payload)
        buffer=io.StringIO()
        with patch.object(shadow,'FAVORITES_ROLLUP_LOG_AT',0):
            with redirect_stdout(buffer):
                shadow.workspace_response(payload)
        self.assertEqual(payload,original)
        records=[json.loads(x) for x in buffer.getvalue().splitlines() if x.strip()]
        correlation=[x for x in records if x.get('event')=='favorites_event_correlation']
        self.assertEqual(len(correlation),1)
        self.assertEqual(correlation[0]['audit']['categories']['weather-daily'][
            'independent_settled_return_events'],1)
        self.assertNotIn('favorites_statistics',json.dumps(correlation))
        self.assertNotIn('KXHIGHNY-26NOV20',json.dumps(correlation))


if __name__=='__main__':
    unittest.main()

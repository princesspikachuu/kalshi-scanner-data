"""Read-only Statistics-Backed Favorites hold P/L evidence regression tests."""
import json
import unittest
from copy import deepcopy
from decimal import Decimal as D

from services.paper_demo.shadow.favorite_single import summarize_statistics_holds
from services.api.shadow import workspace_response


def row(event='event-a', price='.80', horizon='10–15m', kind='15m_price',
        cost='8', net='2', outcome=1, policy='hold_only', estimated=False):
    return dict(price=price, horizon=horizon, market_type=kind,
                return_policy=policy, outcome_events={event: outcome},
                return_events={event:dict(cost=cost, net=net, estimated=estimated)})


class VerifiedStatisticsHoldResearch(unittest.TestCase):
    def summarize(self, collector, stats=None, profiles=None):
        sources=[collector]
        if stats is not None:
            sources.append(stats)
        if profiles is None:
            profiles={bot:dict(id=bot) for source in sources for bot in source}
        return summarize_statistics_holds(sources, profiles)

    def test_same_event_across_collector_and_stats_is_one_entry_cohort_return(self):
        collector={'btc':dict(entry_timing=[row(cost='8',net='2')])}
        stats={'stats_btc':dict(entry_timing=[
            row(cost='1',net='-1'),row('event-b',cost='9',net='1',outcome=0)
        ])}
        result=self.summarize(collector, stats)
        cell=result['by_cell']['15m_price']['80-84|10–15m']
        market=result['by_market_type']['15m_price']
        for report in (cell,market):
            self.assertEqual(report['resolved_events'],2)
            self.assertEqual(report['return_observations'],2)
            self.assertEqual(report['incomplete_events'],0)
            # Event A is one cost-weighted observation: (2-1)/(8+1).
            expected=(D(1)/D(9)+D(1)/D(9))*D(100)/2
            self.assertEqual(D(report['average_return_pct']),expected)
            self.assertIsNone(report['uncertainty90_pct'])
        self.assertEqual(result['basis'],'verified_hold_only')

    def test_one_event_in_multiple_cells_does_not_inflate_single_bucket(self):
        collector={'btc':dict(entry_timing=[
            row(cost='8',net='2'),row(cost='7.5',net='-7.5',
                                       price='.75',horizon='5–10m'),
            row('event-b',cost='8',net='-8',outcome=0)
        ])}
        result=self.summarize(collector)
        self.assertEqual(result['by_market_type']['15m_price']['return_observations'],2)
        self.assertEqual(result['by_cell']['15m_price']['80-84|10–15m']['return_observations'],2)
        self.assertEqual(result['by_cell']['15m_price']['75-79|5–10m']['return_observations'],1)
        self.assertEqual(result['by_cell']['15m_price']['75-79|5–10m']['uncertainty90_pct'],None)
        expected=(D('-5.5')/D('15.5')+D('-8')/D(8))*D(100)/2
        self.assertEqual(D(result['by_market_type']['15m_price']['average_return_pct']),expected)

    def test_unknown_unverified_and_exit_altered_data_never_create_hold_returns(self):
        a=row('observed',net='4',policy='all_executions')
        b=row('incomplete')
        b['return_events']={}
        c=row('unverified')
        c['outcome_events']={}
        result=self.summarize({'btc':dict(entry_timing=[a,b,c])})
        combined=result['by_market_type']['15m_price']
        self.assertEqual(combined['resolved_events'],2)
        self.assertEqual(combined['return_observations'],0)
        self.assertEqual(combined['incomplete_events'],2)
        self.assertIsNone(combined['average_return_pct'])
        self.assertIsNone(combined['uncertainty90_pct'])

    def test_hourly_and_fifteen_minute_events_are_not_combined(self):
        collector={'btc':dict(entry_timing=[row()]),
                   'hour':dict(entry_timing=[row(kind='hourly_price',horizon='30–60m')])}
        report=self.summarize(collector)
        self.assertEqual(report['by_market_type']['15m_price']['resolved_events'],1)
        self.assertEqual(report['by_market_type']['hourly_price']['resolved_events'],1)

    def test_out_of_scope_prices_and_missing_times_are_not_fake_cells(self):
        collector={'btc':dict(entry_timing=[
            row('low',price='.60'),
            row('high',price='.97'),
            row('unknown-time',horizon='unclassified'),
            row('valid')
        ])}
        report=self.summarize(collector)
        self.assertEqual(set(report['by_cell']['15m_price']),{'80-84|10–15m'})
        self.assertEqual(report['by_market_type']['15m_price']['resolved_events'],1)

    def test_estimated_reconstructed_hold_returns_remain_labeled_while_uncertainty_is_pending(self):
        collector={'btc':dict(entry_timing=[row('a',estimated=True),
                                           row('b',cost='9',net='-9',outcome=0)])}
        report=self.summarize(collector)['by_market_type']['15m_price']
        self.assertEqual(report['return_observations'],2)
        self.assertEqual(report['estimated_return_observations'],1)
        self.assertEqual(report['uncertainty_min_samples'],20)
        self.assertIsNone(report['uncertainty90_pct'])
        self.assertIsNone(report['ci90_low_pct'])
        self.assertIsNone(report['ci90_high_pct'])

    def test_statistics_held_interval_starts_at_twenty_distinct_events_with_gains_and_losses(self):
        rows=[row('win-'+str(i)) for i in range(18)]
        rows.append(row('loss-a',cost='8',net='-8',outcome=0))
        early=self.summarize({'btc':dict(entry_timing=rows)})['by_market_type']['15m_price']
        self.assertEqual(early['return_observations'],19)
        self.assertIsNone(early['uncertainty90_pct'])
        rows.append(row('loss-b',cost='8',net='-8',outcome=0))
        enough=self.summarize({'btc':dict(entry_timing=rows)})['by_market_type']['15m_price']
        self.assertEqual(enough['return_observations'],20)
        self.assertGreater(D(enough['uncertainty90_pct']),0)
        self.assertLess(D(enough['ci90_low_pct']),D(enough['average_return_pct']))
        self.assertGreater(D(enough['ci90_high_pct']),D(enough['average_return_pct']))

    def test_authenticated_workspace_merges_saved_paper_sources_without_mutating_them(self):
        bots=[
            dict(id='btc',series='KXBTC15M',asset='crypto'),
            dict(id='stat_btc',series='KXBTC15M',asset='crypto'),
        ]
        collector={'btc':dict(entry_timing=[row()])}
        backed={'stat_btc':dict(entry_timing=[
            row(cost='9',net='-9',outcome=0),
            row('b',cost='8',net='2')
        ])}
        payload=dict(status={},bots=bots,folders=[
            dict(id='favorites',bots=collector),
            dict(id='favorites_statistics',bots=backed,
                 statistics=dict(min_samples=20,matrix=[]))
        ])
        pristine=deepcopy(payload)
        result=json.loads(workspace_response(payload).body)
        self.assertEqual(payload,pristine)
        folder=next(f for f in result['folders'] if f['id']=='favorites_statistics')
        self.assertNotIn('bots',folder)
        self.assertEqual(folder['statistics']['min_samples'],20)
        evidence=folder['statistics_hold_summary']
        self.assertEqual(evidence['by_market_type']['15m_price']['return_observations'],2)
        self.assertEqual(evidence['by_cell']['15m_price']['80-84|10–15m']['return_observations'],2)
        self.assertEqual(evidence['basis'],'verified_hold_only')
        # Raw event IDs, outcome maps and fills never leave the workspace API.
        self.assertNotIn('outcome_events',folder['statistics_hold_summary'])
        self.assertNotIn('return_events',folder['statistics_hold_summary'])

    def test_no_statistics_folder_does_not_add_stats_evidence_to_regular_favorites(self):
        payload=dict(status={},bots=[dict(id='btc',series='KXBTC15M',asset='crypto')],
                     folders=[dict(id='favorites',bots={'btc':dict(entry_timing=[row()])})])
        result=json.loads(workspace_response(payload).body)
        self.assertNotIn('statistics_hold_summary',result['folders'][0])
        self.assertIn('collector_single_summary',result['folders'][0])


if __name__=='__main__':
    unittest.main()

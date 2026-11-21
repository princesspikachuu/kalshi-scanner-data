"""Read-only regular Favorites profitability must be backed by known settlements.

These tests exercise the dashboard's regular collector rollup, not Statistics-
Backed Favorites, execution, settlement, or mutation of historical records.
"""
import copy
import unittest
from decimal import Decimal as D

from services.api.shadow import favorite_collector_timed_totals


class RegularFavoritesProfitAuditTests(unittest.TestCase):
    def row(self, *, price='.75', contracts='1', cost='.75', net='0',
            outcomes=None, returns=None, policy='hold_only'):
        return dict(
            price=price, horizon='5–10m', clock='market_close',
            market_type='15m_price', contracts=contracts, cost=cost, net=net,
            outcome_events={} if outcomes is None else outcomes,
            return_events={} if returns is None else returns,
            return_policy=policy,
        )

    def aggregate(self, rows):
        result=favorite_collector_timed_totals(
            {'btc':dict(entry_timing=rows)},
            {'btc':dict(series='KXBTC15M',asset='crypto')})
        return result['rows']['crypto-15m'][0]

    def test_partials_and_correlated_thresholds_are_one_equal_weight_event(self):
        # Two fills share event A and one separate losing event B. The +2c
        # entry fee on the first A cohort must remain in its cost basis.
        a=self.row(contracts='2',cost='1.52',
            outcomes={'event-A':1},
            returns={'event-A':dict(cost='1.52',net='.48')})
        b=self.row(price='.76',cost='.76',
            outcomes={'event-A':1},
            returns={'event-A':dict(cost='.76',net='.24')})
        c=self.row(outcomes={'event-B':0},
            returns={'event-B':dict(cost='.75',net='-.75')})
        originals=copy.deepcopy([a,b,c])
        result=self.aggregate([a,b,c])
        self.assertEqual([a,b,c],originals,'rollup is read-only')
        self.assertEqual(D(result['contracts']),D(4))
        self.assertEqual(D(result['cost']),D('3.03'))
        self.assertEqual(D(result['events']),D(2))
        self.assertEqual(D(result['event_wins']),D(1))
        self.assertEqual(result['return_observations'],2)
        event_a_roi=D('.72')/D('2.28')
        self.assertAlmostEqual(float(D(result['average_return_pct'])),
            float(100*(event_a_roi-D(1))/2),places=8)

    def test_orphan_return_without_same_row_settlement_is_excluded(self):
        row=self.row(outcomes={'verified':1},returns={
            'verified':dict(cost='.75',net='.25'),
            'unsettled':dict(cost='.75',net='9.25')})
        summary=self.aggregate([row])
        self.assertEqual(D(summary['events']),1)
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(D(summary['average_return_pct']),D(100)/3)

        # A return from an entirely unknown event cannot create a P/L sample.
        unknown=self.aggregate([self.row(outcomes={},
            returns={'unsettled':dict(cost='.75',net='.25')})])
        self.assertEqual(unknown['return_observations'],0)
        self.assertIsNone(unknown['average_return_pct'])

    def test_historical_exit_proceeds_are_not_mislabeled_as_hold_returns(self):
        row=self.row(outcomes={'verified':1},
            returns={'verified':dict(cost='.75',net='-.50')},
            cost='.75',net='-.50',policy='all_executions')
        summary=self.aggregate([row])
        self.assertEqual(D(summary['events']),1)
        self.assertEqual(D(summary['event_wins']),1)
        self.assertEqual(D(summary['net']),D('-.50'),
            'keep the separately reported actual realized ledger total')
        self.assertEqual(summary['return_observations'],0)
        self.assertIsNone(summary['average_return_pct'])

    def test_bad_legacy_evidence_never_invents_a_profit_or_breaks_workspace(self):
        rows=[
            self.row(outcomes={'bad-outcome':'unknown'},
                returns={'bad-outcome':dict(cost='.75',net='.25')}),
            self.row(outcomes={'nonfinite':1},
                returns={'nonfinite':dict(cost='NaN',net='.25')}),
            self.row(outcomes={'zero-cost':0},
                returns={'zero-cost':dict(cost='0',net='-.75')}),
        ]
        summary=self.aggregate(rows)
        self.assertEqual(D(summary['events']),2)
        self.assertEqual(summary['return_observations'],0)
        self.assertIsNone(summary['average_return_pct'])
        self.assertEqual(summary['return_sum'],'0')
        malformed=self.aggregate([self.row(outcomes=['not-a-map'],
            returns={'anything':dict(cost='.75',net='.25')})])
        self.assertEqual(malformed['return_observations'],0)
        self.assertEqual(D(malformed['events']),0)

    def test_event_identifiers_are_normalized_without_mutating_old_records(self):
        row=self.row(outcomes={123:1},
            returns={'123':dict(cost='.80',net='.20')})
        prior=copy.deepcopy(row)
        summary=self.aggregate([row])
        self.assertEqual(row,prior)
        self.assertEqual(D(summary['events']),1)
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(D(summary['average_return_pct']),25)

    def test_unmarked_legacy_policy_still_requires_confirmed_outcome(self):
        row=self.row(outcomes={'A':1},
            returns={'A':dict(cost='.75',net='.25')})
        row.pop('return_policy')
        summary=self.aggregate([row])
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(D(summary['average_return_pct']),D(100)/3)


if __name__=='__main__':
    unittest.main()

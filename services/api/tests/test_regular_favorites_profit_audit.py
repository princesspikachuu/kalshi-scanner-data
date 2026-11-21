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

    def test_historical_known_winning_exit_is_evaluated_as_held_to_settlement(self):
        row=self.row(outcomes={'verified':1},
            returns={'verified':dict(cost='.75',net='-.50')},
            cost='.75',net='-.50',policy='all_executions')
        prior=copy.deepcopy(row)
        summary=self.aggregate([row])
        self.assertEqual(row,prior,'no recorded exits or cash can be rewritten')
        self.assertEqual(D(summary['events']),1)
        self.assertEqual(D(summary['event_wins']),1)
        self.assertEqual(D(summary['net']),D('-.50'),
            'separate historical realized ledger retains the early sale')
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(D(summary['average_return_pct']),D(100)/3,
            'research must report the counterfactual winning hold, not the exit')
        self.assertEqual(D(summary['return_sum']),D(1)/D(3))

    def test_known_losing_exit_is_a_full_held_loss_and_unknown_is_omitted(self):
        loss=self.row(price='.80',contracts='1',cost='.80',net='-.05',
            outcomes={'settled-loss':0},
            returns={'settled-loss':dict(cost='.80',net='-.05')},
            policy='all_executions')
        result=self.aggregate([loss])
        self.assertEqual(result['return_observations'],1)
        self.assertEqual(D(result['average_return_pct']),-100)
        self.assertEqual(D(result['net']),D('-.05'))
        no_result=self.aggregate([self.row(outcomes={},
            returns={'early-exit':dict(cost='.80',net='-.05')},
            policy='all_executions')])
        self.assertEqual(no_result['return_observations'],0)
        self.assertEqual(D(no_result['events']),0)
        self.assertIsNone(no_result['average_return_pct'])

    def test_older_exits_without_return_map_use_verified_entry_basis(self):
        row=self.row(price='.80',contracts='10',cost='8.10',net='-4',
            outcomes={'one':1},returns={},policy='all_executions')
        row.update(resolved='10',winners='10')
        summary=self.aggregate([row])
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(summary['estimated_return_observations'],0)
        self.assertEqual(D(summary['average_return_pct']),
                         100*(D(10)-D('8.10'))/D('8.10'))

    def test_multi_event_historical_costs_estimate_entry_quantities_not_exit_profits(self):
        row=self.row(price='.80',contracts='6',cost='4.8',net='-1',
            outcomes={'win':1,'loss':0},
            returns={'win':dict(cost='3.2',net='-1.1'),
                     'loss':dict(cost='1.6',net='.1')},
            policy='all_executions')
        row.update(resolved='6',winners='4')
        summary=self.aggregate([row])
        self.assertEqual(summary['return_observations'],2)
        self.assertEqual(summary['estimated_return_observations'],2)
        self.assertEqual(D(summary['average_return_pct']),D('-37.5'))

    def test_partially_attributed_repeat_event_cannot_inflate_pooled_roi(self):
        from services.paper_demo.shadow.regular_favorites_hold_research import (
            regular_favorites_held_bots)
        from services.paper_demo.shadow.favorite_single import summarize_single
        from services.paper_demo.shadow.favorite_wide import summarize_wide
        a=self.row(outcomes={'A':1},
            returns={'A':dict(cost='.75',net='.25')})
        b=self.row(outcomes={'A':1},
            returns={'A':dict(cost='NaN',net='.25')})
        bots={'btc':dict(entry_timing=[a,b])}
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        result=self.aggregate([a,b])
        self.assertEqual(D(result['events']),1)
        self.assertEqual(result['return_observations'],0,
            'one malformed cohort makes the combined event return incomplete')
        self.assertIsNone(result['average_return_pct'])
        held=regular_favorites_held_bots(bots)
        wide=summarize_wide(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m'][0]
        single=summarize_single(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m']
        for other in (wide,single):
            self.assertEqual(other['return_observations'],0)
            self.assertIsNone(other['average_return_pct'])

    def test_all_three_regular_favorites_views_restore_known_early_exits(self):
        from services.paper_demo.shadow.regular_favorites_hold_research import (
            regular_favorites_held_bots)
        from services.paper_demo.shadow.favorite_single import summarize_single
        from services.paper_demo.shadow.favorite_wide import summarize_wide
        row=self.row(price='.80',contracts='4',cost='3.2',net='-1.6',
            outcomes={'settled':1},
            returns={'settled':dict(cost='3.2',net='-1.6')},
            policy='all_executions')
        row.update(time_min=400,time_max=401,
            wide_events={'settled':[[400,'4','3.2','-1.6']]})
        original=copy.deepcopy(row)
        bots={'btc':dict(entry_timing=[row])}
        profiles={'btc':dict(series='KXBTC15M',asset='crypto')}
        held=regular_favorites_held_bots(bots)
        self.assertEqual(row,original)
        entry=held['btc']['entry_timing'][0]
        self.assertEqual(D(entry['wide_events']['settled'][0][3]),D('.8'))
        self.assertEqual(D(entry['return_events']['settled']['net']),D('.8'))
        detailed=favorite_collector_timed_totals(held,profiles,held_view=True)['rows']['crypto-15m'][0]
        wide=summarize_wide(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m'][0]
        single=summarize_single(held,profiles,lambda p:'crypto-15m')['rows']['crypto-15m']
        for view in (detailed,wide,single):
            self.assertEqual(view['return_observations'],1)
            self.assertEqual(D(view['average_return_pct']),25)

    def test_conservative_correlated_event_label_does_not_override_confirmed_cash_payout(self):
        # The same venue event can contain several thresholds. A conservative
        # event-level loss label must not overwrite this entry's paid side.
        row=self.row(contracts='4',cost='3',net='-.40',
            outcomes={'grouped-thresholds':0},
            returns={'grouped-thresholds':dict(cost='3',net='-.40')},
            policy='all_executions')
        row.update(resolved='4',winners='4')
        summary=self.aggregate([row])
        self.assertEqual(D(summary['events']),1)
        self.assertEqual(D(summary['event_wins']),0)
        self.assertEqual(summary['return_observations'],1)
        self.assertEqual(D(summary['average_return_pct']),D(100)/D(3),
            'cash payout is known to be a win despite conservative event label')

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

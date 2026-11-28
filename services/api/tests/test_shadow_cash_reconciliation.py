"""Recorded cash links must reconcile before any correction is considered."""
import unittest
from uuid import uuid4
from unittest.mock import patch
from services.demo import shadow_cash_reconciliation as r


def row(kind,cash,stamp='2026-11-01T00:00:00+00:00',**fields):
    ident=str(uuid4())
    return dict(id=ident,idempotency_key='demo/shadow/event/'+str(uuid4()),asset='crypto',
                status='succeeded',created_at=stamp,progress=dict(event=kind,cash=cash,**fields))


def fill(cash,action='buy',side='yes',quantity='1',price='.40',fee='.01',**fields):
    return row('FILL',cash,action=action,side=side,quantity=quantity,price=price,fee=fee,ticker='A',**fields)


def wallet(cash,lots=None,deposits='100'):
    return dict(cash=cash,deposits=deposits,lots=lots or [])


class CashReplayTests(unittest.TestCase):
    def test_buy_partial_exit_and_final_settlement_include_all_recorded_fees(self):
        events=[fill('99.18',quantity='2',fee='.02'),
                fill('99.87',action='sell',price='.70'),
                row('SETTLED','100.87',ticker='A',price='1')]
        report=r.reconcile_wallet(wallet('100.87'),events,initial_cash='100')
        self.assertTrue(report['replay_matches_checkpoint'])
        self.assertEqual(report['recorded_fill_fees'],'0.03')
        self.assertFalse(report['safe_to_restart'])
        self.assertFalse(report['lot_cost_allocation_reconciled'])

    def test_opposite_buy_releases_only_netted_collateral(self):
        events=[fill('99.18',quantity='2',fee='.02'),fill('99.67',side='no',price='.50')]
        w=wallet('99.67',[dict(ticker='A',side='yes',quantity='1')])
        self.assertTrue(r.reconcile_wallet(w,events,initial_cash='100')['replay_matches_checkpoint'])

    def test_same_commit_random_uuid_order_is_not_execution_order(self):
        events=[fill('100.18',action='sell',price='.60'),fill('99.59')]
        result=r.reconcile_wallet(wallet('100.18'),events,initial_cash='100')
        self.assertTrue(result['replay_matches_checkpoint'])

    def test_cash_order_backtracks_when_an_initially_valid_zero_settlement_blocks_fill(self):
        # Both the zero-payout settlement and the buy are initially cash-linked.
        # The correct path buys, returns to 100 through the sell, then settles.
        events=[row('SETTLED','100',ticker='A',price='0'),
                fill('99.60',fee='0'),fill('100',action='sell',fee='0')]
        self.assertTrue(r.reconcile_wallet(wallet('100'),events,initial_cash='100')['replay_matches_checkpoint'])

    def test_many_zero_settlements_do_not_materialize_permutations(self):
        events=[row('SETTLED','100',ticker='A'+str(i),price='0') for i in range(256)]
        report=r.reconcile_wallet(wallet('100'),events,initial_cash='100')
        self.assertTrue(report['replay_matches_checkpoint'])
        self.assertEqual(report['search_states'],256)

    def test_missing_fill_fee_tampering_or_uncovered_sell_breaks_cash_chain(self):
        for events in ([fill('99.59',fee='.02')],[fill('100.39',action='sell')],
                       [fill('99.59'),row('SETTLED','101',ticker='A',price='1')]):
            with self.subTest(events=events),self.assertRaises(r.CashReconciliationError):
                r.reconcile_wallet(wallet('100'),events,initial_cash='100')

    def test_duplicate_sources_or_archive_pointer_are_never_double_counted(self):
        e=fill('99.59')
        for rows in ([e,e],[dict(e,progress=dict(e['progress'],archive={'key':'cold'}))],
                     [dict(e,created_at='2026-11-01')],[dict(e,status='failed')]):
            with self.subTest(rows=rows),self.assertRaises(r.CashReconciliationError):
                r.reconcile_wallet(wallet('99.59'),rows,initial_cash='100')

    def test_refills_and_remaining_inventory_are_independent_endpoint_checks(self):
        events=[row('REFILL','110',quantity='10'),fill('109.59')]
        good=wallet('109.59',[dict(ticker='A',side='yes',quantity='1')],deposits='110')
        result=r.reconcile_wallet(good,events,initial_cash='100')
        self.assertTrue(result['replay_matches_checkpoint'])
        for bad in (dict(good,cash='109'),dict(good,deposits='100'),dict(good,lots=[])):
            self.assertFalse(r.reconcile_wallet(bad,events,initial_cash='100')['replay_matches_checkpoint'])

    def test_invalid_numbers_prices_fees_and_search_capacity_fail_closed(self):
        for field,value in (('fee','NaN'),('fee','-.01'),('price','1.1'),('quantity',True),('quantity','0')):
            e=fill('99.59');e['progress'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(r.CashReconciliationError):
                r.reconcile_wallet(wallet('99.59'),[e],initial_cash='100')
        with patch.object(r,'MAX_SEARCH_STATES',0),self.assertRaisesRegex(r.CashReconciliationError,'capacity'):
            r.reconcile_wallet(wallet('99.59'),[fill('99.59')],initial_cash='100')

    def test_settled_market_cannot_accept_later_fill_or_duplicate_payout(self):
        events=[fill('99.59'),row('SETTLED','100.59',ticker='A',price='1')]
        self.assertTrue(r.reconcile_wallet(wallet('100.59'),events,initial_cash='100')['cash_matches'])
        for extra in (fill('100.18'),row('SETTLED','100.59',ticker='A',price='1')):
            with self.assertRaises(r.CashReconciliationError):
                r.reconcile_wallet(wallet('100.59'),events+[extra],initial_cash='100')

"""Paper market settlement markers remain only diagnostic review leads."""
import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.tests.test_shadow_favorite_fill_linkage import (
    events,original,page,
)
from services.demo.shadow_favorite_settlement_markers import (
    inspect_supplied_favorite_settlement_markers,
)
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def settle(price='1',ticker='KXFAV',at='1794437100'):
    return original(dict(event='SETTLED',ticker=ticker,
                         price=price,time=at))


class SuppliedSettlementMarkerTests(unittest.TestCase):
    def test_single_later_paper_marker_is_not_authoritative_outcome(self):
        cohort,fill=events()
        marker=settle()
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,marker)])
        self.assertEqual(result['linked_entry_fills'],1)
        self.assertEqual(result['candidate_paper_settlement_tickers'],1)
        lead=result['market_review_leads'][0]
        self.assertEqual(lead['evidence_status'],'candidate_paper_marker_only')
        self.assertEqual(lead['candidate_paper_yes_payout'],'1')
        self.assertEqual(lead['marker_original_ids'],[marker['id']])
        for flag in ('authoritative_settlement_verified',
                     'realized_pnl_reconciled','safe_to_train',
                     'all_time_coverage_complete'):
            self.assertFalse(result[flag])
        self.assertEqual(result['authoritative_outcome_samples'],0)

    def test_missing_and_unrelated_markers_are_not_losses(self):
        cohort,fill=events()
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,settle(ticker='UNRELATED'))])
        self.assertEqual(result['missing_paper_marker_tickers_in_supplied_pages'],1)
        self.assertEqual(result['market_review_leads'][0]['evidence_status'],
                         'not_in_supplied_pages')
        self.assertEqual(result['candidate_paper_settlement_tickers'],0)

    def test_earlier_marker_is_ambiguous_not_result(self):
        cohort,fill=events()
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,settle(at='1794436999'))])
        self.assertEqual(result['ambiguous_paper_marker_tickers'],1)
        self.assertEqual(result['market_review_leads'][0]['evidence_status'],
                         'paper_marker_precedes_linked_entry')

    def test_multiple_or_conflicting_paper_markers_remain_ambiguous(self):
        cohort,fill=events()
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,settle('1'),settle('0'))])
        self.assertEqual(result['ambiguous_paper_marker_tickers'],1)
        self.assertEqual(result['candidate_paper_settlement_tickers'],0)
        self.assertIsNone(
            result['market_review_leads'][0]['candidate_paper_yes_payout'])

    def test_verified_r2_copy_does_not_create_second_paper_marker(self):
        cohort,fill=events()
        marker=settle()
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,marker),
            page(deepcopy(marker),source='r2_reclaimed_raw',verified=True)])
        self.assertEqual(result['candidate_paper_settlement_tickers'],1)
        self.assertEqual(result['unique_original_events'],3)

    def test_invalid_relevant_marker_fails_closed(self):
        for price in ('2','-1','NaN','Infinity',[],None):
            cohort,fill=events()
            with self.subTest(price=price):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_supplied_favorite_settlement_markers([
                        page(cohort,fill,settle(price))])
        for at in ('-1','NaN',[],None):
            cohort,fill=events()
            with self.subTest(at=at):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_supplied_favorite_settlement_markers([
                        page(cohort,fill,settle(at=at))])

    def test_unverified_r2_and_ambiguous_fills_not_promoted(self):
        cohort,fill=events()
        marker=settle()
        with self.assertRaises(HistoryReconciliationError):
            inspect_supplied_favorite_settlement_markers([
                page(cohort,fill),page(marker,source='r2_reclaimed_raw')])
        duplicate=deepcopy(fill)
        duplicate['id']=str(uuid4())
        duplicate['key']='demo/shadow/event/'+duplicate['id']
        result=inspect_supplied_favorite_settlement_markers([
            page(cohort,fill,duplicate,marker)])
        self.assertEqual(result['linked_entry_fills'],0)
        self.assertEqual(result['candidate_paper_settlement_tickers'],0)


if __name__=='__main__':
    unittest.main()

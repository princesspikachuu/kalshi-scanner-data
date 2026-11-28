"""No partial Favorites audit is misrepresented as empirical trading evidence."""
import unittest
from uuid import uuid4

from services.demo.shadow_favorites_coverage import summarize_supplied_favorites_evidence
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def ev(kind,ticker='MARKET-TEST',uuid=None):
    identifier=str(uuid or uuid4())
    return dict(id=identifier,key='demo/shadow/event/'+identifier,
                parameters={},progress=dict(event=kind,ticker=ticker,
                                            time='1794437000.123456'),
                event_time='1794437000.123456')


def page(kind,*events,verified=False):
    return dict(source=kind,verified=verified,items=list(events))


class FavoritesHistoryPresenceTests(unittest.TestCase):
    def test_subset_reports_presence_but_zero_authoritative_outcomes(self):
        cohort=ev('FAVORITE_ENTRY_COHORT')
        settle=ev('SETTLED')
        quality=ev('FAVORITE_TRIAL_QUALITY')
        summary=summarize_supplied_favorites_evidence([
            page('hot_raw',cohort,settle,quality)])
        self.assertEqual(summary['candidate_ticker_links']['all_three'],1)
        self.assertEqual(summary['event_kind_counts']['FAVORITE_ENTRY_COHORT'],1)
        self.assertEqual(summary['event_kind_counts']['SETTLED'],1)
        self.assertEqual(summary['authoritative_outcome_samples'],0)
        self.assertFalse(summary['financial_reconciliation_complete'])
        self.assertFalse(summary['all_time_coverage_complete'])
        self.assertFalse(summary['safe_to_train'])

    def test_duplicate_original_copies_never_inflate_counts(self):
        cohort=ev('FAVORITE_ENTRY_COHORT')
        a=summarize_supplied_favorites_evidence([
            page('hot_raw',cohort),
            page('r2_reclaimed_raw',dict(cohort),verified=True)])
        self.assertEqual(a['unique_original_events'],1)
        self.assertEqual(a['duplicate_source_copies'],1)
        self.assertEqual(a['event_kind_counts']['FAVORITE_ENTRY_COHORT'],1)

    def test_conflicting_duplicate_fails_not_counts_as_second_outcome(self):
        item=ev('FAVORITE_ENTRY_COHORT')
        wrong=dict(item,progress=dict(item['progress'],ticker='OTHER'))
        with self.assertRaises(HistoryReconciliationError):
            summarize_supplied_favorites_evidence([
                page('hot_raw',item),
                page('r2_reclaimed_raw',wrong,verified=True)])

    def test_partial_subset_does_not_infer_missing_settlement_result(self):
        a=summarize_supplied_favorites_evidence([
            page('hot_raw',ev('FAVORITE_ENTRY_COHORT','A'),
                 ev('SETTLED','B'))])
        self.assertEqual(a['candidate_ticker_links']['cohort_without_supplied_settlement'],1)
        self.assertEqual(a['candidate_ticker_links']['settlement_without_supplied_cohort'],1)
        self.assertEqual(a['authoritative_outcome_samples'],0)

    def test_unknown_and_missing_ticker_do_not_create_fake_event_link(self):
        a=summarize_supplied_favorites_evidence([
            page('hot_raw',ev('FAVORITE_ENTRY_COHORT',None),
                 ev('OTHER_EVENT','A'))])
        self.assertEqual(a['missing_ticker_by_kind']['FAVORITE_ENTRY_COHORT'],1)
        self.assertEqual(a['candidate_ticker_links']['all_three'],0)
        self.assertFalse(a['safe_to_train'])

    def test_unverified_cold_data_rejected(self):
        with self.assertRaises(HistoryReconciliationError):
            summarize_supplied_favorites_evidence([
                page('r2_reclaimed_raw',ev('FAVORITE_ENTRY_COHORT'))])

    def test_many_supplied_originals_still_bounded(self):
        events=[ev('FAVORITE_STAT_DECISION') for _ in range(257)]
        with self.assertRaises(HistoryReconciliationError):
            summarize_supplied_favorites_evidence([page('hot_raw',*events)])


if __name__=='__main__':
    unittest.main()

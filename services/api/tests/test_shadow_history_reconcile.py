"""Pure history reconciliation safety tests; no database, R2, or trading I/O."""
import unittest
from uuid import uuid4

from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages, MAX_INPUT_EVENTS,
)


def event(ident=None, *, value=1, when=100):
    ident = str(ident or uuid4())
    return dict(id=ident, key='demo/shadow/event/' + ident,
                parameters={'series': 'KXTEST'},
                progress={'event': 'FAVORITE_STAT_DECISION',
                          'sample': value, 'time': when},
                event_time=when)


def page(source, *items, verified=False):
    return dict(source=source, items=list(items), verified=verified)


class VerifiedHistoryReconciliationTests(unittest.TestCase):
    def test_repeated_raw_packed_and_r2_copies_count_only_once(self):
        a, b = event(when=200), event(when=100)
        result = reconcile_verified_pages([
            page('hot_raw', a),
            page('hot_packed', b),
            page('r2_reclaimed_raw', dict(a), verified=True),
            page('r2_reclaimed_packed', dict(b), verified=True),
        ])
        self.assertEqual(result['input_events'], 4)
        self.assertEqual(result['unique_events'], 2)
        self.assertEqual(result['duplicate_copies'], 2)
        self.assertEqual([i['id'] for i in result['items']], [b['id'], a['id']])
        self.assertEqual(result['items'][1]['sources'], ['hot_raw', 'r2_reclaimed_raw'])
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertFalse(result['source_exhaustion_verified'])

    def test_conflicting_progress_same_uuid_fails_closed(self):
        first = event()
        changed = event(first['id'], value=2)
        with self.assertRaisesRegex(HistoryReconciliationError, 'Conflicting'):
            reconcile_verified_pages([page('hot_raw', first),
                                      page('r2_reclaimed_raw', changed, verified=True)])

    def test_conflicting_key_same_uuid_fails_closed(self):
        first = event()
        changed = dict(first, key=first['key']+'-alt')
        with self.assertRaises(HistoryReconciliationError):
            reconcile_verified_pages([page('hot_raw', first),
                                      page('hot_raw', changed)])

    def test_reused_key_with_different_uuid_fails_closed(self):
        first, other = event(), event()
        other['key'] = first['key']
        with self.assertRaisesRegex(HistoryReconciliationError, 'key reused'):
            reconcile_verified_pages([page('hot_raw', first, other)])

    def test_unverified_r2_must_not_be_accepted(self):
        for source in ('r2_pointer', 'r2_reclaimed_raw', 'r2_reclaimed_packed'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(HistoryReconciliationError, 'not verified'):
                    reconcile_verified_pages([page(source, event())])

    def test_non_shadow_and_noncanonical_ids_fail(self):
        original = event()
        for altered in (dict(original, key='demo/order/123'),
                        dict(original, id='not-a-uuid'),
                        dict(original, id=original['id'].upper())):
            with self.subTest(altered=altered):
                with self.assertRaises(HistoryReconciliationError):
                    reconcile_verified_pages([page('hot_raw', altered)])

    def test_time_mismatch_and_invalid_payload_fails(self):
        first = event()
        for altered in (dict(first, event_time=999),
                        dict(first, parameters=None),
                        dict(first, progress={'time': float('nan')}),
                        dict(first, event_time=True)):
            with self.subTest(altered=altered):
                with self.assertRaises(HistoryReconciliationError):
                    reconcile_verified_pages([page('hot_raw', altered)])

    def test_financial_or_settlement_progress_is_preserved_exactly(self):
        original = event()
        original['progress'] = {'event': 'SETTLED', 'time': 100,
                                'gross': '109.55', 'fees': '3.05'}
        result = reconcile_verified_pages([page('hot_raw', original)])
        self.assertEqual(result['items'][0]['progress'], original['progress'])

    def test_decimal_string_audit_times_are_supported_without_rewriting_progress(self):
        original=event()
        original['progress']['time']='1794437000.123456'
        original['event_time']='1794437000.123456'
        result=reconcile_verified_pages([page('hot_raw',original)])
        self.assertAlmostEqual(result['items'][0]['event_time'],1794437000.123456)
        self.assertEqual(result['items'][0]['progress']['time'],'1794437000.123456')

    def test_normalized_r2_float_timestamp_matches_original_decimal_string(self):
        original=event()
        original['progress']['time']='1794437000.123456'
        original['event_time']='1794437000.123456'
        first=reconcile_verified_pages([page('r2_reclaimed_raw',original,verified=True)])
        archived=first['items'][0]
        second=reconcile_verified_pages([
            page('r2_reclaimed_raw',archived,verified=True)])
        self.assertEqual(second['unique_events'],1)
        self.assertEqual(second['items'][0]['progress']['time'],'1794437000.123456')
        altered=dict(archived,event_time=1794437000.123999)
        with self.assertRaises(HistoryReconciliationError):
            reconcile_verified_pages([page('r2_reclaimed_raw',altered,verified=True)])

    def test_unsafe_timestamp_strings_rejected(self):
        for value in ('NaN','Infinity','-100','1e10','', '123; DROP TABLE',
                      '1'*42):
            sample=event()
            sample['progress']['time']=value
            sample['event_time']=value
            with self.subTest(value=value):
                with self.assertRaises(HistoryReconciliationError):
                    reconcile_verified_pages([page('hot_raw',sample)])

    def test_null_time_not_invented(self):
        first = event()
        first['progress'].pop('time')
        first['event_time'] = None
        result = reconcile_verified_pages([page('hot_raw', first)])
        self.assertIsNone(result['items'][0]['event_time'])

    def test_bounded_input_and_unsupported_sources(self):
        original = event()
        with self.assertRaisesRegex(HistoryReconciliationError, 'budget'):
            reconcile_verified_pages([page('hot_raw',
                                            *[original for _ in range(MAX_INPUT_EVENTS+1)])])
        with self.assertRaisesRegex(HistoryReconciliationError, 'Unknown'):
            reconcile_verified_pages([page('untrusted', original)])


if __name__ == '__main__':
    unittest.main()

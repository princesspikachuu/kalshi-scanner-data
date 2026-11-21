"""Page continuity is not proof of all-time data coverage."""
import unittest

from services.demo.shadow_page_chain import verify_history_page_chain
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def raw_page(indices, *, cursor=None, more=False, next_cursor=None):
    return dict(source='raw', order='idempotency_key_ascending',
                request_cursor=cursor,
                items=[dict(key='demo/shadow/event/%04d' % i) for i in indices],
                more=more, next_cursor=next_cursor)


def packed_page(indices, *, cursor=None, more=False, next_cursor=None):
    keys=['demo/shadow/event-batch/%04d' % i for i in indices]
    return dict(source='packed', order='idempotency_key_ascending',
                request_cursor=cursor, items=[{'id': str(i)} for i in indices],
                source_keys=keys, more=more, next_cursor=next_cursor)


class PageChainSafetyTests(unittest.TestCase):
    def test_valid_raw_cursor_chain_is_not_claimed_all_time_complete(self):
        a=raw_page([1,2],more=True,next_cursor='demo/shadow/event/0002')
        b=raw_page([3],cursor='demo/shadow/event/0002')
        result=verify_history_page_chain([a,b],'raw')
        self.assertTrue(result['pagination_chain_verified'])
        self.assertFalse(result['database_snapshot_verified'])
        self.assertFalse(result['r2_manifest_catalog_complete'])
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertEqual(result['supplied_keys'],3)

    def test_valid_packed_source_key_chain(self):
        a=packed_page([1],more=True,next_cursor='demo/shadow/event-batch/0001')
        b=packed_page([2],cursor='demo/shadow/event-batch/0001')
        result=verify_history_page_chain([a,b],'packed')
        self.assertEqual(result['supplied_keys'],2)
        self.assertFalse(result['all_time_coverage_complete'])

    def test_missing_or_repeated_pages_fail_closed(self):
        first=raw_page([1],more=True,next_cursor='demo/shadow/event/0001')
        for chain in ([first], [first,raw_page([2])],
                      [first,raw_page([1],cursor='demo/shadow/event/0001')],
                      [raw_page([2,1])],
                      [raw_page([1],more=False,next_cursor='demo/shadow/event/0001')],
                      [raw_page([1]),raw_page([2])]):
            with self.subTest(chain=chain):
                with self.assertRaises(HistoryReconciliationError):
                    verify_history_page_chain(chain,'raw')

    def test_requires_explicit_source_keys_and_rejects_wrong_namespace(self):
        first=packed_page([1])
        first.pop('source_keys')
        with self.assertRaisesRegex(HistoryReconciliationError, 'source keys'):
            verify_history_page_chain([first],'packed')
        wrong=raw_page([1])
        wrong['items'][0]['key']='demo/order/0001'
        with self.assertRaises(HistoryReconciliationError):
            verify_history_page_chain([wrong],'raw')

    def test_manifest_pages_need_trustworthy_indexed_keys(self):
        empty=dict(order='manifest_key',request_cursor=None,items=[{'manifest_id':'test'}],
                   more=False,next_cursor=None)
        with self.assertRaises(HistoryReconciliationError):
            verify_history_page_chain([empty],'manifests')
        keyed=dict(empty,items=[dict(manifest_key='demo/shadow/archive-manifest/0001')])
        result=verify_history_page_chain([keyed],'manifests')
        self.assertFalse(result['r2_manifest_catalog_complete'])
        self.assertFalse(result['all_time_coverage_complete'])

    def test_source_row_and_original_count_tampering_fails(self):
        raw=raw_page([1])
        for changed in (dict(raw,source_rows=2),
                        dict(raw,original_events=0)):
            with self.subTest(changed=changed):
                with self.assertRaises(HistoryReconciliationError):
                    verify_history_page_chain([changed],'raw')
        packed=packed_page([1])
        for changed in (dict(packed,source_keys=[]),
                        dict(packed,source_rows=2),
                        dict(packed,original_events=0)):
            with self.subTest(changed=changed):
                with self.assertRaises(HistoryReconciliationError):
                    verify_history_page_chain([changed],'packed')

    def test_rejects_unbounded_and_missing_pages(self):
        with self.assertRaises(HistoryReconciliationError):
            verify_history_page_chain([],'raw')
        with self.assertRaises(HistoryReconciliationError):
            verify_history_page_chain([raw_page([]) for _ in range(65)],'raw')


if __name__ == '__main__':
    unittest.main()

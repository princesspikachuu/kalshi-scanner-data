"""Rolling receipts preserve original identities without unbounded memory."""
import unittest
from uuid import UUID

from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_streaming_receipt import (
    extend_ordered_receipt, MAX_RECEIPT_CHUNK,
)


def item(n, amount='1.00'):
    ident = str(UUID(int=n))
    return dict(id=ident, key='demo/shadow/event/'+ident, parameters={'series':'KXTEST'},
                progress={'event':'FAVORITE_STAT_DECISION',
                          'time':'1794437000.123456','amount':amount},
                event_time=1794437000.123456)


def source(entry, name='hot_raw', verified=False):
    return dict(source=name, verified=verified, item=entry)


class OrderedReceiptTests(unittest.TestCase):
    def test_cross_chunk_duplicate_counted_once_and_digest_stable(self):
        a,b,c=(item(i) for i in (1,2,3))
        first=extend_ordered_receipt(None,[source(a),source(b)])
        final=extend_ordered_receipt(first,[
            source(dict(b), 'r2_reclaimed_raw', True),
            source(c,'r2_reclaimed_packed',True)])
        direct=extend_ordered_receipt(None,[source(a),source(b),source(c)])
        self.assertEqual(final['original_events'],3)
        self.assertEqual(final['duplicate_source_copies'],1)
        self.assertEqual(final['chain_digest'],direct['chain_digest'])
        self.assertEqual(final['checked_chunks'],2)
        self.assertFalse(final['all_time_coverage_complete'])
        self.assertFalse(final['safe_to_train'])

    def test_conflicting_cross_chunk_copy_fails_closed(self):
        old=item(1)
        initial=extend_ordered_receipt(None,[source(old)])
        with self.assertRaisesRegex(HistoryReconciliationError,'Conflicting'):
            extend_ordered_receipt(initial,[
                source(item(1,'999.99'),'r2_reclaimed_raw',True)])

    def test_out_of_order_or_dropped_cursor_fails(self):
        first=extend_ordered_receipt(None,[source(item(2))])
        with self.assertRaisesRegex(HistoryReconciliationError,'ordered'):
            extend_ordered_receipt(first,[source(item(1))])
        with self.assertRaisesRegex(HistoryReconciliationError,'ordered'):
            extend_ordered_receipt(None,[source(item(3)),source(item(2))])

    def test_unverified_and_unknown_sources_fail(self):
        with self.assertRaisesRegex(HistoryReconciliationError,'Unverified'):
            extend_ordered_receipt(None,[source(item(1),'r2_reclaimed_raw')])
        with self.assertRaisesRegex(HistoryReconciliationError,'source'):
            extend_ordered_receipt(None,[source(item(1),'made_up',True)])

    def test_bounded_chunks_and_invalid_prior_receipt_fail(self):
        with self.assertRaises(HistoryReconciliationError):
            extend_ordered_receipt(None,[source(item(i+1)) for i in range(MAX_RECEIPT_CHUNK+1)])
        with self.assertRaises(HistoryReconciliationError):
            extend_ordered_receipt(None,[])
        state=extend_ordered_receipt(None,[source(item(1))])
        for forged in (dict(state,chain_digest='not-a-digest'),
                       dict(state,original_events=-1),
                       dict(state,last_original_id='not-uuid')):
            with self.subTest(forged=forged):
                with self.assertRaises(HistoryReconciliationError):
                    extend_ordered_receipt(forged,[source(item(2))])

    def test_normalized_time_preserves_original_progress_and_settlement_fields(self):
        original=item(1)
        original['progress']={'event':'SETTLED','time':'1794437000.123456',
                              'net':'1.22','fees':'0.04'}
        receipt=extend_ordered_receipt(None,[source(original)])
        self.assertEqual(receipt['original_events'],1)
        self.assertEqual(original['progress']['net'],'1.22')
        self.assertEqual(receipt['authoritative_financial_outcomes'],0)
        self.assertFalse(receipt['safe_to_restart_writers'])

    def test_many_chunks_same_deterministic_digest_as_one_pass(self):
        originals=[source(item(i)) for i in range(1,221)]
        direct=extend_ordered_receipt(None, originals)
        partial=None
        for start in range(0,len(originals),17):
            partial=extend_ordered_receipt(partial,originals[start:start+17])
        self.assertEqual(partial['original_events'],220)
        self.assertEqual(partial['chain_digest'],direct['chain_digest'])


if __name__=='__main__':
    unittest.main()

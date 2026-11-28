"""Read-only indexed source receipts never assert full data completeness."""
import unittest

from services.demo.shadow_keyset_receipts import extend_keyset_receipt
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def page(source, numbers, *, cursor=None, more=False):
    prefix={'raw':'demo/shadow/event/','packed':'demo/shadow/event-batch/',
            'manifests':'demo/shadow/archive-manifest/'}[source]
    keys=[prefix+f'{n:04d}' for n in numbers]
    items=[dict(manifest_key=k,original_events=12) for k in keys] if source=='manifests' else [
        dict(key=k) for k in keys]
    result=dict(source=source,order='manifest_key' if source=='manifests'
                else 'idempotency_key_ascending',
                request_cursor=cursor,items=items,more=more,
                next_cursor=keys[-1] if more else None)
    if source!='manifests':
        result.update(source_keys=keys,source_rows=len(keys),
                      original_events=len(items))
    return result


class KeysetRollingReceiptTests(unittest.TestCase):
    def test_two_raw_pages_with_real_cursor_receipt(self):
        a=extend_keyset_receipt(None,'raw',page('raw',[1,2],more=True))
        b=extend_keyset_receipt(a,'raw',page('raw',[3,4],
                                            cursor='demo/shadow/event/0002'))
        self.assertTrue(b['terminal'])
        self.assertEqual(b['source_rows'],4)
        self.assertEqual(b['original_events'],4)
        self.assertEqual(b['pages_seen'],2)
        self.assertFalse(b['stable_database_snapshot_verified'])
        self.assertFalse(b['all_time_coverage_complete'])

    def test_reject_skipped_wrong_or_repeated_cursor(self):
        a=extend_keyset_receipt(None,'raw',page('raw',[1],more=True))
        for altered in (
            page('raw',[2]),page('raw',[2],cursor='demo/shadow/event/0000'),
            page('raw',[1],cursor='demo/shadow/event/0001'),
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(HistoryReconciliationError):
                    extend_keyset_receipt(a,'raw',altered)

    def test_terminal_cannot_accept_extra_page(self):
        a=extend_keyset_receipt(None,'raw',page('raw',[1]))
        with self.assertRaisesRegex(HistoryReconciliationError,'terminal'):
            extend_keyset_receipt(a,'raw',page('raw',[2]))

    def test_packed_expansion_has_separate_source_row_and_original_counts(self):
        p=page('packed',[1])
        p['items']=[dict(key='demo/shadow/event/one'),
                    dict(key='demo/shadow/event/two')]
        p['original_events']=2
        receipt=extend_keyset_receipt(None,'packed',p)
        self.assertEqual(receipt['source_rows'],1)
        self.assertEqual(receipt['original_events'],2)
        bad=dict(p,original_events=1)
        with self.assertRaises(HistoryReconciliationError):
            extend_keyset_receipt(None,'packed',bad)

    def test_manifest_source_counts_are_not_verified_original_events(self):
        receipt=extend_keyset_receipt(None,'manifests',page('manifests',[1,2]))
        self.assertEqual(receipt['source_rows'],2)
        self.assertEqual(receipt['manifest_originals_claimed'],24)
        self.assertEqual(receipt['original_events'],0)
        self.assertFalse(receipt['r2_manifest_catalog_complete'])
        bad=page('manifests',[1])
        bad['items'][0]['original_events']='12'
        with self.assertRaises(HistoryReconciliationError):
            extend_keyset_receipt(None,'manifests',bad)

    def test_invalid_page_metadata_and_forged_receipt_refused(self):
        p=page('raw',[1])
        for bad in (dict(p,source='packed'),dict(p,order='manifest_key'),
                    dict(p,source_rows=2),dict(p,original_events=2),
                    dict(p,source_keys=[]),dict(p,more=True),
                    dict(p,more=False,next_cursor='demo/shadow/event/0001')):
            with self.subTest(bad=bad):
                with self.assertRaises(HistoryReconciliationError):
                    extend_keyset_receipt(None,'raw',bad)
        good=extend_keyset_receipt(None,'raw',p)
        for prior in (dict(good,source_key_digest='wrong'),
                      dict(good,source_rows=-1),dict(good,source='packed'),
                      dict(good,terminal=False)):
            with self.subTest(prior=prior):
                with self.assertRaises(HistoryReconciliationError):
                    extend_keyset_receipt(prior,'raw',page('raw',[2],
                                         cursor='demo/shadow/event/0001'))

    def test_chunking_independent_source_digest(self):
        one=extend_keyset_receipt(None,'raw',page('raw',[1,2,3,4]))
        first=extend_keyset_receipt(None,'raw',page('raw',[1,2],more=True))
        second=extend_keyset_receipt(first,'raw',page('raw',[3,4],
                                                     cursor='demo/shadow/event/0002'))
        self.assertEqual(one['source_key_digest'],second['source_key_digest'])
        self.assertEqual(one['source_rows'],second['source_rows'])

    def test_empty_first_page_is_valid_terminal_only(self):
        receipt=extend_keyset_receipt(None,'raw',page('raw',[]))
        self.assertTrue(receipt['terminal'])
        self.assertEqual(receipt['source_rows'],0)
        self.assertFalse(receipt['all_time_coverage_complete'])


if __name__=='__main__':
    unittest.main()

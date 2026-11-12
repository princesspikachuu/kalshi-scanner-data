"""Require every original event from one manifest; do not infer catalog completeness."""
import unittest
from uuid import uuid4
from services.demo.shadow_reclaimed_chain import verify_reclaimed_manifest_chain
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def make_pages(total=3, first_size=2):
    ident=str(uuid4())
    key='demo/shadow/archive-manifest/'+ident
    original=[dict(id=str(uuid4())) for _ in range(total)]
    a=dict(manifest_id=ident,manifest_key=key,manifest_digest='a'*64,
           source='r2_reclaimed_raw',
           total_events=total,offset=0,page_events=first_size,
           items=original[:first_size],next_offset=first_size if first_size<total else None,
           verified=True)
    if first_size==total:return [a]
    b=dict(a,offset=first_size,page_events=total-first_size,
           items=original[first_size:],next_offset=None)
    return [a,b]


class ReclaimedChainTests(unittest.TestCase):
    def test_full_reclaimed_manifest_exhausted_but_catalog_not_complete(self):
        result=verify_reclaimed_manifest_chain(make_pages())
        self.assertTrue(result['individual_manifest_exhausted'])
        self.assertEqual(result['original_events_verified'],3)
        self.assertFalse(result['source_exhaustion_verified'])
        self.assertFalse(result['r2_manifest_catalog_complete'])
        self.assertFalse(result['all_time_coverage_complete'])

    def test_legacy_independent_key_uuid_allowed_but_wrong_kind_rejected(self):
        first=make_pages(1,1)
        first[0]['manifest_key']='demo/shadow/archive-manifest/'+str(uuid4())
        receipt=verify_reclaimed_manifest_chain(first)
        self.assertTrue(receipt['individual_manifest_exhausted'])
        for bad in (
            'demo/shadow/archive-manifest/batch/'+str(uuid4()),
            'demo/shadow/archive-manifest/not-a-uuid',
            'demo/shadow/archive-manifest-extra/'+str(uuid4()),
        ):
            with self.subTest(key=bad):
                with self.assertRaises(HistoryReconciliationError):
                    verify_reclaimed_manifest_chain([dict(first[0],manifest_key=bad)])
        packed=[dict(first[0],source='r2_reclaimed_packed',
                     manifest_key='demo/shadow/archive-manifest/batch/'+str(uuid4()))]
        self.assertTrue(verify_reclaimed_manifest_chain(packed)['individual_manifest_exhausted'])
        with self.assertRaises(HistoryReconciliationError):
            verify_reclaimed_manifest_chain([
                dict(packed[0],manifest_key='demo/shadow/archive-manifest/'+str(uuid4()))])

    def test_missing_page_or_skipped_offset_fails(self):
        pages=make_pages()
        for modified in ([pages[0]], [pages[1]],
                         [pages[0],dict(pages[1],offset=3)],
                         [pages[0],dict(pages[1],next_offset=3)],
                         [pages[0],dict(pages[1],manifest_id=str(uuid4()))],
                         [pages[0],dict(pages[1],verified=False)]):
            with self.subTest(modified=modified):
                with self.assertRaises(HistoryReconciliationError):
                    verify_reclaimed_manifest_chain(modified)

    def test_changed_manifest_content_digest_fails(self):
        pages=make_pages()
        replaced=dict(pages[1],manifest_digest='b'*64)
        with self.assertRaises(HistoryReconciliationError):
            verify_reclaimed_manifest_chain([pages[0],replaced])

    def test_repeated_original_id_fails(self):
        pages=make_pages()
        second=dict(pages[1],items=[dict(pages[0]['items'][0])])
        with self.assertRaisesRegex(HistoryReconciliationError,'Repeated'):
            verify_reclaimed_manifest_chain([pages[0],second])

    def test_oversize_and_missing_metadata_fails(self):
        pages=make_pages(1,1)
        for bad in ([],pages*129,[dict(pages[0],total_events=10001)],
                    [dict(pages[0],page_events=True)],
                    [dict(pages[0],source='hot_raw')]):
            with self.subTest(bad=bad):
                with self.assertRaises(HistoryReconciliationError):
                    verify_reclaimed_manifest_chain(bad)


if __name__ == '__main__':
    unittest.main()

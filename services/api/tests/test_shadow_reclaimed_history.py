"""Reclaimed R2 pages retain full original identities and fail closed."""
import unittest
from uuid import uuid4
from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_reclaimed_history import normalize_reclaimed_manifest_page


def archived(kind='raw', count=2):
    manifest_id=str(uuid4())
    manifest_key='demo/shadow/archive-manifest/'+('batch/' if kind=='packed' else '')+manifest_id
    events=[]
    for i in range(count):
        ident=str(uuid4())
        events.append(dict(id=ident,key='demo/shadow/event/'+ident,
                           parameters=dict(index=i,series='TEST'),
                           progress=dict(event='FAVORITE_STAT_DECISION',time=100+i,
                                         amount_cents=i+50)))
    return dict(manifest=dict(manifest_id=manifest_id,manifest_key=manifest_key,
                              kind=kind,original_events=count),
                source='cloudflare-r2',verified=True,
                total_events=count,items=events,next_offset=None)


class ReclaimedManifestHistoryTests(unittest.TestCase):
    def test_raw_reclaimed_page_retains_original_id_and_financial_fields(self):
        result=archived()
        page=normalize_reclaimed_manifest_page(result,offset=0)
        self.assertEqual({x['id'] for x in page['items']},
                         {x['id'] for x in result['items']})
        self.assertEqual(page['items'][0]['progress']['amount_cents'],50)
        self.assertEqual(page['source'],'r2_reclaimed_raw')
        self.assertEqual(page['page_events'],2)
        self.assertFalse(page['all_time_coverage_complete'])
        self.assertFalse(page['r2_manifest_catalog_complete'])

    def test_packed_partial_page_preserves_originals_and_exact_next_offset(self):
        result=archived('packed',3)
        result['items']=result['items'][:2]
        result['next_offset']=2
        page=normalize_reclaimed_manifest_page(result,offset=0)
        self.assertEqual(page['source'],'r2_reclaimed_packed')
        self.assertEqual(page['next_offset'],2)
        self.assertEqual(page['total_events'],3)
        self.assertFalse(page['source_exhaustion_verified'])

    def test_settled_progress_preserved(self):
        result=archived(count=1)
        result['items'][0]['progress']=dict(event='SETTLED',time=100,net='1.22',fees='0.04')
        page=normalize_reclaimed_manifest_page(result,offset=0)
        self.assertEqual(page['items'][0]['progress'],result['items'][0]['progress'])

    def test_invalid_or_unverified_receipts_fail_closed(self):
        for change in (
            dict(verified=False),dict(source='other'),
            dict(total_events=3),dict(next_offset=1),
            dict(manifest=dict(kind='other')),
        ):
            result=archived()
            result.update(change)
            with self.subTest(change=change):
                with self.assertRaises(HistoryReconciliationError):
                    normalize_reclaimed_manifest_page(result,offset=0)

    def test_invalid_original_id_or_conflicting_key_rejected(self):
        result=archived()
        result['items'][1]['id']=result['items'][0]['id']
        with self.assertRaises(HistoryReconciliationError):
            normalize_reclaimed_manifest_page(result,offset=0)
        result=archived()
        result['items'][1]['key']=result['items'][0]['key']
        with self.assertRaises(HistoryReconciliationError):
            normalize_reclaimed_manifest_page(result,offset=0)

    def test_bounds_and_cursors_fail_closed(self):
        result=archived()
        for offset in (-1,True,10001,2):
            with self.subTest(offset=offset):
                with self.assertRaises(HistoryReconciliationError):
                    normalize_reclaimed_manifest_page(result,offset=offset)
        result=archived()
        result['items']=[]
        with self.assertRaises(HistoryReconciliationError):
            normalize_reclaimed_manifest_page(result,offset=0)

    def test_timestamp_conflict_cannot_pass(self):
        result=archived()
        result['items'][0]['progress']['time']=float('nan')
        with self.assertRaises(HistoryReconciliationError):
            normalize_reclaimed_manifest_page(result,offset=0)


if __name__ == '__main__':
    unittest.main()

"""Partial multi-source receipts never establish missing global coverage."""
import unittest
from copy import deepcopy
from uuid import uuid4

from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_multisource_preview import reconcile_supplied_history

RAW='demo/shadow/event/'
PACKED='demo/shadow/event-batch/'
MANIFEST='demo/shadow/archive-manifest/'


def event(ident=None,amount='1.25'):
    ident=str(ident or uuid4())
    return dict(id=ident,key=RAW+ident,parameters=dict(strategy='favorites'),
                progress=dict(event='FAVORITE_STAT_DECISION',
                              time='1794437000.123456',amount=amount),
                event_time='1794437000.123456')


def hot(source,items):
    if source=='raw':
        return dict(source='raw',order='idempotency_key_ascending',
                    request_cursor=None,items=sorted(items,key=lambda x:x['key']),
                    more=False,next_cursor=None)
    key=PACKED+str(uuid4())
    return dict(source='packed',order='idempotency_key_ascending',
                request_cursor=None,source_keys=[key],items=items,
                more=False,next_cursor=None)


def fixture():
    original=event()
    ident=str(uuid4())
    key=MANIFEST+ident
    digest='a'*64
    summary=dict(manifest_id=ident,manifest_key=key,manifest_digest=digest,
                 kind='raw',original_events=1)
    catalog=[dict(source='manifests',order='manifest_key',
                  request_cursor=None,items=[summary],more=False,next_cursor=None)]
    cold=[dict(source='r2_reclaimed_raw',verified=True,
               manifest_id=ident,manifest_key=key,manifest_digest=digest,
               total_events=1,offset=0,page_events=1,items=[deepcopy(original)],
               next_offset=None)]
    return original,[hot('raw',[original])],[hot('packed',[event()])],catalog,{ident:cold}


class MultiSourcePreviewTests(unittest.TestCase):
    def test_original_duplicates_count_once_and_history_is_still_incomplete(self):
        original,raw,packed,catalog,cold=fixture()
        result=reconcile_supplied_history(raw,packed,catalog,cold)
        self.assertEqual(result['unique_original_events'],2)
        self.assertEqual(result['duplicate_source_copies'],1)
        self.assertEqual(result['supplied_archived_manifests'],1)
        self.assertEqual(result['items'][0]['progress']['amount'],'1.25')
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertFalse(result['r2_manifest_catalog_complete'])
        self.assertFalse(result['database_snapshot_verified'])
        self.assertFalse(result['safe_to_train'])
        self.assertFalse(result['safe_to_restart_writers'])

    def test_reject_missing_catalog_manifest_or_r2_pages(self):
        original,raw,packed,catalog,cold=fixture()
        for missing in ({},dict(cold,extra=[])):
            with self.subTest(missing=missing):
                with self.assertRaises(HistoryReconciliationError):
                    reconcile_supplied_history(raw,packed,catalog,missing)

    def test_reject_changed_archive_payload_across_hot_and_r2(self):
        original,raw,packed,catalog,cold=fixture()
        key=next(iter(cold))
        cold[key][0]['items'][0]['progress']['amount']='999999'
        with self.assertRaisesRegex(HistoryReconciliationError,'Conflicting'):
            reconcile_supplied_history(raw,packed,catalog,cold)

    def test_reject_changed_catalog_metadata(self):
        original,raw,packed,catalog,cold=fixture()
        catalog[0]['items'][0]['manifest_digest']='b'*64
        with self.assertRaises(HistoryReconciliationError):
            reconcile_supplied_history(raw,packed,catalog,cold)

    def test_reject_unfinished_postgres_page_chain(self):
        original,raw,packed,catalog,cold=fixture()
        raw[0]['more']=True
        raw[0]['next_cursor']=original['key']
        with self.assertRaises(HistoryReconciliationError):
            reconcile_supplied_history(raw,packed,catalog,cold)

    def test_reject_unverified_reclaimed_chain(self):
        original,raw,packed,catalog,cold=fixture()
        cold[next(iter(cold))][0]['verified']=False
        with self.assertRaises(HistoryReconciliationError):
            reconcile_supplied_history(raw,packed,catalog,cold)

    def test_empty_manifest_catalog_requires_no_cold_sources(self):
        source=event()
        raw=[hot('raw',[source])]
        packed=[dict(source='packed',order='idempotency_key_ascending',
                     request_cursor=None,source_keys=[],items=[],
                     more=False,next_cursor=None)]
        manifests=[dict(source='manifests',order='manifest_key',
                        request_cursor=None,items=[],more=False,next_cursor=None)]
        result=reconcile_supplied_history(raw,packed,manifests,{})
        self.assertEqual(result['unique_original_events'],1)
        self.assertFalse(result['all_time_coverage_complete'])

    def test_invalid_archive_manifest_stops_preview(self):
        original,raw,packed,catalog,cold=fixture()
        catalog[0]['items'].append(dict(catalog[0]['items'][0]))
        with self.assertRaises(HistoryReconciliationError):
            reconcile_supplied_history(raw,packed,catalog,cold)


if __name__=='__main__':
    unittest.main()

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


    def test_reclaimed_and_hot_duplicate_counted_once_with_original_payload(self):
        from services.demo.shadow_history_reconcile import reconcile_verified_pages
        result=archived(count=1)
        cold=normalize_reclaimed_manifest_page(result,offset=0)
        original=result['items'][0]
        hot=dict(id=original['id'],key=original['key'],
                 parameters=original['parameters'],progress=original['progress'],
                 event_time=original['progress']['time'])
        combined=reconcile_verified_pages([
            dict(source='hot_raw',items=[hot]),
            dict(source=cold['source'],items=cold['items'],verified=cold['verified'])
        ])
        self.assertEqual(combined['input_events'],2)
        self.assertEqual(combined['unique_events'],1)
        self.assertEqual(combined['duplicate_copies'],1)
        self.assertFalse(combined['all_time_coverage_complete'])
        self.assertEqual(combined['items'][0]['sources'],
                         ['hot_raw','r2_reclaimed_raw'])

    def test_modified_reclaimed_copy_not_counted_as_separate_success(self):
        from services.demo.shadow_history_reconcile import reconcile_verified_pages
        result=archived(count=1)
        cold=normalize_reclaimed_manifest_page(result,offset=0)
        original=result['items'][0]
        modified=dict(id=original['id'],key=original['key'],
                      parameters=original['parameters'],
                      progress=dict(original['progress'],amount_cents=100000),
                      event_time=original['progress']['time'])
        with self.assertRaises(HistoryReconciliationError):
            reconcile_verified_pages([
                dict(source='hot_raw',items=[modified]),
                dict(source=cold['source'],items=cold['items'],verified=True)
            ])

    def test_owner_route_requires_auth_and_does_not_serve_unverified_data(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from unittest.mock import MagicMock, patch
        from services.api.shadow import install_shadow
        identifier=str(uuid4())
        uri='/demo/shadow/history/reclaimed/'+identifier
        app=FastAPI()
        install_shadow(app,lambda request: (_ for _ in ()).throw(
            HTTPException(403,'Owner authentication required')),MagicMock(),MagicMock())
        self.assertEqual(TestClient(app).get(uri).status_code,403)
        app=FastAPI()
        install_shadow(app,lambda request: True,MagicMock(),MagicMock())
        client=TestClient(app)
        for suffix in ('?offset=-1','?limit=0','?limit=51','?unknown=1',
                       '?offset=2&offset=3'):
            with self.subTest(suffix=suffix):
                self.assertEqual(client.get(uri+suffix).status_code,422)
        self.assertEqual(client.get('/demo/shadow/history/reclaimed/not-a-uuid').status_code,422)
        with patch('services.demo.shadow_archive_reader.read_manifest_events',
                   return_value=archived(count=1)):
            response=client.get(uri)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['source'],'r2_reclaimed_raw')
        self.assertFalse(response.json()['all_time_coverage_complete'])
        with patch('services.demo.shadow_archive_reader.read_manifest_events',
                   return_value=dict(archived(count=1),verified=False)):
            response=client.get(uri)
        self.assertEqual(response.status_code,503)
        self.assertIn('could not be verified',response.text)
        self.assertNotIn('hidden-credential',response.text)
        with patch('services.demo.shadow_archive_reader.read_manifest_events',
                   return_value=None):
            self.assertEqual(client.get(uri).status_code,404)

    def test_owner_route_cold_read_gate_denied_without_credentials(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from unittest.mock import MagicMock,patch
        from services.api.shadow import install_shadow
        from services.demo.shadow_archive_reader import ArchiveReaderUnavailable
        app=FastAPI()
        install_shadow(app,lambda request: True,MagicMock(),MagicMock())
        with patch('services.demo.shadow_archive_reader.read_manifest_events',
                   side_effect=ArchiveReaderUnavailable('hidden-credential')):
            response=TestClient(app).get('/demo/shadow/history/reclaimed/'+str(uuid4()))
        self.assertEqual(response.status_code,503)
        self.assertNotIn('hidden-credential',response.text)


if __name__ == '__main__':
    unittest.main()

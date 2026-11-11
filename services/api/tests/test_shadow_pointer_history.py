"""MT-019: recent Favorites decision history must survive cold R2 pointers."""
import io
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.demo.maintenance import put_verified
from services.demo.shadow_archive_recovery import PREFIX, archive_payload
from services.demo.shadow_archive_reader import ArchiveReaderUnavailable
from services.demo.legacy_event_archive import FORMAT
from services.demo.shadow_pointer_history import (
    MAX_COLD_OBJECTS_PER_PAGE, rehydrate_event_rows,
)


class MemoryR2:
    def __init__(self):
        self.bucket='private-test'
        self.blobs={}
        self.client=self
        self.gets=0
        self.closed=False

    def put_object(self, **kw):
        self.blobs[kw['Key']]=kw['Body']

    def get_object(self, **kw):
        self.gets+=1
        blob=self.blobs[kw['Key']]
        return dict(ContentLength=len(blob),Body=io.BytesIO(blob))

    def close(self):
        self.closed=True


class ColdDiagnosticPointerTests(unittest.TestCase):
    def source(self, ident=None, progress=None):
        ident=ident or str(uuid4())
        at=datetime(2026,10,1,tzinfo=timezone.utc)
        return dict(id=ident,idempotency_key=PREFIX+ident,
                    asset='crypto',status='succeeded',
                    parameters=dict(kind='EXPERIMENT'),
                    progress=progress or dict(event='FAVORITE_STAT_DECISION',
                                              decision='precious sample'),
                    created_at=at,started_at=at,finished_at=at,
                    lease_expires_at=None,attempts=1,error_code=None,
                    available_at=at,max_attempts=3,lease_token=None)

    def archived(self, sources, store=None):
        store=store or MemoryR2()
        original=archive_payload(sources)
        receipt=put_verified(store,'events',dict(
            format=FORMAT,source_prefix=PREFIX,
            ids=[r['id'] for r in original],count=len(original),
            records=original,created_at=1794500000))
        pointers=[dict(row,progress=dict(archive=receipt,archived=True,
                                        archive_format=FORMAT))
                  for row in sources]
        return pointers,store

    def test_hot_events_do_not_attempt_r2_or_require_configuration(self):
        row=self.source()
        calls=[]
        def connect(_):
            calls.append(1)
            raise AssertionError('R2 network should not be opened')
        actual,count,objects=rehydrate_event_rows([row],
                                                   store_factory=connect)
        self.assertEqual(actual,[row])
        self.assertEqual((count,objects),(0,0))
        self.assertEqual(calls,[])

    def test_real_gzip_sha_roundtrip_restores_source_event_for_dashboard(self):
        rows=[self.source(),self.source()]
        original=[r['progress'] for r in rows]
        pointers,store=self.archived(rows)
        existing_readbacks=store.gets  # put_verified already verifies R2 once
        restored,count,objects=rehydrate_event_rows(
            pointers,env=dict(MT_ARCHIVE_V2_POINTER_READ_ENABLED='true'),
            store_factory=lambda _:store)
        self.assertEqual([r['progress'] for r in restored],original)
        self.assertEqual((count,objects),(2,1))
        self.assertEqual(store.gets,existing_readbacks+1)
        self.assertTrue(store.closed)
        self.assertEqual(pointers[0]['progress']['archived'],True)

    def test_missing_read_only_credentials_returns_failure_not_partial_success(self):
        pointer,_=self.archived([self.source()])
        with self.assertRaises(ArchiveReaderUnavailable):
            rehydrate_event_rows(pointer,env={})
        with self.assertRaises(ArchiveReaderUnavailable):
            rehydrate_event_rows(pointer,env=dict(MT_ARCHIVE_READ_ENABLED='true'))

    def test_tampered_metadata_and_bad_kind_rejected_before_dashboard_return(self):
        original=self.source()
        for variant in ('parameters','timestamp','missing','settlement'):
            with self.subTest(variant=variant):
                row=dict(original)
                if variant=='parameters':
                    row['parameters']=dict(kind='ALTERED')
                if variant=='timestamp':
                    row['created_at']=datetime(2026,10,2,tzinfo=timezone.utc)
                badsource=dict(original)
                if variant=='settlement':
                    badsource['progress']=dict(event='SETTLED',cash_cents=150)
                pointers,store=self.archived([badsource])
                if variant=='missing':
                    pointers[0]['id']=str(uuid4())
                elif variant in ('parameters','timestamp'):
                    pointers[0]=dict(pointers[0],
                                     **{variant if variant=='parameters'
                                        else 'created_at':
                                        row[variant if variant=='parameters'
                                            else 'created_at']})
                with self.assertRaises(ValueError):
                    rehydrate_event_rows(
                        pointers,
                        env=dict(MT_ARCHIVE_V2_POINTER_READ_ENABLED='true'),
                        store_factory=lambda _:store)
                self.assertTrue(store.closed)

    def test_invalid_receipt_and_unbounded_page_fail_before_r2_network(self):
        original=self.source()
        pointers,_=self.archived([original])
        def never(_):
            raise AssertionError('Must reject before R2 I/O')
        for bad in ('../../secrets','demo/events/notahash.json.gz'):
            with self.subTest(bad=bad):
                ptr=dict(pointers[0],progress=dict(pointers[0]['progress']))
                ptr['progress']['archive']=dict(ptr['progress']['archive'],key=bad)
                with self.assertRaises(ValueError):
                    rehydrate_event_rows([ptr],env=dict(
                        MT_ARCHIVE_V2_POINTER_READ_ENABLED='true'),
                        store_factory=never)
        many=[]
        for i in range(MAX_COLD_OBJECTS_PER_PAGE+1):
            receipt=dict(pointers[0]['progress']['archive'])
            receipt['sha256']=f'{i:064x}'
            receipt['key']='demo/events/'+receipt['sha256']+'.json.gz'
            many.append(dict(pointers[0],id=str(uuid4()),
                             progress=dict(pointers[0]['progress'],
                                           archive=receipt)))
        with self.assertRaises(ValueError):
            rehydrate_event_rows(
                many,env=dict(MT_ARCHIVE_V2_POINTER_READ_ENABLED='true'),
                store_factory=never)

    def test_route_fail_closed_does_not_disguise_unread_archives_as_events(self):
        from services.api.shadow import install_shadow
        source=self.source()
        pointers,_=self.archived([source])
        pool=MagicMock()
        db=pool.connection.return_value.__enter__.return_value
        def exec_sql(sql,*args):
            cursor=MagicMock()
            cursor.fetchall.return_value=pointers if 'idempotency_key,parameters' in sql else []
            return cursor
        db.execute.side_effect=exec_sql
        app=FastAPI()
        install_shadow(app,lambda _: True,MagicMock(),pool)
        client=TestClient(app)
        with patch('services.demo.shadow_pointer_history.rehydrate_event_rows',
                   side_effect=ArchiveReaderUnavailable('secret')):
            response=client.get('/demo/shadow/events')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('secret',response.text)
        with patch('services.demo.shadow_pointer_history.rehydrate_event_rows',
                   return_value=( [dict(pointers[0],progress=source['progress'])],
                                  1,1 )):
            response=client.get('/demo/shadow/events')
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body['items'][0]['decision'],'precious sample')
        self.assertTrue(body['recent_history_complete'])
        self.assertEqual(body['archived_rows_rehydrated'],1)
        self.assertEqual(body['archive_objects_verified'],1)


if __name__ == '__main__':
    unittest.main()

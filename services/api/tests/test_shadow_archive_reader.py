"""Verified R2 cold history remains owner-only, bounded, and read-only."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.demo.shadow_archive_reader import (
    PREFIX, MANIFEST_SCAN, MANIFEST_BY_ID, ArchiveReaderUnavailable,
    validate_page, list_manifests, find_manifest, read_manifest_events, read_store
)


class ShadowArchiveReaderTests(unittest.TestCase):
    def manifest(self, packed=False, index='1'):
        ident = '11111111-1111-1111-1111-%012d' % int(index)
        kind = 'diagnostic_batch_r2_manifest' if packed else 'shadow_event_r2_manifest'
        progress = dict(format='shadow-diagnostic-r2-manifest-v1' if packed
                        else 'shadow-r2-event-batch-v1',
                        reference=dict(key='demo/events/abc.json.gz',size=56,sha256='a'*64),
                        count=1, earliest='2026-11-09T00:00:00+00:00',
                        latest='2026-11-09T01:00:00+00:00')
        if packed:
            progress.update(row_ids=[ident], original_events=2)
        else:
            progress['ids']=[ident]
        return dict(id=ident, idempotency_key=PREFIX + ('batch/' if packed else '') + ident,
                    parameters=dict(kind=kind),progress=progress,
                    created_at=datetime(2026,11,10,tzinfo=timezone.utc))

    def pool(self, rows=None, target=None):
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        def execute(sql,params):
            cursor=MagicMock()
            if sql==MANIFEST_SCAN:cursor.fetchall.return_value=rows or []
            elif sql==MANIFEST_BY_ID:cursor.fetchone.return_value=target
            else:raise AssertionError('Unexpected or mutating database query')
            return cursor
        c.execute.side_effect=execute
        return pool,c

    def test_manifest_cursor_page_is_index_bounded(self):
        rows=[self.manifest(index='1'),self.manifest(packed=True,index='2')]
        pool,c=self.pool(rows=rows)
        result=list_manifests(pool,limit=1)
        self.assertEqual(len(result['items']),1)
        self.assertTrue(result['more'])
        self.assertEqual(result['next_cursor'],rows[0]['idempotency_key'])
        self.assertIsNone(result['request_cursor'])
        self.assertEqual(result['source'],'manifests')
        self.assertEqual(result['items'][0]['manifest_key'],rows[0]['idempotency_key'])
        self.assertTrue(result['no_r2_reads'])
        self.assertEqual(c.execute.call_args.args[0],MANIFEST_SCAN)
        self.assertIn('idempotency_key LIKE %s',MANIFEST_SCAN)
        self.assertEqual(c.execute.call_args.args[1][2],PREFIX+'%')
        self.assertEqual(c.execute.call_args.args[1][-1],2)
        result=list_manifests(self.pool(rows=rows[:1])[0],limit=2)
        self.assertFalse(result['more'])
        self.assertIsNone(result['next_cursor'])

    def test_bad_ids_pages_and_unsafe_manifest_kind_are_rejected(self):
        for limit in (0,26,True,'2',-1):
            with self.assertRaises(ValueError):validate_page(limit)
        for cursor in ('outside',PREFIX+'../../bad',PREFIX+'batch/nope',
                       PREFIX+'<script>','x'*300):
            with self.assertRaises(ValueError):validate_page(1,cursor)
        self.assertEqual(validate_page(1,PREFIX+'11111111-1111-1111-1111-111111111111')[0],1)
        pool,_=self.pool(target=self.manifest())
        with self.assertRaises(ValueError):find_manifest(pool,'no-uuid')
        wrong=self.manifest()
        wrong['progress']['format']='financial-history'
        with self.assertRaises(ValueError):find_manifest(self.pool(target=wrong)[0],wrong['id'])
        self.assertIsNone(find_manifest(self.pool(target=None)[0],self.manifest()['id']))

    def test_manifest_index_refuses_neighboring_or_mismatched_identity(self):
        raw=self.manifest()
        packed=self.manifest(packed=True,index='2')
        forged=[]
        row=dict(raw,idempotency_key='demo/shadow/archive-manifest-extra/'+raw['id'])
        forged.append(row)
        row=dict(raw,idempotency_key=PREFIX+'batch/'+raw['id'])
        forged.append(row)
        row=dict(packed,idempotency_key=PREFIX+packed['id'])
        forged.append(row)
        row=dict(raw,idempotency_key=PREFIX+'11111111-1111-1111-1111-000000000099')
        forged.append(row)
        row=dict(raw,id='not-canonical-uuid')
        forged.append(row)
        row=dict(raw,progress=dict(raw['progress'],format='wrong-format'))
        forged.append(row)
        for candidate in forged:
            with self.subTest(row=candidate['idempotency_key']):
                with self.assertRaises(ValueError):
                    list_manifests(self.pool(rows=[candidate])[0])
                with self.assertRaises(ValueError):
                    find_manifest(self.pool(target=candidate)[0],raw['id'])

    def test_manifest_lookup_is_exactly_namespace_bounded(self):
        row=self.manifest(packed=True,index='3')
        pool,c=self.pool(target=row)
        found=find_manifest(pool,row['id'])
        self.assertEqual(found['id'],row['id'])
        self.assertIn('idempotency_key LIKE %s',MANIFEST_BY_ID)
        self.assertEqual(c.execute.call_args.args[1][-1],PREFIX+'%')

    def test_read_raw_original_rows_with_checksum_verified_by_existing_verifier(self):
        row=self.manifest()
        pool,c=self.pool(target=row)
        original=dict(id=row['progress']['ids'][0],
                      idempotency_key='demo/shadow/event/'+row['progress']['ids'][0],
                      parameters=dict(ticker='BTC'),progress=dict(event='FAVORITE_STAT_DECISION'),
                      created_at='2026-11-09T00:00:00+00:00')
        store=MagicMock()
        with patch('services.demo.shadow_archive_reader.verify_archived_manifest',
                   return_value=[original]) as verify:
            result=read_manifest_events(pool,row['id'],store_factory=lambda env:store)
        self.assertTrue(result['verified'])
        self.assertEqual(result['items'][0]['progress']['event'],'FAVORITE_STAT_DECISION')
        self.assertEqual(result['total_events'],1)
        self.assertEqual(result['source'],'cloudflare-r2')
        self.assertEqual(c.execute.call_args.args[0],MANIFEST_BY_ID)
        verify.assert_called_once_with(store,row['progress'])
        store.client.close.assert_called_once()

    def test_packed_archive_reconstructs_every_original_event_id(self):
        row=self.manifest(packed=True)
        pool,_=self.pool(target=row)
        records=[dict(progress=dict(format='shadow-diagnostic-batch-v1'),
                      created_at='2026-11-09T00:00:00+00:00')]
        entries=[dict(id='first',key='demo/shadow/event/first',
                      parameters={},progress=dict(event='FAVORITE_STAT_DECISION')),
                 dict(id='second',key='demo/shadow/event/second',
                      parameters={},progress=dict(event='SCALPER_OBSERVATION_BATCH'))]
        with patch('services.demo.shadow_archive_reader.verify_batch_manifest',
                   return_value=records), patch(
                   'services.demo.shadow_archive_reader.decode_diagnostic_batch',
                   return_value=entries):
            result=read_manifest_events(pool,row['id'],offset=1,limit=1,
                store_factory=lambda env:MagicMock())
        self.assertEqual(result['total_events'],2)
        self.assertEqual(result['items'][0]['id'],'second')
        self.assertIsNone(result['next_offset'])

    def test_restore_failure_never_returns_success_and_closes_client(self):
        row=self.manifest()
        store=MagicMock()
        with patch('services.demo.shadow_archive_reader.verify_archived_manifest',
                   side_effect=RuntimeError('invalid checksum')):
            with self.assertRaises(RuntimeError):
                read_manifest_events(self.pool(target=row)[0],row['id'],
                    store_factory=lambda env:store)
        store.client.close.assert_called_once()
        for offset,limit in ((-1,2),(10001,2),(True,2),(0,0),(0,51),(0,True)):
            with self.assertRaises(ValueError):
                read_manifest_events(MagicMock(),'test',offset=offset,limit=limit)

    def test_reader_off_unless_separate_read_only_credentials_present(self):
        with self.assertRaises(ArchiveReaderUnavailable):
            read_store(dict(R2_ACCOUNT_ID='a'*32,R2_BUCKET='archive',
                            R2_ACCESS_KEY_ID='write-token',R2_SECRET_ACCESS_KEY='write-secret'))
        with self.assertRaises(ArchiveReaderUnavailable):
            read_store(dict(MT_ARCHIVE_READ_ENABLED='true',R2_ACCOUNT_ID='a'*32,
                R2_BUCKET='archive',R2_ACCESS_KEY_ID='write-token',
                R2_SECRET_ACCESS_KEY='write-secret'))
        env=dict(MT_ARCHIVE_READ_ENABLED='true',R2_ACCOUNT_ID='a'*32,R2_BUCKET='archive',
                 R2_READ_ACCESS_KEY_ID='read-id',R2_READ_SECRET_ACCESS_KEY='read-secret')
        with patch('services.demo.shadow_archive_reader.R2Objects.connect') as connect:
            read_store(env)
            self.assertEqual(connect.call_args.kwargs['access_key_id'],'read-id')
            self.assertEqual(connect.call_args.kwargs['secret_access_key'],'read-secret')
            self.assertNotIn('write-token',str(connect.call_args))


    def test_owner_routes_require_auth_and_are_query_bounded(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from services.api.shadow import install_shadow

        app=FastAPI()
        def unauthenticated(request):
            raise HTTPException(401, 'Sign in required')
        install_shadow(app,unauthenticated,MagicMock(),MagicMock())
        client=TestClient(app)
        self.assertEqual(client.get('/demo/shadow/archives').status_code,401)
        self.assertEqual(client.get(
            '/demo/shadow/archives/11111111-1111-1111-1111-111111111111').status_code,401)

        app=FastAPI()
        install_shadow(app,lambda _: True,MagicMock(),MagicMock())
        client=TestClient(app)
        with patch('services.demo.shadow_archive_reader.list_manifests',
                   return_value=dict(items=[],more=False,next_cursor=None)) as listing:
            self.assertEqual(client.get('/demo/shadow/archives').status_code,200)
            listing.assert_called_once()
        self.assertEqual(client.get('/demo/shadow/archives?limit=999').status_code,422)
        self.assertEqual(client.get('/demo/shadow/archives?cursor=../../bad').status_code,422)
        self.assertEqual(client.get('/demo/shadow/archives?limit=3&limit=4').status_code,422)
        self.assertEqual(client.get('/demo/shadow/archives?secret=1').status_code,422)
        with patch('services.demo.shadow_archive_reader.read_manifest_events',
                   side_effect=ArchiveReaderUnavailable('private-secret')):
            response=client.get('/demo/shadow/archives/11111111-1111-1111-1111-111111111111')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private-secret',response.text)


if __name__=='__main__':
    unittest.main()

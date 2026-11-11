"""P0 #196: full-row legacy archive, CAS and reversible restore checks.

The database tests require the disposable pocket_test CI database and never
use Render production credentials or any real R2 objects.
"""
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4
from urllib.parse import urlsplit

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from services.demo.legacy_event_archive import (
    FORMAT, CANDIDATES, LOCKED_ROWS, POINTER_UPDATE,
    verified_records, archive_events_v2, restore_requests_v2,
)
from services.demo.shadow_archive_recovery import PREFIX, archive_payload
from services.demo.store import DemoStore

URL=os.environ.get('POCKET_TEST_DATABASE_URL')
RECEIPT=dict(key='demo/events/'+'a'*64+'.json.gz',
             sha256='a'*64,size=200,at=42.0)


def sample_row(ident=None,progress=None):
    ident=ident or str(uuid4())
    timestamp=datetime(2026,10,1,tzinfo=timezone.utc)
    return dict(id=ident,idempotency_key=PREFIX+ident,
                asset='crypto',status='succeeded',
                parameters=dict(kind='EXPERIMENT',model='v1'),
                progress=progress or dict(event='FAVORITE_STAT_DECISION',
                                          details='original diagnostic'),
                created_at=timestamp,started_at=None,finished_at=timestamp,
                lease_expires_at=None,attempts=2,error_code=None,
                available_at=timestamp,max_attempts=5,lease_token=None)


class LegacyArchiveV2UnitTests(unittest.TestCase):
    def test_only_safe_shadow_diagnostics_are_candidates(self):
        self.assertIn("progress->>'event'=ANY",CANDIDATES)
        self.assertIn("status='succeeded'",CANDIDATES)
        self.assertIn("NOT (progress ? 'archive')",CANDIDATES)
        self.assertIn("ORDER BY idempotency_key LIMIT",CANDIDATES)
        self.assertIn("FOR UPDATE",LOCKED_ROWS)
        self.assertIn("progress=%s::jsonb",POINTER_UPDATE)
        self.assertNotIn("'demo/event/'",CANDIDATES)

    def test_v2_full_row_contract_and_legacy_v1_restore(self):
        original=archive_payload([sample_row()])[0]
        payload=dict(format=FORMAT,count=1,ids=[original['id']],
                     source_prefix=PREFIX,records=[original])
        from io import BytesIO
        from types import SimpleNamespace
        from services.demo.maintenance import put_verified, read_verified
        class MemoryClient:
            def __init__(self):
                self.rows={}
            def put_object(self,**kwargs):
                self.rows[kwargs['Key']]=kwargs['Body']
            def get_object(self,**kwargs):
                data=self.rows[kwargs['Key']]
                return dict(Body=BytesIO(data),ContentLength=len(data))
        objects=SimpleNamespace(client=MemoryClient(),bucket='archive-test')
        receipt=put_verified(objects,'events',payload)
        self.assertEqual(read_verified(objects,receipt),payload)
        self.assertEqual(receipt['size'],
                         len(objects.client.rows[receipt['key']]))

        records,full=verified_records(payload)
        self.assertTrue(full)
        self.assertEqual(records[0],original)
        self.assertEqual(len(records[0]),15)
        previous=[dict(id=original['id'],parameters=original['parameters'],
                       progress=original['progress'])]
        self.assertEqual(verified_records(previous),(previous,False))
        for broken in (
            dict(payload,source_prefix='demo/event/'),
            dict(payload,ids=['another-id']),
            dict(payload,count=2),
            dict(payload,records=[dict(original,progress=dict(event='SETTLED'))]),
            dict(payload,records=[dict(original,idempotency_key='demo/order/x')]),
            dict(payload,records=[dict(original,parameters='bad')]),
            dict(payload,records=[dict(original,status='running')]),
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    verified_records(broken)
        with self.assertRaises(ValueError):
            verified_records([previous[0],previous[0]])

    def test_network_upload_occurs_outside_sql_and_all_columns_are_compared(self):
        from contextlib import contextmanager
        row=sample_row();pool=MagicMock()
        connection=pool.connection.return_value.__enter__.return_value
        store=MagicMock(pool=pool)
        store.get.return_value=None
        depth=[0];events=[]
        @contextmanager
        def transaction():
            depth[0]+=1;events.append('begin')
            try:
                yield
            finally:
                depth[0]-=1;events.append('end')
        connection.transaction.side_effect=transaction
        def execute(sql,params=None):
            cursor=MagicMock()
            if sql==CANDIDATES:cursor.fetchall.return_value=[row]
            elif sql==LOCKED_ROWS:cursor.fetchall.return_value=[row]
            elif sql==POINTER_UPDATE:cursor.fetchone.return_value=dict(id=row['id'])
            return cursor
        connection.execute.side_effect=execute
        def put(*args):
            self.assertEqual(depth[0],0)
            events.append('R2-readback-complete')
            payload=args[2]
            self.assertEqual(payload['format'],FORMAT)
            self.assertEqual(payload['records'][0]['progress'],row['progress'])
            self.assertEqual(payload['records'][0]['attempts'],2)
            self.assertEqual(payload['records'][0]['created_at'],
                             row['created_at'].isoformat())
            return RECEIPT
        with patch('services.demo.maintenance.put_verified',side_effect=put):
            archive_events_v2(store,object(),
                dict(archive_days=30),False)
        self.assertEqual(events,['begin','end','R2-readback-complete',
                                 'begin','end'])
        self.assertEqual(connection.transaction.call_count,2)
        self.assertEqual(pool.connection.call_count,2)
        self.assertEqual(sum(c.args[0]==POINTER_UPDATE
                             for c in connection.execute.call_args_list),1)
        self.assertTrue(any(x.args[0]=='archive-health'
                            for x in store.put.call_args_list))

    def test_changed_record_and_r2_failure_leave_source_unmodified(self):
        row=sample_row();changed=sample_row(
            ident=row['id'],progress=dict(row['progress'],newer=True))
        for failure in ('changed','upload'):
            with self.subTest(failure=failure):
                pool=MagicMock()
                c=pool.connection.return_value.__enter__.return_value
                store=MagicMock(pool=pool)
                store.get.return_value=None
                def execute(sql,params=None):
                    cursor=MagicMock()
                    if sql==CANDIDATES:cursor.fetchall.return_value=[row]
                    elif sql==LOCKED_ROWS:cursor.fetchall.return_value=[
                        changed if failure=='changed' else row]
                    return cursor
                c.execute.side_effect=execute
                with patch('services.demo.maintenance.put_verified',
                           side_effect=ValueError('R2 unavailable')
                           if failure=='upload' else lambda *_: RECEIPT):
                    with self.assertRaises((RuntimeError,ValueError)):
                        archive_events_v2(store,object(),
                                          dict(archive_days=30),False)
                self.assertFalse(any(call.args[0]==POINTER_UPDATE
                                     for call in c.execute.call_args_list))
                store.put.assert_not_called()


    def test_demo_auto_archive_default_off_even_with_policy_enabled(self):
        from services.demo.maintenance import maintenance
        from threading import Event
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        def sql(stmt,params=None):
            cursor=MagicMock()
            if 'pg_database_size(' in stmt:
                cursor.fetchone.return_value=dict(size=1024)
            elif 'pg_stat_user_tables' in stmt:
                cursor.fetchall.return_value=[]
            elif 'pg_stat_database' in stmt:
                cursor.fetchone.return_value=dict(numbackends=1)
            return cursor
        c.execute.side_effect=sql
        store=MagicMock(pool=pool)
        store.get.return_value=None
        objects=MagicMock()
        with patch('services.demo.maintenance.object_store',return_value=objects), \
             patch('services.demo.maintenance.archive_events') as archive, \
             patch('services.demo.maintenance.restore_requests'), \
             patch('services.demo.maintenance.backup'), \
             patch('services.demo.maintenance.emails'):
            maintenance(store,dict(DATABASE_CAPACITY_GB='15'),Event())
            archive.assert_not_called()
            maintenance(store,dict(DATABASE_CAPACITY_GB='15',
                                   MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED='true'),
                        Event())
            archive.assert_called_once()

@unittest.skipUnless(URL,'Disposable PostgreSQL database required')
class LegacyArchiveV2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':
            raise RuntimeError('Only the disposable pocket_test may be mutated')
        from services.api.manage import migrate
        migrate(URL)
        cls.pool=ConnectionPool(URL,min_size=1,max_size=3,open=True,
                                kwargs=dict(row_factory=dict_row))
        cls.store=DemoStore(cls.pool)

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()

    def setUp(self):
        self.ids=[]
        with self.pool.connection() as c:
            c.execute("""DELETE FROM research_job WHERE idempotency_key IN
                ('demo/archive-scan-v2','demo/archive-health')""")

    def tearDown(self):
        with self.pool.connection() as c:
            c.execute('DELETE FROM research_job WHERE id=ANY(%s::uuid[])',
                      (self.ids,))
            c.execute("""DELETE FROM research_job WHERE idempotency_key IN
                ('demo/archive-scan-v2','demo/archive-health')""")

    def insert(self,event='FAVORITE_STAT_DECISION',prefix=PREFIX):
        ident=str(uuid4());self.ids.append(ident)
        with self.pool.connection() as c:
            return c.execute("""INSERT INTO research_job
                (id,idempotency_key,asset,status,parameters,progress,
                 created_at,finished_at,available_at,attempts,max_attempts)
                VALUES(%s,%s,'crypto','succeeded',%s,%s,
                    clock_timestamp()-interval '45 days',
                    clock_timestamp()-interval '45 days',
                    clock_timestamp()-interval '45 days',2,5)
                RETURNING id::text,idempotency_key,asset,status,parameters,
                    progress,created_at,started_at,finished_at,
                    lease_expires_at,attempts,error_code,available_at,
                    max_attempts,lease_token""",
                (ident,prefix+ident,Jsonb(dict(kind='EXPERIMENT')),
                 Jsonb(dict(event=event,details='must survive')))).fetchone()

    def progress(self,ident):
        with self.pool.connection() as c:
            return c.execute('SELECT progress FROM research_job WHERE id=%s',
                             (ident,)).fetchone()['progress']

    def test_v1_progress_only_archive_still_restores_without_metadata_loss(self):
        row=self.insert()
        with self.pool.connection() as c:
            c.execute('UPDATE research_job SET progress=%s WHERE id=%s',
                      (Jsonb(dict(archive=RECEIPT,archived=True)),row['id']))
        request_key=str(uuid4())
        self.ids.append(self.store.put('restore/'+request_key,
                                       dict(event_id=row['id'])))
        legacy=[dict(id=row['id'],parameters=row['parameters'],
                     progress=row['progress'])]
        with patch('services.demo.maintenance.read_verified',
                   return_value=legacy):
            restore_requests_v2(self.store,object())
        self.assertEqual(self.progress(row['id'])['details'],'must survive')
        self.assertTrue(self.store.get('restore/'+request_key)['progress']['done'])

    def test_recovery_restore_rejects_changed_database_metadata(self):
        row=self.insert()
        snapshots=[]
        with patch('services.demo.maintenance.put_verified',
                   side_effect=lambda _o,_k,p:(snapshots.append(p),RECEIPT)[1]):
            archive_events_v2(self.store,object(),dict(archive_days=30),False)
        request_key=str(uuid4())
        self.ids.append(self.store.put('restore/'+request_key,
                                       dict(event_id=row['id'])))
        with self.pool.connection() as c:
            c.execute('UPDATE research_job SET parameters=%s WHERE id=%s',
                      (Jsonb(dict(kind='EXP',edited_after_archive=True)),
                       row['id']))
        with patch('services.demo.maintenance.read_verified',
                   return_value=snapshots[0]):
            with self.assertRaisesRegex(RuntimeError,'metadata changed'):
                restore_requests_v2(self.store,object())
        self.assertIn('archive',self.progress(row['id']))
        self.assertFalse(self.store.get('restore/'+request_key)['progress'].get('done'))

    def test_exact_full_row_archive_and_restore_legacy_compatibility(self):
        row=self.insert()
        money=self.insert('SETTLED')
        ordinary=self.insert('FAVORITE_STAT_DECISION','demo/event/')
        captured=[]
        def put(objects,kind,payload):
            self.assertEqual(kind,'events')
            captured.append(payload)
            return RECEIPT
        with patch('services.demo.maintenance.put_verified',side_effect=put):
            archive_events_v2(self.store,object(),dict(archive_days=30),False)
        self.assertEqual(len(captured),1)
        snapshot=captured[0]
        self.assertEqual(snapshot['format'],FORMAT)
        self.assertEqual(snapshot['count'],1)
        self.assertEqual(snapshot['records'][0],archive_payload([row])[0])
        self.assertEqual(self.progress(money['id'])['event'],'SETTLED')
        self.assertEqual(self.progress(ordinary['id'])['details'],
                         'must survive')
        pointer=self.progress(row['id'])
        self.assertEqual(pointer['archive_format'],FORMAT)
        self.assertEqual(pointer['archive']['sha256'],RECEIPT['sha256'])
        req=str(uuid4())
        request_row_id=self.store.put('restore/'+req,dict(event_id=row['id']))
        self.ids.append(request_row_id)
        with patch('services.demo.maintenance.read_verified',
                   return_value=snapshot):
            restore_requests_v2(self.store,object())
        restored=self.progress(row['id'])
        self.assertEqual(restored['event'],'FAVORITE_STAT_DECISION')
        self.assertEqual(restored['details'],'must survive')
        self.assertIn('restored_at',restored)
        self.assertTrue(self.store.get('restore/'+req)['progress']['done'])

    def test_concurrent_update_during_r2_upload_aborts_without_pointer(self):
        row=self.insert()
        def concurrent_write(*_):
            # A separate connection modifies the source AFTER the SELECT
            # transaction has ended and BEFORE the FOR UPDATE/compare phase.
            with self.pool.connection() as c:
                c.execute('UPDATE research_job SET parameters=%s WHERE id=%s',
                    (Jsonb(dict(row['parameters'],newer_research='retained')),
                     row['id']))
            return RECEIPT
        with patch('services.demo.maintenance.put_verified',
                   side_effect=concurrent_write):
            with self.assertRaisesRegex(RuntimeError,'source changed'):
                archive_events_v2(self.store,object(),
                                  dict(archive_days=30),False)
        with self.pool.connection() as c:
            retained=c.execute('SELECT parameters FROM research_job WHERE id=%s',
                               (row['id'],)).fetchone()['parameters']
        self.assertEqual(retained['newer_research'],'retained')
        self.assertNotIn('archive',self.progress(row['id']))
        self.assertIsNone(self.store.get('archive-scan-v2'))


if __name__=='__main__':
    unittest.main()

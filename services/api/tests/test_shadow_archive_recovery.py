"""Recovery tooling must never delete a paper event before a verified R2 receipt."""
import unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch

from services.demo.shadow_archive_recovery import (
    PREFIX,MANIFEST_PREFIX,CANDIDATES,LOCKED_CANDIDATES,MANIFEST_SQL,DELETE_SQL,SCOPED_RECLAIM_SQL,
    SAFE_EVENT_KINDS,validate_window,archive_payload,plan_only,
    archive_and_reclaim_one,verify_archived_manifest,main
)

class ShadowArchiveRecoveryTests(unittest.TestCase):
    def row(self,ident='11111111-1111-1111-1111-111111111111'):
        return dict(id=ident,idempotency_key=PREFIX+ident,asset='crypto',
            status='succeeded',parameters=dict(kind='EXPERIMENT'),
            progress=dict(event='FAVORITE_STAT_DECISION',details='original decision evidence'),
            created_at=datetime(2026,11,7,tzinfo=timezone.utc),
            started_at=None,finished_at=datetime(2026,11,7,tzinfo=timezone.utc),
            lease_expires_at=None,attempts=0,error_code=None,
            available_at=datetime(2026,11,7,tzinfo=timezone.utc),
            max_attempts=5,lease_token=None)

    def db(self,rows=None,deleted=None):
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        rows=[] if rows is None else rows
        deleted=([dict(id=r['id']) for r in rows] if deleted is None else deleted)
        def sql(statement,params=None):
            cur=MagicMock()
            if statement in (CANDIDATES,LOCKED_CANDIDATES):cur.fetchall.return_value=rows
            if statement in (DELETE_SQL,SCOPED_RECLAIM_SQL):cur.fetchall.return_value=deleted
            return cur
        c.execute.side_effect=sql
        return pool,c

    def test_age_batch_and_namespace_bounds_are_fail_closed(self):
        for age in (0,1,5,-1,True,7.5):
            with self.assertRaises(ValueError):validate_window(10000,age,100)
        for batch in (0,151,-1,True,2.3):
            with self.assertRaises(ValueError):validate_window(10000,24,batch)
        self.assertEqual(validate_window(10000,6,1),10000-6*3600)
        self.assertIn("idempotency_key>=%s",CANDIDATES)
        self.assertIn("idempotency_key LIKE %s",CANDIDATES)
        self.assertIn("idempotency_key LIKE %s",DELETE_SQL)
        self.assertIn("created_at<to_timestamp(%s)",DELETE_SQL)
        self.assertIn("ORDER BY created_at, id LIMIT %s",CANDIDATES)
        self.assertNotIn("FOR UPDATE",CANDIDATES)
        self.assertIn("FOR UPDATE SKIP LOCKED",LOCKED_CANDIDATES)
        self.assertIn("progress->>'event'=ANY",DELETE_SQL)
        self.assertNotIn('FILL',SAFE_EVENT_KINDS)
        self.assertNotIn('SETTLED',SAFE_EVENT_KINDS)
        self.assertNotIn('CYCLE_REPORT',SAFE_EVENT_KINDS)
        self.assertTrue(MANIFEST_PREFIX.startswith('demo/shadow/'))
        self.assertNotEqual(PREFIX,'demo/event/')

    def test_preview_reports_only_bounded_categories_without_modifying_db(self):
        row=self.row();pool,c=self.db([row])
        result=plan_only(pool,now=1794500000,age_hours=24)
        self.assertEqual(result['mode'],'preview')
        self.assertEqual(result['event_types'],{'FAVORITE_STAT_DECISION':1})
        self.assertEqual(result['eligible_in_sample'],1)
        self.assertEqual([call.args[0] for call in c.execute.call_args_list],
                         ['SET LOCAL statement_timeout=5000',CANDIDATES])
        self.assertNotIn('original decision evidence',str(result))

    def test_verified_archive_manifest_precedes_exact_deletion_in_one_transaction(self):
        a=self.row();b=self.row('22222222-2222-2222-2222-222222222222')
        pool,c=self.db([a,b])
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',sha256='a'*64,size=410,at=42)
        obj=MagicMock()
        with patch('services.demo.shadow_archive_recovery.put_verified',return_value=receipt) as put:
            result=archive_and_reclaim_one(pool,obj,now=1794500000,age_hours=24)
        self.assertEqual((result['archived'],result['deleted'],result['compressed_bytes']),(2,2,410))
        put.assert_called_once()
        self.assertEqual(put.call_args.args[1],'events')
        self.assertEqual([r['id'] for r in put.call_args.args[2]],[a['id'],b['id']])
        self.assertEqual(put.call_args.args[2][0]['progress'],a['progress'])
        self.assertEqual(put.call_args.args[2][0]['finished_at'],a['finished_at'].isoformat())
        self.assertEqual(put.call_args.args[2][0]['attempts'],a['attempts'])
        self.assertEqual(put.call_args.args[2][0]['asset'],a['asset'])
        statements=[call.args[0] for call in c.execute.call_args_list]
        self.assertEqual(statements,['SET LOCAL statement_timeout=10000',LOCKED_CANDIDATES,MANIFEST_SQL,DELETE_SQL])
        manifest_args=c.execute.call_args_list[2].args[1]
        self.assertEqual(manifest_args[3],MANIFEST_PREFIX+str(manifest_args[0]))
        self.assertEqual(manifest_args[2].obj['count'],2)
        self.assertEqual(manifest_args[2].obj['ids'],[a['id'],b['id']])
        self.assertEqual(manifest_args[2].obj['reference'],receipt)
        self.assertEqual(c.execute.call_args_list[3].args[1][0],[a['id'],b['id']])
        c.transaction.assert_called_once()

    def test_collector_unrelated_namespace_never_reaches_r2_or_delete(self):
        row=self.row()
        row['idempotency_key']='demo/shadow/event-batch/'+row['id']
        pool,c=self.db([row])
        with patch('services.demo.shadow_archive_recovery.put_verified') as write:
            with self.assertRaisesRegex(RuntimeError,'Unrelated row'):
                archive_and_reclaim_one(pool,MagicMock(),now=1794500000)
        write.assert_not_called()
        statements=[call.args[0] for call in c.execute.call_args_list]
        self.assertNotIn(MANIFEST_SQL,statements)
        self.assertNotIn(DELETE_SQL,statements)

    def test_scoped_archival_uses_function_not_table_delete_or_row_update_lock(self):
        row=self.row();pool,c=self.db([row])
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=800,at=42)
        with patch('services.demo.shadow_archive_recovery.put_verified',
                   return_value=receipt):
            result=archive_and_reclaim_one(pool,MagicMock(),
                now=1794500000,age_hours=24,batch_size=1,scoped=True)
        self.assertEqual(result['deleted'],1)
        operations=[call.args[0] for call in c.execute.call_args_list]
        self.assertEqual(operations,['SET LOCAL statement_timeout=5000',
            CANDIDATES,'SET LOCAL statement_timeout=10000',SCOPED_RECLAIM_SQL])
        self.assertEqual(c.transaction.call_count,2)
        self.assertEqual(pool.connection.call_count,2)
        self.assertNotIn(DELETE_SQL,operations)
        self.assertNotIn(LOCKED_CANDIDATES,operations)
        scoped_args=c.execute.call_args_list[-1].args[1]
        self.assertEqual(scoped_args[1],'shadow_event_r2_manifest')
        self.assertEqual(scoped_args[2].obj['count'],1)
        self.assertEqual(scoped_args[3].obj[0]['id'],row['id'])
        self.assertEqual(scoped_args[3].obj[0]['available_at'],
                         row['available_at'].isoformat())
        self.assertEqual(scoped_args[3].obj[0]['max_attempts'],5)

    def test_scoped_r2_io_occurs_after_snapshot_tx_and_before_reclaim_tx(self):
        from contextlib import contextmanager
        row=self.row()
        pool,c=self.db([row])
        events=[];depth=[0]
        @contextmanager
        def tracked():
            depth[0]+=1
            events.append('begin')
            try:yield
            finally:
                events.append('end')
                depth[0]-=1
        c.transaction.side_effect=tracked
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=800,at=42)
        def verify(*args,**kwargs):
            self.assertEqual(depth[0],0,'R2 I/O must never hold scoped SQL transaction')
            events.append('verified-R2')
            return receipt
        with patch('services.demo.shadow_archive_recovery.put_verified',
                   side_effect=verify):
            report=archive_and_reclaim_one(pool,MagicMock(),
                now=1794500000,age_hours=24,batch_size=1,scoped=True)
        self.assertTrue(report['verified'])
        self.assertEqual(events,['begin','end','verified-R2','begin','end'])

    def test_scoped_changed_source_aborts_short_reclaim(self):
        row=self.row()
        pool,c=self.db([row],deleted=[])
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=800,at=42)
        with patch('services.demo.shadow_archive_recovery.put_verified',
                   return_value=receipt):
            with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
                archive_and_reclaim_one(pool,MagicMock(),now=1794500000,
                    age_hours=24,batch_size=1,scoped=True)
        self.assertEqual(c.transaction.call_count,2)
        self.assertNotIn(DELETE_SQL,[call.args[0] for call in c.execute.call_args_list])

    def test_archive_failure_never_reaches_manifest_or_delete(self):
        pool,c=self.db([self.row()])
        with patch('services.demo.shadow_archive_recovery.put_verified',side_effect=TimeoutError('storage failed')):
            with self.assertRaises(TimeoutError):
                archive_and_reclaim_one(pool,MagicMock(),now=1794500000)
        statements=[call.args[0] for call in c.execute.call_args_list]
        self.assertEqual(statements,['SET LOCAL statement_timeout=10000',LOCKED_CANDIDATES])

    def test_delete_mismatch_aborts_instead_of_reporting_success(self):
        pool,c=self.db([self.row()],deleted=[])
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',sha256='a'*64,size=1,at=42)
        with patch('services.demo.shadow_archive_recovery.put_verified',return_value=receipt):
            with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
                archive_and_reclaim_one(pool,MagicMock(),now=1794500000)
        self.assertEqual(c.execute.call_args_list[-1].args[0],DELETE_SQL)


    def test_never_delete_settlements_or_financial_records(self):
        financial=self.row()
        financial['progress']=dict(event='SETTLED',cash='1200',details=dict(payout=1))
        pool,c=self.db([financial])
        with self.assertRaisesRegex(RuntimeError,'Non-diagnostic'):
            archive_and_reclaim_one(pool,MagicMock(),now=1794500000)
        self.assertNotIn(DELETE_SQL,[call.args[0] for call in c.execute.call_args_list])
        self.assertNotIn(MANIFEST_SQL,[call.args[0] for call in c.execute.call_args_list])

    def test_verify_manifest_roundtrip_and_reject_tampered_or_unrelated_entries(self):
        from services.demo.shadow_archive_recovery import archive_payload
        original=archive_payload([self.row()])
        manifest=dict(format='shadow-r2-event-batch-v1',source_prefix=PREFIX,
                      count=1,ids=[original[0]['id']],
                      reference=dict(key='demo/events/abc.json.gz'))
        with patch('services.demo.shadow_archive_recovery.read_verified',return_value=original) as reader:
            self.assertEqual(verify_archived_manifest(MagicMock(),manifest),original)
            reader.assert_called_once()
        with patch('services.demo.shadow_archive_recovery.read_verified',return_value=original*2):
            with self.assertRaisesRegex(ValueError,'count mismatch'):
                verify_archived_manifest(MagicMock(),manifest)
        invalid=[dict(original[0],progress=dict(event='FILL'))]
        with patch('services.demo.shadow_archive_recovery.read_verified',return_value=invalid):
            with self.assertRaisesRegex(ValueError,'financial'):
                verify_archived_manifest(MagicMock(),manifest)
        invalid=[dict(original[0],idempotency_key='demo/order/unrelated')]
        with patch('services.demo.shadow_archive_recovery.read_verified',return_value=invalid):
            with self.assertRaisesRegex(ValueError,'unrelated'):
                verify_archived_manifest(MagicMock(),manifest)
        altered=dict(manifest,ids=['a different archive record'])
        with patch('services.demo.shadow_archive_recovery.read_verified',return_value=original):
            with self.assertRaisesRegex(ValueError,'IDs mismatch'):
                verify_archived_manifest(MagicMock(),altered)


    def test_command_line_requires_explicit_operator_confirmation(self):
        with self.assertRaises(SystemExit) as caught:
            main(['--execute','--max-batches','1'])
        self.assertEqual(caught.exception.code,2)
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(SystemExit) as caught:
                main([])
        self.assertEqual(caught.exception.code,2)


from services.api.tests import test_demo_postgres as fixture

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class RealDisposableReclaimNamespaceTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_aged_packed_neighbor_does_not_enter_raw_reclaim_preview(self):
        import time
        from uuid import uuid4
        raw=self.demo.put('shadow/event/'+str(uuid4()),
            dict(event='FAVORITE_STAT_DECISION',time=123))
        neighbor=self.demo.put('shadow/event-batch/'+str(uuid4()),
            dict(event='FAVORITE_STAT_DECISION',time=124))
        with self.store.pool.connection() as c:
            c.execute("""UPDATE research_job SET
                created_at=clock_timestamp()-interval '72 hours'
                WHERE id=ANY(%s::uuid[])""",([raw,neighbor],))
        result=plan_only(self.store.pool,now=time.time(),
                         age_hours=24,batch_size=10)
        self.assertEqual(result['eligible_in_sample'],1)
        self.assertEqual(result['mode'],'preview')
        with self.store.pool.connection() as c:
            intact=c.execute("""SELECT id::text FROM research_job
                WHERE id=ANY(%s::uuid[])""",([raw,neighbor],)).fetchall()
        self.assertEqual({r['id'] for r in intact},{raw,neighbor})

if __name__=='__main__':unittest.main()

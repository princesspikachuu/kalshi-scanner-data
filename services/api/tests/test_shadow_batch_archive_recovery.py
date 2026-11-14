"""Operator batch archival keeps every diagnostic event and financial state safe."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.paper_demo.shadow.storage import entry
from services.paper_demo.shadow.diagnostic_batches import compact_diagnostic_rows
from services.demo.shadow_batch_archive_recovery import (
    BATCH_PREFIX, CANDIDATES, LOCKED_CANDIDATES, MANIFEST_SQL, DELETE_SQL, SCOPED_RECLAIM_SQL,
    FORMAT, archive_one, cutoff_at, original_row, preview,
    validated_records, verify_batch_manifest, main,
)


class ShadowBatchArchiveRecoveryTests(unittest.TestCase):
    def row(self,index=1):
        originals=[
            entry('demo/shadow/event/'+str(index)+'-one',
                  dict(kind='EXPERIMENT',time=100.0),
                  dict(time=100.0,event='FAVORITE_STAT_DECISION',details=dict(price='0.91'))),
            entry('demo/shadow/event/'+str(index)+'-two',
                  dict(kind='EXPERIMENT',time=101.0),
                  dict(time=101.0,event='FAVORITE_STAT_DECISION',details=dict(price='0.92')))
        ]
        packed=compact_diagnostic_rows(originals,entry)[0]
        return dict(id='11111111-1111-1111-1111-%012d'%index,
            idempotency_key=packed[3],asset='crypto',status='succeeded',
            parameters=packed[1].obj,progress=packed[2].obj,
            created_at=datetime(2026,11,7,tzinfo=timezone.utc),
            started_at=None,finished_at=datetime(2026,11,7,tzinfo=timezone.utc),
            lease_expires_at=None,attempts=0,error_code=None,
            available_at=datetime(2026,11,7,tzinfo=timezone.utc),
            max_attempts=5,lease_token=None)

    def pool(self,rows=None,deleted=None):
        rows=rows or []
        deleted=([dict(id=r['id']) for r in rows] if deleted is None else deleted)
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        def execute(query,params=None):
            cur=MagicMock()
            if query in (CANDIDATES,LOCKED_CANDIDATES):
                cur.fetchall.return_value=rows
            elif query in (DELETE_SQL,SCOPED_RECLAIM_SQL):
                cur.fetchall.return_value=deleted
            return cur
        c.execute.side_effect=execute
        return pool,c

    def test_preview_is_read_only_and_uses_prefix_index(self):
        r=self.row();pool,c=self.pool([r])
        result=preview(pool,now=1794500000)
        self.assertEqual(result['batch_rows'],1)
        self.assertEqual(result['original_events'],2)
        self.assertTrue(result['no_writes'])
        queries=[x.args[0] for x in c.execute.call_args_list]
        self.assertEqual(queries,['SET LOCAL statement_timeout=5000',CANDIDATES])
        self.assertNotIn('FOR UPDATE',CANDIDATES)
        self.assertIn('ORDER BY idempotency_key LIMIT %s',CANDIDATES)
        self.assertIn('idempotency_key LIKE %s',CANDIDATES)
        self.assertIn('idempotency_key LIKE %s',DELETE_SQL)
        self.assertIn('FOR UPDATE SKIP LOCKED',LOCKED_CANDIDATES)

    def test_verified_r2_manifest_and_exact_delete_in_same_transaction(self):
        rows=[self.row(1),self.row(2)]
        pool,c=self.pool(rows)
        original=[original_row(row) for row in rows]
        receipt=dict(key='demo/events/verified.json.gz',sha256='a'*64,size=300)
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt) as put,patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   return_value=original) as read:
            result=archive_one(pool,MagicMock(),now=1794500000,batch_size=2)
        self.assertEqual(result['archived_rows'],2)
        self.assertEqual(result['original_events'],4)
        self.assertEqual(result['deleted_rows'],2)
        put.assert_called_once()
        self.assertEqual(put.call_args.args[1],'events')
        self.assertEqual(put.call_args.args[2],original)
        read.assert_called_once()
        queries=[x.args[0] for x in c.execute.call_args_list]
        self.assertEqual(queries,['SET LOCAL statement_timeout=10000',
                                  LOCKED_CANDIDATES,MANIFEST_SQL,DELETE_SQL])
        manifest=c.execute.call_args_list[2].args[1][2].obj
        archive_args=c.execute.call_args_list[2].args[1]
        self.assertEqual(archive_args[3],
                         'demo/shadow/archive-manifest/batch/'+str(archive_args[0]))
        self.assertEqual(manifest['format'],FORMAT)
        self.assertEqual(manifest['row_ids'],[row['id'] for row in rows])
        self.assertEqual(manifest['original_events'],4)
        self.assertEqual(len(manifest['event_ids']),4)
        self.assertEqual(c.execute.call_args_list[3].args[1][0],manifest['row_ids'])
        c.transaction.assert_called_once()

    def test_scoped_packed_archive_cannot_execute_table_delete(self):
        row=self.row();pool,c=self.pool([row])
        record=original_row(row)
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=300)
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   return_value=[record]):
            result=archive_one(pool,MagicMock(),now=1794500000,
                batch_size=1,scoped=True)
        self.assertEqual(result['deleted_rows'],1)
        operations=[call.args[0] for call in c.execute.call_args_list]
        self.assertEqual(operations,['SET LOCAL statement_timeout=5000',
            CANDIDATES,'SET LOCAL statement_timeout=10000',SCOPED_RECLAIM_SQL])
        self.assertEqual(c.transaction.call_count,2)
        self.assertEqual(pool.connection.call_count,2)
        self.assertNotIn(DELETE_SQL,operations)
        scoped=c.execute.call_args_list[-1].args[1]
        self.assertEqual(scoped[1],'diagnostic_batch_r2_manifest')
        self.assertEqual(scoped[3].obj,[record])
        self.assertEqual(record['available_at'],row['available_at'].isoformat())
        self.assertEqual(record['max_attempts'],5)

    def test_scoped_packed_r2_verification_never_holds_db_transaction(self):
        from contextlib import contextmanager
        row=self.row()
        pool,c=self.pool([row])
        original=original_row(row)
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
                     sha256='a'*64,size=300)
        def put(*args,**kwargs):
            self.assertEqual(depth[0],0)
            events.append('R2-put-verified')
            return receipt
        def read(*args,**kwargs):
            self.assertEqual(depth[0],0)
            events.append('R2-read-verified')
            return [original]
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   side_effect=put),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   side_effect=read):
            report=archive_one(pool,MagicMock(),now=1794500000,
                               batch_size=1,scoped=True)
        self.assertEqual(report['deleted_rows'],1)
        self.assertEqual(events,['begin','end','R2-put-verified',
                                 'R2-read-verified','begin','end'])

    def test_scoped_packed_reclaim_rejects_modified_row(self):
        row=self.row()
        pool,c=self.pool([row],deleted=[])
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=300)
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   return_value=[original_row(row)]):
            with self.assertRaisesRegex(RuntimeError,'Incomplete batch reclaim'):
                archive_one(pool,MagicMock(),now=1794500000,
                            batch_size=1,scoped=True)
        self.assertNotIn(DELETE_SQL,[call.args[0] for call in c.execute.call_args_list])
        self.assertEqual(c.transaction.call_count,2)

    def test_archiving_must_validate_real_r2_readback(self):
        r=self.row();pool,c=self.pool([r])
        receipt=dict(key='demo/events/verified.json.gz',sha256='a'*64,size=300)
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   side_effect=TimeoutError('R2 unavailable')):
            with self.assertRaises(TimeoutError):
                archive_one(pool,MagicMock(),now=1794500000)
        self.assertNotIn(MANIFEST_SQL,[x.args[0] for x in c.execute.call_args_list])
        self.assertNotIn(DELETE_SQL,[x.args[0] for x in c.execute.call_args_list])

    def test_incorrect_r2_restoration_cannot_delete(self):
        r=self.row();pool,c=self.pool([r])
        receipt=dict(key='demo/events/verified.json.gz',sha256='a'*64,size=300)
        altered=dict(original_row(r),id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   return_value=[altered]):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                archive_one(pool,MagicMock(),now=1794500000)
        self.assertNotIn(DELETE_SQL,[x.args[0] for x in c.execute.call_args_list])

    def test_empty_candidates_and_delete_count_mismatch(self):
        empty_pool,_=self.pool([])
        self.assertEqual(archive_one(empty_pool,MagicMock(),now=1794500000)['deleted_rows'],0)
        r=self.row();pool,c=self.pool([r],deleted=[])
        receipt=dict(key='demo/events/verified.json.gz',sha256='a'*64,size=300)
        with patch('services.demo.shadow_batch_archive_recovery.put_verified',
                   return_value=receipt),patch(
                   'services.demo.shadow_batch_archive_recovery.read_verified',
                   return_value=[original_row(r)]):
            with self.assertRaisesRegex(RuntimeError,'Incomplete batch reclaim'):
                archive_one(pool,MagicMock(),now=1794500000)
        self.assertEqual(c.execute.call_args_list[-1].args[0],DELETE_SQL)

    def test_fail_closed_for_unsafe_rows_and_age(self):
        for age in (True,0,5,-1,2.5):
            with self.assertRaises(ValueError):
                cutoff_at(999999,age,1)
        for amount in (0,9,True,-1):
            with self.assertRaises(ValueError):
                cutoff_at(999999,24,amount)
        bad=dict(self.row(),asset='weather')
        with self.assertRaisesRegex(ValueError,'Invalid shadow'):
            validated_records([bad])
        bad=dict(self.row(),idempotency_key='demo/order/other')
        with self.assertRaisesRegex(ValueError,'Unrelated shadow'):
            validated_records([bad])

    def test_command_line_requires_operator_explicit_write_flag(self):
        with self.assertRaises(SystemExit) as exc:
            main(['--execute'])
        self.assertEqual(exc.exception.code,2)
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(SystemExit) as exc:
                main([])
            self.assertEqual(exc.exception.code,2)


if __name__=='__main__':
    unittest.main()

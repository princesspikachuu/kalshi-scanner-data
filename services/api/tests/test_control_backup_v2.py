"""Control backups never advance durable health until all R2 parts roundtrip."""
import json
import unittest
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from services.demo.control_backup_v2 import (
    FORMAT,PART_FORMAT,MAX_CHUNK_ROWS,MAX_ROWS,MAX_CHUNK_BYTES,
    canonical,select_prefix_query,collect_snapshot,collect_snapshot_spooled,
    split_snapshot,digest_records,restore_verified_snapshot,verify_staged_archive,backup_controls,
    is_authorized,backup_once
)

class VerifiedControlBackupTests(unittest.TestCase):
    def record(self,index=1,progress=None):
        return dict(id='11111111-1111-1111-1111-%012d'%index,
                    idempotency_key='live/write/'+str(index),
                    parameters={'kind':'pilot','index':index},
                    progress=progress or dict(done=True,net_pnl='1.25'))

    def test_chunking_and_checksum_do_not_drop_or_mutate_rows(self):
        records=[self.record(i) for i in range(1,424)]
        original=json.loads(json.dumps(records))
        chunks=split_snapshot(records)
        self.assertGreaterEqual(len(chunks),3)
        self.assertEqual([row for section in chunks for row in section],records)
        self.assertTrue(all(1<=len(part)<=MAX_CHUNK_ROWS for part in chunks))
        self.assertEqual(records,original)
        self.assertEqual(digest_records(records),digest_records(original))
        self.assertNotEqual(digest_records(records),digest_records(records[:-1]))
        huge=self.record(500,progress=dict(data='z'*MAX_CHUNK_BYTES))
        self.assertEqual(len(split_snapshot([huge])),1)

    def test_collection_uses_indexed_prefix_pages_and_repeatable_read(self):
        rows=[self.record(1),self.record(2)]
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        requested=[]
        def execute(sql,args=None):
            requested.append(sql)
            cur=MagicMock()
            if 'FROM research_job' not in sql:
                return cur
            if 'idempotency_key=ANY' in sql:
                cur.fetchall.return_value=[]
                return cur
            prefix=args[0]
            # Live write records are the only matching scope.
            cur.fetchall.return_value=rows if prefix=='live/write/' else []
            return cur
        c.execute.side_effect=execute
        result=collect_snapshot(pool)
        self.assertEqual(result,rows)
        self.assertIn('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',requested)
        self.assertIn('SET LOCAL statement_timeout=5000',requested)
        self.assertTrue(all('DELETE FROM research_job' not in sql for sql in requested))
        self.assertTrue(all('UPDATE research_job' not in sql for sql in requested))
        self.assertTrue(any('ORDER BY idempotency_key LIMIT %s' in x for x in requested))
        c.transaction.assert_called_once()
        self.assertIn('ORDER BY idempotency_key LIMIT %s',select_prefix_query(None))
        with self.assertRaises(ValueError):
            select_prefix_query("progress->>'event'='FILL'")

    def test_corrupt_control_record_fails_closed(self):
        for invalid in (dict(self.record(),parameters=[]),
                        dict(self.record(),progress=None),
                        dict(self.record(),idempotency_key=None)):
            pool=MagicMock()
            c=pool.connection.return_value.__enter__.return_value
            def execute(sql,args=None):
                cur=MagicMock()
                if 'FROM research_job' in sql:
                    cur.fetchall.return_value=[invalid]
                return cur
            c.execute.side_effect=execute
            with self.assertRaises(ValueError):collect_snapshot(pool)

    def test_restore_validates_entire_root_all_chunks_and_event_identities(self):
        first=self.record(1);second=self.record(2)
        part=dict(format=PART_FORMAT,count=2,records=[first,second])
        ref=dict(key='demo/backups/part.json.gz',size=45,sha256='a'*64)
        root=dict(format=FORMAT,records=2,sha256=digest_records([first,second]),
                  chunks=[dict(reference=ref,count=2)])
        root_ref=dict(key='demo/backups/root.json.gz',size=37,sha256='b'*64)
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[root,part]) as reader:
            restored=restore_verified_snapshot(MagicMock(),root_ref)
        self.assertEqual(restored,[first,second])
        self.assertEqual(reader.call_count,2)
        wrong=dict(root,sha256='0'*64)
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[wrong,part]):
            with self.assertRaisesRegex(ValueError,'aggregate integrity'):
                restore_verified_snapshot(MagicMock(),root_ref)
        duplicate=dict(part,records=[first,first])
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[root,duplicate]):
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                restore_verified_snapshot(MagicMock(),root_ref)
        bad=dict(root,chunks=[dict(reference=ref,count=3)])
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[bad,part]):
            with self.assertRaisesRegex(ValueError,'chunk count'):
                restore_verified_snapshot(MagicMock(),root_ref)

    def staged(self,records):
        payload=dict(format=PART_FORMAT,count=len(records),records=records)
        blob=canonical(payload)
        buffer=BytesIO(len(blob).to_bytes(4,'big')+blob)
        return dict(file=buffer,records=len(records),parts=1,
                    sha256=digest_records(records),staged_bytes=len(blob))

    def test_spooling_uses_single_snapshot_and_limited_memory(self):
        records=[self.record(1),self.record(2)]
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        def execute(sql,args=None):
            result=MagicMock()
            if 'FROM research_job' in sql:
                if 'idempotency_key=ANY' in sql:
                    result.fetchall.return_value=[]
                else:
                    result.fetchall.return_value=records if args[0]=='live/write/' else []
            return result
        c.execute.side_effect=execute
        with patch('services.demo.control_backup_v2.tempfile.TemporaryFile',
                   return_value=BytesIO()) as temp:
            staged=collect_snapshot_spooled(pool)
        self.assertEqual(staged['records'],2)
        self.assertEqual(staged['parts'],1)
        self.assertEqual(staged['sha256'],digest_records(records))
        length=int.from_bytes(staged['file'].read(4),'big')
        content=json.loads(staged['file'].read(length))
        self.assertEqual(content['format'],PART_FORMAT)
        self.assertEqual(content['records'],records)
        staged['file'].close()
        self.assertEqual(c.execute.call_args_list[0].args[0],
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.transaction.assert_called_once()
        with patch('services.demo.control_backup_v2.MAX_STAGED_BYTES',80):
            with self.assertRaisesRegex(ValueError,'Spool size budget'):
                collect_snapshot_spooled(pool)

    def test_spool_refuses_low_disk_without_creating_a_file(self):
        from services.demo.control_backup_v2 import MIN_FREE_DISK_RESERVE
        with patch('services.demo.control_backup_v2.shutil.disk_usage',
                   return_value=SimpleNamespace(free=MIN_FREE_DISK_RESERVE)), patch(
                   'services.demo.control_backup_v2.tempfile.TemporaryFile') as temp:
            with self.assertRaisesRegex(ValueError,'Insufficient temporary disk'):
                collect_snapshot_spooled(MagicMock())
            temp.assert_not_called()

    def test_full_r2_verification_without_holding_all_records(self):
        records=[self.record(1),self.record(2)]
        reference=dict(key='demo/backups/root.json.gz',size=200,sha256='a'*64)
        part_ref=dict(key='demo/backups/part.json.gz',size=100,sha256='b'*64)
        root=dict(format=FORMAT,records=2,sha256=digest_records(records),
                  chunks=[dict(reference=part_ref,count=2)])
        part=dict(format=PART_FORMAT,count=2,records=records)
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[root,part]) as reader:
            result=verify_staged_archive(MagicMock(),reference)
        self.assertEqual(result,dict(records=2,sha256=digest_records(records),chunks=1))
        self.assertEqual(reader.call_count,2)
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[root,dict(part,records=[records[0],records[0]])]):
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                verify_staged_archive(MagicMock(),reference)
        wrong_root=dict(root,sha256='0'*64)
        with patch('services.demo.control_backup_v2.read_verified',
                   side_effect=[wrong_root,part]):
            with self.assertRaisesRegex(ValueError,'root digest'):
                verify_staged_archive(MagicMock(),reference)

    def test_backup_persists_health_only_after_full_r2_restore(self):
        records=[self.record(1),self.record(2)]
        store=MagicMock()
        receipts=[dict(key='demo/backups/a',size=101,sha256='a'*64),
                  dict(key='demo/backups/b',size=60,sha256='b'*64)]
        with patch('services.demo.control_backup_v2.collect_snapshot_spooled',
                   return_value=self.staged(records)), patch(
                   'services.demo.control_backup_v2.put_verified',
                   side_effect=receipts) as put, patch(
                   'services.demo.control_backup_v2.verify_staged_archive',
                   return_value=dict(records=2,sha256=digest_records(records),chunks=1)):
            result=backup_controls(store,MagicMock(),now=123)
        self.assertTrue(result['verified'])
        self.assertEqual(result['records'],2)
        self.assertEqual(put.call_count,2)
        self.assertEqual(put.call_args_list[0].args[2]['format'],PART_FORMAT)
        self.assertEqual(put.call_args_list[1].args[2]['format'],FORMAT)
        self.assertEqual(store.put.call_args.args[0],'backup-health')
        self.assertEqual(store.put.call_args.args[1]['format'],FORMAT)
        self.assertEqual(store.put.call_args.args[1]['records'],2)
        with patch('services.demo.control_backup_v2.collect_snapshot_spooled',
                   return_value=self.staged(records)), patch(
                   'services.demo.control_backup_v2.put_verified',
                   side_effect=RuntimeError('private R2 error')):
            store=MagicMock()
            with self.assertRaises(RuntimeError):
                backup_controls(store,MagicMock(),now=123)
            store.put.assert_not_called()
        with patch('services.demo.control_backup_v2.collect_snapshot_spooled',
                   return_value=self.staged(records)), patch(
                   'services.demo.control_backup_v2.put_verified',
                   side_effect=receipts), patch(
                   'services.demo.control_backup_v2.verify_staged_archive',
                   return_value=dict(records=1,sha256=digest_records(records),chunks=1)):
            store=MagicMock()
            with self.assertRaises(ValueError):
                backup_controls(store,MagicMock(),now=123)
            store.put.assert_not_called()

    def test_recovery_flag_requires_stopped_writers_and_backup_is_opt_in(self):
        settings=SimpleNamespace(role='collector',enabled=False,acceptance='off',
                                 operator_action='off')
        env=dict(MT_CONTROL_BACKUP_V2_ONCE='true',MT_STORAGE_RECOVERY_HOLD='true',
                 MT_CONTROL_BACKUP_AUDIT='false',MT_ARCHIVE_VERIFY_ONCE='false',
                 MT_ARCHIVE_RECOVERY_LOOP='false')
        self.assertFalse(is_authorized({},settings))
        self.assertTrue(is_authorized(env,settings))
        with self.assertRaises(ValueError):
            is_authorized(dict(env,MT_STORAGE_RECOVERY_HOLD='false'),settings)
        with self.assertRaises(ValueError):
            is_authorized(dict(env,MT_CONTROL_BACKUP_AUDIT='true'),settings)
        with self.assertRaises(ValueError):
            is_authorized(env,SimpleNamespace(role='demo',enabled=False,acceptance='off',operator_action='off'))

    def test_one_shot_failure_does_not_emit_credential_or_modify_health(self):
        factory=MagicMock(side_effect=RuntimeError('secret postgres url'))
        outputs=[]
        result=backup_once('postgresql://private',{},pool_factory=factory,
            emit=lambda s,**kw:outputs.append(s))
        self.assertFalse(result['verified'])
        self.assertEqual(result['error_type'],'RuntimeError')
        self.assertNotIn('private',outputs[0])
        self.assertNotIn('secret',outputs[0])

if __name__=='__main__':
    unittest.main()

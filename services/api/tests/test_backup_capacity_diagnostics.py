"""A failed backup reports only its exact bounded capacity cause and scope."""
import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from services.demo.backup_limit import BackupSnapshotLimit
from services.demo.control_backup_v2 import collect_snapshot_spooled,MAX_STAGED_ROWS
from services.demo.maintenance import failure_details


class BackupCapacityDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def pool_with_live_writes():
        records=[dict(id='11111111-1111-1111-1111-%012d'%i,
                      idempotency_key='live/write/'+str(i),
                      parameters={'index':i},progress={'secret':'private-value'})
                 for i in (1,2)]
        pool=MagicMock()
        connection=pool.connection.return_value.__enter__.return_value

        def execute(sql,args=None):
            result=MagicMock()
            if 'FROM research_job' in sql:
                if 'idempotency_key=ANY' in sql:
                    result.fetchall.return_value=[]
                else:
                    result.fetchall.return_value=(records if args[0]=='live/write/' else [])
            return result

        connection.execute.side_effect=execute
        return pool,records

    def test_row_cap_aborts_snapshot_with_precise_safe_fields(self):
        pool,records=self.pool_with_live_writes()
        temporary=BytesIO()
        with patch('services.demo.control_backup_v2.MAX_STAGED_ROWS',1), patch(
                'services.demo.control_backup_v2.tempfile.TemporaryFile',
                return_value=temporary), patch(
                'services.demo.control_backup_v2.shutil.disk_usage',
                return_value=SimpleNamespace(free=2*1024**3)):
            with self.assertRaises(BackupSnapshotLimit) as raised:
                collect_snapshot_spooled(pool)
        self.assertTrue(temporary.closed)
        error=raised.exception
        self.assertEqual(error.kind,'rows')
        self.assertEqual(error.scope,'live_writes')
        self.assertEqual(error.records,1)
        self.assertEqual(error.limit,1)
        report=failure_details(error,'backup')
        self.assertEqual(report['reason_code'],'backup_row_capacity')
        self.assertEqual(report['backup_scope'],'live_writes')
        self.assertEqual(report['capacity_unit'],'rows')
        self.assertEqual(report['capacity_limit'],1)
        self.assertEqual(report['staged_records'],1)
        self.assertNotIn('private-value',json.dumps(report))
        self.assertNotIn('live/write/1',json.dumps(report))

    def test_byte_cap_preserves_v2_error_contract_and_no_partial_spool(self):
        pool,records=self.pool_with_live_writes()
        temporary=BytesIO()
        with patch('services.demo.control_backup_v2.MAX_STAGED_BYTES',80), patch(
                'services.demo.control_backup_v2.tempfile.TemporaryFile',
                return_value=temporary), patch(
                'services.demo.control_backup_v2.shutil.disk_usage',
                return_value=SimpleNamespace(free=2*1024**3)):
            with self.assertRaisesRegex(BackupSnapshotLimit,'Spool size budget') as raised:
                collect_snapshot_spooled(pool)
        self.assertTrue(temporary.closed)
        report=failure_details(raised.exception,'backup')
        self.assertEqual(report['reason_code'],'backup_byte_capacity')
        self.assertEqual(report['backup_scope'],'live_writes')
        self.assertEqual(report['capacity_unit'],'bytes')
        self.assertEqual(report['capacity_limit'],80)
        self.assertEqual(report['staged_records'],0)
        self.assertNotIn('private-value',json.dumps(report))

    def test_static_scopes_and_numbers_required(self):
        for args in [
                ('rows','postgresql://private.example',1,2,3),
                ('sensitive','live_writes',1,2,3),
                ('bytes','live_writes',True,2,3),
                ('bytes','live_writes',1,-1,3)]:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    BackupSnapshotLimit(*args)

    def test_old_generic_valueerror_stays_generic(self):
        old=failure_details(ValueError('Spool size budget exceeded; no partial backup published'),'backup')
        self.assertEqual(old['reason_code'],'backup_spool_capacity')
        self.assertNotIn('backup_scope',old)


if __name__=='__main__':
    unittest.main()

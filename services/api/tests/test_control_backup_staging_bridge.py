"""The temporary larger spool stays fail-closed and strictly disk-bounded."""
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from services.demo.backup_limit import BackupSnapshotLimit
from services.demo.control_backup_v2 import (
    MAX_STAGED_BYTES,MIN_FREE_DISK_RESERVE,MAX_STAGED_ROWS,
    MAX_CHUNK_BYTES,collect_snapshot_spooled,
)


class TemporaryStagingBudgetTests(unittest.TestCase):
    def test_temporary_bridge_is_explicitly_bounded(self):
        # Backups were 499,163,978 staged bytes on Nov 20; the old 512 MiB
        # cap was exhausted by sustained source growth. Do not expand the
        # row budget, R2 part sizes or the source scopes.
        self.assertEqual(MAX_STAGED_BYTES,1024*1024*1024)
        self.assertEqual(MIN_FREE_DISK_RESERVE,512*1024*1024)
        self.assertEqual(MAX_STAGED_ROWS,100000)
        self.assertEqual(MAX_CHUNK_BYTES,2*1024*1024)

    def test_no_spool_if_reserve_is_all_that_is_free(self):
        with patch('services.demo.control_backup_v2.shutil.disk_usage',
                   return_value=SimpleNamespace(free=MIN_FREE_DISK_RESERVE)),patch(
                   'services.demo.control_backup_v2.tempfile.TemporaryFile') as create:
            with self.assertRaisesRegex(ValueError,'Insufficient temporary disk headroom'):
                collect_snapshot_spooled(MagicMock())
            create.assert_not_called()

    def test_large_max_still_clamps_to_actual_free_disk_and_closes_file(self):
        # A large configured ceiling must NOT permit a full temp disk.
        row=dict(id='00000000-0000-0000-0000-000000000001',
                 idempotency_key='live/write/test',
                 parameters=dict(test=True),progress=dict(done=True))
        pool=MagicMock()
        connection=pool.connection.return_value.__enter__.return_value
        def execute(sql,args=None):
            result=MagicMock()
            if 'FROM research_job' in sql:
                result.fetchall.return_value=(
                    [row] if args and args[0]=='live/write/' else [])
            return result
        connection.execute.side_effect=execute
        spool=BytesIO()
        available=MIN_FREE_DISK_RESERVE+50
        with patch('services.demo.control_backup_v2.shutil.disk_usage',
                   return_value=SimpleNamespace(free=available)),patch(
                   'services.demo.control_backup_v2.tempfile.TemporaryFile',
                   return_value=spool):
            with self.assertRaises(BackupSnapshotLimit) as error:
                collect_snapshot_spooled(pool)
        self.assertTrue(spool.closed)
        self.assertEqual(error.exception.kind,'bytes')
        self.assertEqual(error.exception.scope,'live_writes')
        self.assertEqual(error.exception.limit,50)
        self.assertEqual(error.exception.records,0)


if __name__=='__main__':
    unittest.main()

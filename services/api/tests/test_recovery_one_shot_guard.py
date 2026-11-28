"""MT-019 startup exclusion checks for recovery-only audit and backup tasks."""
import unittest
from threading import Event
from unittest.mock import patch

from services.research import runtime
from services.research.recovery_one_shot_guard import (
    ONE_SHOTS, check_recovery_jobs_exclusive,
)


class RecoveryOneShotExclusivityTests(unittest.TestCase):
    def test_no_one_shot_preserves_disabled_and_normal_startup(self):
        self.assertEqual(check_recovery_jobs_exclusive({}), ())
        self.assertEqual(check_recovery_jobs_exclusive({
            'MT_ARCHIVE_RECOVERY_LOOP':'false',
            'MT_CONTROL_BACKUP_V2_ENABLED':'false',
            'MT_WAL_PREFLIGHT_ONCE':'false',
        }), ())

    def test_every_one_shot_is_independently_allowed(self):
        for flag in ONE_SHOTS:
            with self.subTest(flag=flag):
                self.assertEqual(
                    check_recovery_jobs_exclusive({flag:'true'}), (flag,))

    def test_every_pair_is_rejected_before_network_io(self):
        for i,left in enumerate(ONE_SHOTS):
            for right in ONE_SHOTS[i+1:]:
                with self.subTest(left=left,right=right):
                    flags={left:'true',right:'true'}
                    with self.assertRaisesRegex(ValueError,'Only one'):
                        check_recovery_jobs_exclusive(flags)
                    with patch.dict(runtime.os.environ,flags,clear=True), \
                         patch.object(runtime.R2Objects,'connect') as connect, \
                         patch.object(runtime,'ConnectionPool') as pool:
                        with self.assertRaises(ValueError):
                            runtime.run(object(),Event())
                        connect.assert_not_called()
                        pool.assert_not_called()

    def test_no_one_shot_can_overlap_archival_or_recurring_backup(self):
        for flag in ONE_SHOTS:
            for other in ('MT_ARCHIVE_RECOVERY_LOOP',
                          'MT_CONTROL_BACKUP_V2_ENABLED'):
                with self.subTest(flag=flag,other=other):
                    with self.assertRaises(ValueError):
                        check_recovery_jobs_exclusive({
                            flag:'true',other:'true',
                        })

    def test_exact_census_is_only_a_backup_audit_addon(self):
        with self.assertRaisesRegex(ValueError,'Exact census'):
            check_recovery_jobs_exclusive({
                'MT_BACKUP_EXACT_CENSUS':'true',
            })
        self.assertEqual(check_recovery_jobs_exclusive({
            'MT_BACKUP_EXACT_CENSUS':'true',
            'MT_CONTROL_BACKUP_AUDIT':'true',
        }), ('MT_CONTROL_BACKUP_AUDIT',))
        with self.assertRaises(ValueError):
            check_recovery_jobs_exclusive({
                'MT_BACKUP_EXACT_CENSUS':'true',
                'MT_CONTROL_BACKUP_AUDIT':'true',
                'MT_ARCHIVE_RECOVERY_LOOP':'true',
            })
        with self.assertRaises(ValueError):
            check_recovery_jobs_exclusive({
                'MT_BACKUP_EXACT_CENSUS':'true',
                'MT_ARCHIVE_RECOVERY_LOOP':'true',
            })


if __name__ == '__main__':
    unittest.main()

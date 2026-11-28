"""MT-019 temp preflight does not access the database or write any file."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from services.research.recovery_temp_disk_audit import (
    RESERVE_BYTES,MAX_STAGE_BYTES,SOURCE_JSONB_BYTES,
    is_authorized,inspect,audit_once
)


class TempDiskRecoveryAuditTests(unittest.TestCase):
    def settings(self,**override):
        return SimpleNamespace(**dict(dict(role='collector',enabled=False,
            acceptance='off',operator_action='off'),**override))

    def env(self,**override):
        return dict(dict(MT_WORKER_DISK_AUDIT_ONCE='true',
            MT_STORAGE_RECOVERY_HOLD='true',COLLECTION_ENABLED='false',
            MT_CONTROL_BACKUP_AUDIT='false',MT_ARCHIVE_VERIFY_ONCE='false',
            MT_ARCHIVE_RECOVERY_LOOP='false',MT_CONTROL_BACKUP_V2_ONCE='false'),
            **override)

    def test_explicitly_off_by_default_and_recovery_held_only(self):
        self.assertFalse(is_authorized({},self.settings()))
        self.assertTrue(is_authorized(self.env(),self.settings()))
        for name,val in (
            ('MT_STORAGE_RECOVERY_HOLD','false'),
            ('COLLECTION_ENABLED','true'),
            ('MT_CONTROL_BACKUP_AUDIT','true'),
            ('MT_ARCHIVE_VERIFY_ONCE','true'),
            ('MT_ARCHIVE_RECOVERY_LOOP','true'),
            ('MT_CONTROL_BACKUP_V2_ONCE','true')):
            with self.subTest(name=name),self.assertRaises(ValueError):
                is_authorized(self.env(**{name:val}),self.settings())
        for change in (dict(role='demo'),dict(enabled=True),
                       dict(acceptance='enabled'),dict(operator_action='prepare-roles-v1')):
            with self.assertRaises(ValueError):
                is_authorized(self.env(),self.settings(**change))

    def test_statvfs_and_disk_usage_take_conservative_minimum(self):
        GiB=1024*1024*1024
        usage=SimpleNamespace(total=2*GiB,used=GiB,free=GiB)
        stat=SimpleNamespace(f_bavail=600,f_frsize=1024*1024)
        audit=inspect(tempdir=lambda:'/tmp',disk_usage=lambda _:usage,
                      statvfs=lambda _:stat)
        self.assertEqual(audit['conservative_available_bytes'],600*1024*1024)
        self.assertEqual(audit['maximum_stage_budget_bytes'],
                         min(MAX_STAGE_BYTES,600*1024*1024-RESERVE_BYTES))
        self.assertTrue(audit['source_jsonb_fits_stage_budget'])
        self.assertEqual(audit['sufficient_for_full_backup'],'unverified')
        self.assertTrue(audit['no_write'])
        self.assertTrue(audit['no_database_access'])

    def test_low_disk_gives_zero_budget_and_never_claims_safe(self):
        usage=SimpleNamespace(total=500,used=450,free=50)
        stat=SimpleNamespace(f_bavail=50,f_frsize=1)
        result=inspect(tempdir=lambda:'/tmp',disk_usage=lambda _:usage,
                       statvfs=lambda _:stat)
        self.assertEqual(result['maximum_stage_budget_bytes'],0)
        self.assertFalse(result['source_jsonb_fits_stage_budget'])
        self.assertEqual(result['shadow_bot_census_jsonb_bytes'],187718269)
        self.assertEqual(result['total_control_census_jsonb_bytes'],SOURCE_JSONB_BYTES)

    def test_one_shot_sanitized_failure_does_not_reveal_secret(self):
        emitted=[]
        def fail():
            raise RuntimeError('secret-key/password=private')
        result=audit_once(inspect_fn=fail,
            emit=lambda msg,**kwargs:emitted.append(json.loads(msg)))
        self.assertFalse(result['verified'])
        self.assertEqual(result['error_type'],'RuntimeError')
        self.assertNotIn('secret-key',json.dumps(emitted))
        self.assertNotIn('private',json.dumps(emitted))
        self.assertTrue(result['no_write'])

    def test_one_shot_uses_only_inspection_function(self):
        out=[]
        f=MagicMock(return_value=dict(filesystem_free_bytes=123,
            maximum_stage_budget_bytes=1))
        result=audit_once(inspect_fn=f,
            emit=lambda msg,**kwargs:out.append(json.loads(msg)))
        f.assert_called_once()
        self.assertTrue(result['verified'])
        self.assertEqual(out[0]['filesystem_free_bytes'],123)
        self.assertTrue(out[0]['advisory_only'])


if __name__=='__main__':
    unittest.main()

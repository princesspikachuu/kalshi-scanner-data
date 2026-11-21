"""Retention bounds, dry runs, cursor progress and R2 failure ordering."""
import io
import unittest
from unittest.mock import MagicMock, patch

from services.demo import shadow_diagnostic_retention as retention
from services.api.tests import test_shadow_archive_recovery as fixtures


class MemoryObjects:
    def __init__(self):
        self.client = self
        self.bucket = 'disposable-test'
        self.objects = {}
        self.on_read = lambda: None

    def put_object(self, **kw):
        self.objects[kw['Key']] = kw['Body']

    def get_object(self, **kw):
        body = self.objects[kw['Key']]
        self.on_read()
        return dict(ContentLength=len(body), Body=io.BytesIO(body))


class DiagnosticRetentionTests(unittest.TestCase):
    def env(self):
        return dict(RECOVERY_DATABASE_URL='postgresql://archive@local/pocket_test',
                    DATABASE_URL='postgresql://app@local/pocket_test', DATABASE_CAPACITY_GB='15',
                    MT_DIAGNOSTIC_RETENTION_ENABLED='true',
                    MT_DIAGNOSTIC_RETENTION_READ_PATH_VERIFIED='true',
                    MT_DIAGNOSTIC_RETENTION_HEADROOM_VERIFIED='true',
                    MT_STORAGE_RECOVERY_HOLD='false')

    def test_default_off_and_cannot_bypass_recovery(self):
        env = self.env()
        self.assertEqual(retention.settings(env, True)[1], 15)
        for key in ('MT_DIAGNOSTIC_RETENTION_ENABLED', 'MT_DIAGNOSTIC_RETENTION_READ_PATH_VERIFIED',
                    'MT_DIAGNOSTIC_RETENTION_HEADROOM_VERIFIED', 'MT_STORAGE_RECOVERY_HOLD'):
            missing = dict(env); missing.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                retention.settings(missing, True)
        for change in (dict(MT_STORAGE_RECOVERY_HOLD='true'), dict(MT_ARCHIVE_RECOVERY_LOOP='true'),
                       dict(RECOVERY_DATABASE_URL=env['DATABASE_URL'])):
            with self.assertRaises(ValueError):
                retention.settings(dict(env, **change), True)
        # Read-only preview remains possible while recovery is held.
        retention.settings(dict(env, MT_STORAGE_RECOVERY_HOLD='true'), False)

    def test_selection_advances_past_ineligible_rows_in_a_readonly_bounded_page(self):
        pool = MagicMock()
        c = pool.connection.return_value.__enter__.return_value
        keys = [dict(idempotency_key=retention.PREFIX+str(i)) for i in range(2)]
        def query(sql, args=None):
            result = MagicMock()
            result.fetchall.return_value = keys if sql == retention.KEY_PAGE else []
            return result
        c.execute.side_effect = query
        rows, cursor, scanned, complete = retention.select_page(
            pool, retention.PREFIX, retention.PREFIX, now=1794500000, page_size=2)
        self.assertEqual((rows, cursor, scanned, complete), ([], keys[-1]['idempotency_key'], 2, False))
        calls = c.execute.call_args_list
        self.assertIn('READ ONLY', calls[0].args[0])
        self.assertEqual(calls[3].args, (retention.KEY_PAGE, (retention.PREFIX, retention.PREFIX+'zzzz', 2)))
        self.assertEqual(calls[4].args[1][0], [k['idempotency_key'] for k in keys])
        self.assertNotIn('progress', retention.KEY_PAGE)
        for kwargs in (dict(age_hours=23), dict(page_size=101), dict(age_hours=True)):
            with self.assertRaises(ValueError):
                retention.select_page(pool, retention.PREFIX, retention.PREFIX, now=1, **kwargs)

    def test_failed_r2_read_never_opens_delete_transaction(self):
        pool = MagicMock(); objects = MemoryObjects()
        objects.on_read = lambda: (_ for _ in ()).throw(RuntimeError('read failed'))
        row = fixtures.ShadowArchiveRecoveryTests().row()
        with self.assertRaises(RuntimeError):
            retention.reclaim_page(pool, objects, [row], retention.PREFIX, 1794500000)
        pool.connection.assert_not_called()

    def test_preview_and_failure_do_not_delete_or_advance_cursor(self):
        cursors = {}; row = fixtures.ShadowArchiveRecoveryTests().row()
        with patch.object(retention, 'database_bytes', return_value=9_000_000_000), patch.object(
                retention, 'select_page', return_value=([row], retention.PREFIX+'x', 1, False)), patch.object(
                retention, 'reclaim_page') as reclaim:
            report = retention.cycle(MagicMock(), None, cursors, now=1, capacity_gb=15, pages=1)
        reclaim.assert_not_called()
        self.assertEqual(report['eligible_rows'], 2)
        self.assertEqual(report['deleted_rows'], 0)
        self.assertIsNone(report['physical_bytes_freed'])
        cursors = {}
        with patch.object(retention, 'database_bytes', return_value=9_000_000_000), patch.object(
                retention, 'verify_scoped_role'), patch.object(retention, 'select_page',
                return_value=([row], retention.PREFIX+'x', 1, False)), patch.object(
                retention, 'reclaim_page', side_effect=RuntimeError('concurrent modification')):
            with self.assertRaises(RuntimeError):
                retention.cycle(MagicMock(), None, cursors, now=1, capacity_gb=15, execute=True)
        self.assertEqual(cursors, {})

    def test_empty_namespace_does_not_repeat_within_cycle_and_capacity_blocks_mutation(self):
        with patch.object(retention, 'database_bytes', return_value=9_000_000_000), patch.object(
                retention, 'select_page', side_effect=lambda _, p, *a, **k: ([], p, 0, True)) as select:
            report = retention.cycle(MagicMock(), None, {}, now=1, capacity_gb=15)
        self.assertEqual(select.call_count, 2)
        self.assertEqual(report['completed_passes'], 2)
        with patch.object(retention, 'database_bytes', return_value=13_000_000_000), patch.object(
                retention, 'reclaim_page') as reclaim:
            with self.assertRaisesRegex(RuntimeError, 'capacity guard'):
                retention.cycle(MagicMock(), None, {}, now=1, capacity_gb=15, execute=True)
        reclaim.assert_not_called()

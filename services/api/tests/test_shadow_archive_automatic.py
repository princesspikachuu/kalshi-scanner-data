"""MT-019 automatic recovery loop is disabled unless every safety condition holds."""
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

from services.demo.shadow_archive_automatic import (
    Limits, ROLE_QUERY, archive_cycle, configuration, verify_scoped_role, run
)


class RecoveryArchiveAutomaticTests(unittest.TestCase):
    def env(self):
        return dict(
            MT_ARCHIVE_RECOVERY_LOOP='true',
            MT_ARCHIVE_WRITERS_STOPPED='true',
            MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED='true',
            MT_STORAGE_RECOVERY_HOLD='true',
            WORKER_ROLE='collector',
            COLLECTION_ENABLED='false',
            STAGING_ACCEPTANCE='off',
            STAGING_OPERATOR_ACTION='off',
            MT_STORAGE_RECOVERY_AUDIT='false',
            DATABASE_CAPACITY_GB='15',
            DATABASE_URL='postgresql://app:placeholder@localhost/db',
            RECOVERY_DATABASE_URL='postgresql://archive:placeholder@localhost/db',
        )

    def pool(self, *, size=9_000_000_000, principal='pocket_archive_maintenance', owner='owner', elevated=False, truncate=False, schema_create=False, membership=False):
        pool = MagicMock()
        conn = pool.connection.return_value.__enter__.return_value

        def query(sql):
            result = MagicMock()
            if sql == ROLE_QUERY:
                result.fetchone.return_value = dict(
                    principal=principal, owner=owner, elevated=elevated,
                    can_select=True, can_insert=False, can_delete=False,
                    can_update=False, can_truncate=truncate,
                    can_schema_create=schema_create, can_scoped_reclaim=True,
                    has_memberships=membership)
            else:
                result.fetchone.return_value = dict(bytes=size)
            return result

        conn.execute.side_effect = query
        return pool

    def test_configuration_defaults_off_and_requires_separate_role(self):
        base = self.env()
        self.assertEqual(configuration(base).capacity_gb, 15)
        self.assertEqual(configuration(base).interval_seconds, 60)
        self.assertEqual(configuration(base).raw_batch_size, 50)
        for key, invalid in (
                ('MT_ARCHIVE_RECOVERY_LOOP', 'false'),
                ('MT_ARCHIVE_WRITERS_STOPPED', 'false'),
                ('MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED', 'false'),
                ('MT_STORAGE_RECOVERY_HOLD', 'false'),
                ('WORKER_ROLE', 'demo'),
                ('COLLECTION_ENABLED', 'true'),
                ('STAGING_ACCEPTANCE', 'r2-v1'),
                ('STAGING_OPERATOR_ACTION', 'prepare-roles-v1'),
                ('MT_STORAGE_RECOVERY_AUDIT', 'true')):
            invalid_env = dict(base, **{key: invalid})
            with self.subTest(key=key), self.assertRaises(ValueError):
                configuration(invalid_env)
        with self.assertRaises(ValueError):
            configuration(dict(base, MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED=''))
        with self.assertRaises(ValueError):
            configuration(dict(base, RECOVERY_DATABASE_URL=base['DATABASE_URL']))
        with self.assertRaises(ValueError):
            configuration(dict(base, RECOVERY_DATABASE_URL=''))
        with self.assertRaises(ValueError):
            configuration(dict(base, DATABASE_CAPACITY_GB=''))
        for key, value in (('MT_ARCHIVE_INTERVAL_SECONDS', '1'),
                           ('MT_ARCHIVE_RAW_BATCH_SIZE', '151'),
                           ('MT_ARCHIVE_RAW_BATCHES', '0'),
                           ('MT_ARCHIVE_PACKED_BATCHES', '100'),
                           ('MT_ARCHIVE_PACKED_BATCH_SIZE', '0')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                configuration(dict(base, **{key: value}))

    def test_privilege_audit_targets_public_schema_not_search_path(self):
        self.assertIn("schemaname='public'", ROLE_QUERY)
        self.assertIn("'public.research_job'", ROLE_QUERY)
        self.assertIn("has_schema_privilege(current_user,'public','CREATE')", ROLE_QUERY)
        self.assertNotIn('current_schema()', ROLE_QUERY)
        self.assertIn('pg_auth_members', ROLE_QUERY)
        self.assertIn('rolbypassrls OR rolinherit', ROLE_QUERY)

    def test_refuse_database_owner_and_admin_role(self):
        for pool in (self.pool(principal='owner', owner='owner'),
                     self.pool(principal='pocket_archive_maintenance', elevated=True),
                     self.pool(owner=None),
                     self.pool(truncate=True),
                     self.pool(schema_create=True),
                     self.pool(membership=True),
                     self.pool(principal='different-scoped-role')):
            with self.assertRaises(ValueError):
                verify_scoped_role(pool)
        good = self.pool()
        verify_scoped_role(good)
        good.connection.return_value.__enter__.return_value.execute.assert_called_with(ROLE_QUERY)

    def test_recovery_cycle_limits_deletes_and_verifies_both_formats(self):
        pool = self.pool()
        limits = configuration(self.env())
        raw = dict(archived=10, deleted=10, verified=True,
                   manifest_stored=True, compressed_bytes=1400)
        packed = dict(archived_rows=2, deleted_rows=2, original_events=30,
                      verified=True, compressed_bytes=1000)
        with patch('services.demo.shadow_archive_automatic.archive_and_reclaim_one',
                   side_effect=[raw, dict(archived=0, deleted=0)]) as a, patch(
                   'services.demo.shadow_archive_automatic.archive_one',
                   side_effect=[packed, dict(archived_rows=0, deleted_rows=0)]) as b:
            report = archive_cycle(pool, MagicMock(), limits, now=1794500000)
        self.assertEqual(report['raw_rows'], 10)
        self.assertEqual(report['packed_rows'], 2)
        self.assertEqual(report['original_packed_events'], 30)
        self.assertEqual(report['compressed_bytes'], 2400)
        self.assertEqual(a.call_count, 2)
        self.assertEqual(b.call_count, 2)
        self.assertEqual(a.call_args.kwargs['age_hours'], 24)
        self.assertEqual(a.call_args.kwargs['batch_size'], 50)
        self.assertTrue(a.call_args.kwargs['scoped'])
        self.assertTrue(b.call_args.kwargs['scoped'])
        self.assertEqual(b.call_args.kwargs['batch_size'], 2)

    def test_no_archival_near_capacity(self):
        with patch('services.demo.shadow_archive_automatic.archive_and_reclaim_one') as a:
            with self.assertRaisesRegex(RuntimeError, 'capacity guard'):
                archive_cycle(self.pool(size=12_500_000_000), MagicMock(),
                              configuration(self.env()))
            a.assert_not_called()

    def test_missing_receipt_and_mismatch_fail_closed(self):
        pool = self.pool()
        limits = configuration(self.env())
        for receipt in (dict(archived=2, deleted=1),
                        dict(archived=2, deleted=2, verified=False, manifest_stored=True),
                        dict(archived=2, deleted=2, verified=True, manifest_stored=False)):
            with patch('services.demo.shadow_archive_automatic.archive_and_reclaim_one',
                       return_value=receipt), self.assertRaises(RuntimeError):
                archive_cycle(pool, MagicMock(), limits)
        with patch('services.demo.shadow_archive_automatic.archive_and_reclaim_one',
                   return_value=dict(archived=0, deleted=0)), patch(
                   'services.demo.shadow_archive_automatic.archive_one',
                   return_value=dict(archived_rows=1, deleted_rows=1, verified=False)), self.assertRaises(RuntimeError):
            archive_cycle(pool, MagicMock(), limits)

    def test_stop_fence_prevents_work_and_unauthorized_start_never_connects(self):
        limits = configuration(self.env())
        with patch('services.demo.shadow_archive_automatic.archive_and_reclaim_one') as a, patch(
                'services.demo.shadow_archive_automatic.archive_one') as b:
            archive_cycle(self.pool(), MagicMock(), limits, stopped=lambda: True)
            a.assert_not_called()
            b.assert_not_called()
        invalid = dict(self.env(), MT_ARCHIVE_WRITERS_STOPPED='false')
        with patch('services.demo.shadow_archive_automatic.ConnectionPool') as constructor:
            with self.assertRaises(ValueError):
                run(Event(), invalid)
            constructor.assert_not_called()


if __name__ == '__main__':
    unittest.main()

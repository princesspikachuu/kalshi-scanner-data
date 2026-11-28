"""MT-019: WAL inspection must remain one-shot, read-only and nonauthorizing."""
import json
import unittest
from threading import Event
from unittest.mock import MagicMock, Mock, patch

from services.research import runtime
from services.research.recovery_wal_preflight import (
    CONNECTION_OPTIONS, INCOMPATIBLE_FLAGS, QUERIES, audit_once, is_authorized,
)


class WALRecoveryPreflightTests(unittest.TestCase):
    def settings(self, **override):
        env = dict(
            DATABASE_URL='postgresql://private-sentinel@db/research',
            R2_ACCOUNT_ID='a' * 32, R2_BUCKET='test-archive',
            R2_ACCESS_KEY_ID='access-sentinel',
            R2_SECRET_ACCESS_KEY='secret-sentinel',
            KALSHI_READ_RATE='4', KALSHI_READ_CAPACITY='4',
            KALSHI_ENDPOINT_COST='1', WORKER_ROLE='collector',
            COLLECTION_ENABLED='false', STAGING_ACCEPTANCE='off',
            STAGING_OPERATOR_ACTION='off',
        )
        env.update(override)
        return runtime.WorkerSettings.from_env(env)

    def test_preflight_only_under_explicit_idle_hold(self):
        base = dict(MT_WAL_PREFLIGHT_ONCE='true',
                    MT_STORAGE_RECOVERY_HOLD='true')
        settings = self.settings()
        self.assertTrue(is_authorized(base, settings))
        self.assertFalse(is_authorized({}, settings))
        self.assertFalse(is_authorized(
            dict(MT_WAL_PREFLIGHT_ONCE='false'), settings))
        with self.assertRaises(ValueError):
            is_authorized(dict(base, MT_STORAGE_RECOVERY_HOLD='false'),
                          settings)
        for change in (
            dict(WORKER_ROLE='demo'), dict(WORKER_ROLE='processor'),
            dict(COLLECTION_ENABLED='true'),
            dict(STAGING_ACCEPTANCE='r2-v1'),
            dict(STAGING_OPERATOR_ACTION='prepare-roles-v1'),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                is_authorized(base, self.settings(**change))
        self.assertIn('MT_WORKER_DISK_AUDIT_ONCE', INCOMPATIBLE_FLAGS)
        self.assertIn('MT_BACKUP_EXACT_CENSUS', INCOMPATIBLE_FLAGS)
        for flag in INCOMPATIBLE_FLAGS:
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                is_authorized(dict(base, **{flag: 'true'}), settings)

    def test_bounded_aggregate_queries_never_write_or_emit_secrets(self):
        factory = MagicMock()
        connection = (factory.return_value.__enter__.return_value
                      .connection.return_value.__enter__.return_value)
        rows = {
            'logical_database': {'database_bytes': 9250000000},
            'wal_counters': {'records': 10000,
                             'generated_bytes_since_reset': 250000000},
            'wal_directory': {'segment_count': 8,
                              'directory_bytes': 134217728},
            'connections': {'total': 2, 'active': 0,
                            'idle_in_transaction': 0},
            'archive_role_presence': {
                'role_exists': False, 'login_enabled': False,
                'scoped_function_exists': False,
            },
        }
        query_lookup = {sql: rows[name] for name, sql in QUERIES}
        statements = []

        def execute(sql):
            statements.append(sql)
            result = Mock()
            result.fetchone.return_value = query_lookup.get(sql)
            return result

        connection.execute.side_effect = execute
        emitter = Mock()
        report = audit_once('postgresql://private-sentinel@db/research',
                            pool_factory=factory, emit=emitter)
        self.assertEqual(report['wal_directory']['directory_bytes'],
                         134217728)
        self.assertIs(report['verified_physical_free_disk'], False)
        self.assertIs(report['verified_all_writers_stopped'], False)
        self.assertIs(report['authorizes_archive_reclaim'], False)
        self.assertEqual(factory.call_args.kwargs['max_size'], 1)
        self.assertIn('default_transaction_read_only=on',
                      factory.call_args.kwargs['kwargs']['options'])
        self.assertIn('statement_timeout=3000', CONNECTION_OPTIONS)
        self.assertEqual(
            statements,
            [part for _, sql in QUERIES
             for part in ('SET LOCAL statement_timeout=3000', sql)],
        )
        payload = emitter.call_args.args[0]
        self.assertNotIn('private-sentinel', payload)
        self.assertNotIn('access-sentinel', payload)
        self.assertNotIn('secret-sentinel', payload)
        self.assertEqual(json.loads(payload)['mode'], 'read_only')
        for sql in statements:
            normalized = sql.strip().upper()
            self.assertTrue(
                normalized.startswith('SELECT') or
                normalized.startswith('SET LOCAL'),
            )

    def test_permission_denial_in_wal_directory_does_not_fake_metrics(self):
        factory = MagicMock()
        connection = (factory.return_value.__enter__.return_value
                      .connection.return_value.__enter__.return_value)
        count = [0]

        def execute(sql):
            if sql == QUERIES[2][1]:
                raise PermissionError('private-sentinel')
            count[0] += 1
            return Mock(fetchone=lambda: {'ok': count[0]})

        connection.execute.side_effect = execute
        emitter = Mock()
        result = audit_once('postgresql://private-sentinel@db/research',
                            pool_factory=factory, emit=emitter)
        self.assertEqual(result['wal_directory_error_type'],
                         'PermissionError')
        self.assertNotIn('wal_directory', result)
        self.assertIn('archive_role_presence', result)
        self.assertFalse(result['verified_physical_free_disk'])
        self.assertNotIn('private-sentinel', emitter.call_args.args[0])

    def test_connection_failure_is_type_only(self):
        emitter = Mock()
        report = audit_once('postgresql://private-sentinel@db/research',
                            pool_factory=Mock(
                                side_effect=RuntimeError('private-sentinel')),
                            emit=emitter)
        self.assertEqual(report['connection_error_type'], 'RuntimeError')
        self.assertNotIn('private-sentinel', emitter.call_args.args[0])

    def test_idle_worker_runs_once_without_market_or_r2_or_archive(self):
        settings = self.settings()
        env = dict(MT_WAL_PREFLIGHT_ONCE='true',
                   MT_STORAGE_RECOVERY_HOLD='true')
        with patch.dict(runtime.os.environ, env, clear=True), \
             patch('services.research.recovery_wal_preflight.audit_once') as preflight, \
             patch.object(runtime.R2Objects, 'connect') as r2, \
             patch.object(runtime, 'ConnectionPool') as pool:
            stop = Event()
            stop.set()
            runtime.run(settings, stop)
            preflight.assert_called_once_with(settings.database_url)
            r2.assert_not_called()
            pool.assert_not_called()


if __name__ == '__main__':
    unittest.main()

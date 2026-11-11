"""Emergency inspection is read-only, bounded, and never runs trading."""
import json
import unittest
from unittest.mock import MagicMock, Mock, patch
from threading import Event

from services.research import runtime
from services.research.recovery_storage_audit import (
    EVENT_SAMPLE_SQL, CONNECTION_OPTIONS, audit_once, is_authorized,
)


class EmergencyStorageAuditTests(unittest.TestCase):
    def settings(self, **env):
        raw=dict(
            DATABASE_URL='postgresql://private-sentinel@db/a',
            R2_ACCOUNT_ID='a'*32, R2_BUCKET='pocket-test',
            R2_ACCESS_KEY_ID='access-sentinel',
            R2_SECRET_ACCESS_KEY='secret-sentinel',
            KALSHI_READ_RATE='4', KALSHI_READ_CAPACITY='4',
            KALSHI_ENDPOINT_COST='1', WORKER_ROLE='collector',
            COLLECTION_ENABLED='false', STAGING_ACCEPTANCE='off',
            STAGING_OPERATOR_ACTION='off',
        )
        raw.update(env)
        return runtime.WorkerSettings.from_env(raw)

    def test_gate_requires_storage_hold_and_disabled_collector(self):
        settings=self.settings()
        base=dict(MT_STORAGE_RECOVERY_AUDIT='true', MT_STORAGE_RECOVERY_HOLD='true')
        self.assertTrue(is_authorized(base,settings))
        self.assertFalse(is_authorized({},settings))
        for value in [
            dict(MT_STORAGE_RECOVERY_HOLD='false'),
            dict(MT_STORAGE_RECOVERY_HOLD=''),
        ]:
            with self.assertRaises(ValueError):
                is_authorized(dict(base,**value),settings)
        for change in [
            dict(WORKER_ROLE='demo'),
            dict(WORKER_ROLE='processor'),
            dict(COLLECTION_ENABLED='true'),
            dict(STAGING_ACCEPTANCE='r2-v1'),
            dict(STAGING_OPERATOR_ACTION='prepare-roles-v1'),
        ]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                is_authorized(base,self.settings(**change))

    def test_one_shot_only_reads_aggregates_without_market_or_r2_clients(self):
        pool_factory=MagicMock()
        conn=pool_factory.return_value.__enter__.return_value.connection.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value=[
            dict(event_kind='FAVORITE_STAT_DECISION',sampled_rows=100,
                 sampled_payload_bytes=12000)
        ]
        summary=dict(database_bytes=100_000,relations=[
            dict(relname='research_job',total_bytes=94000)
        ],job_families=[dict(family='demo/shadow',sampled_rows=800)],
            job_sample_percent=1)
        emitter=Mock()
        report=audit_once('postgresql://private-sentinel@db/a',
            pool_factory=pool_factory,inspect=Mock(return_value=summary),
            emit=emitter)
        self.assertEqual(report['database_bytes'],100_000)
        self.assertEqual(report['sampled_shadow_event_kinds'][0]['sampled_rows'],100)
        kwargs=pool_factory.call_args.kwargs
        self.assertEqual(kwargs['max_size'],1)
        self.assertIn('default_transaction_read_only=on',kwargs['kwargs']['options'])
        self.assertIn('statement_timeout=3500',CONNECTION_OPTIONS)
        statements=[c.args[0] for c in conn.execute.call_args_list]
        self.assertEqual(statements,['SET LOCAL statement_timeout=3500',EVENT_SAMPLE_SQL])
        self.assertNotIn('private-sentinel',emitter.call_args.args[0])
        self.assertEqual(json.loads(emitter.call_args.args[0])['mode'],'read_only')

    def test_connection_errors_are_type_only_and_do_not_expose_secrets(self):
        emitter=Mock()
        report=audit_once('postgresql://private-sentinel@db/a',
            pool_factory=Mock(side_effect=RuntimeError('private-sentinel')),
            inspect=Mock(),emit=emitter)
        self.assertEqual(report['connection_error_type'],'RuntimeError')
        self.assertNotIn('private-sentinel',emitter.call_args.args[0])

    def test_disabled_worker_audits_once_then_does_not_start_collection(self):
        settings=self.settings()
        env=dict(MT_STORAGE_RECOVERY_AUDIT='true',MT_STORAGE_RECOVERY_HOLD='true')
        with patch.dict(runtime.os.environ,env,clear=True),\
             patch('services.research.recovery_storage_audit.audit_once') as audit,\
             patch.object(runtime.R2Objects,'connect') as r2,\
             patch.object(runtime,'ConnectionPool') as pool:
            stop=Event()
            stop.set()
            runtime.run(settings,stop)
            audit.assert_called_once_with(settings.database_url)
            r2.assert_not_called()
            pool.assert_not_called()


if __name__=='__main__':
    unittest.main()

"""Emergency backup scope inspection is bounded and never mutates DB."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.demo.control_backup_capacity_audit import (
    MAX_PER_SCOPE, PREFIX_SCOPES, SINGLETONS, SINGLETON_QUERY,
    CONNECTION_OPTIONS, prefix_query, is_authorized, sample_rows,
    inspect_control_backup, audit_once
)

class ControlBackupAuditTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(role='collector',enabled=False,acceptance='off',operator_action='off')

    def env(self):
        return dict(MT_CONTROL_BACKUP_AUDIT='true',MT_STORAGE_RECOVERY_HOLD='true',
                    MT_ARCHIVE_VERIFY_ONCE='false',MT_ARCHIVE_RECOVERY_LOOP='false')

    def test_disabled_collector_only_and_fail_closed(self):
        self.assertFalse(is_authorized({},self.settings()))
        self.assertTrue(is_authorized(self.env(),self.settings()))
        for override in (dict(MT_STORAGE_RECOVERY_HOLD='false'),
                         dict(MT_ARCHIVE_RECOVERY_LOOP='true'),
                         dict(MT_ARCHIVE_VERIFY_ONCE='true')):
            with self.assertRaises(ValueError):
                is_authorized(dict(self.env(),**override),self.settings())
        for settings in (SimpleNamespace(role='demo',enabled=False,acceptance='off',operator_action='off'),
                         SimpleNamespace(role='collector',enabled=True,acceptance='off',operator_action='off'),
                         SimpleNamespace(role='collector',enabled=False,acceptance='r2-v1',operator_action='off')):
            with self.assertRaises(ValueError):is_authorized(self.env(),settings)

    def pool(self,rows=None,errors=None):
        pool=MagicMock()
        conn=pool.connection.return_value.__enter__.return_value
        errors=errors or []
        def exec_sql(sql,params):
            self.assertTrue(sql.strip().startswith('SELECT '))
            self.assertTrue('LIMIT %s' in sql)
            self.assertNotIn('DELETE FROM',sql)
            self.assertNotIn('UPDATE research_job',sql)
            if errors:raise errors.pop(0)
            cursor=MagicMock()
            cursor.fetchall.return_value=list(rows or [])
            return cursor
        conn.execute.side_effect=exec_sql
        return pool,conn

    def test_all_original_backup_control_scopes_included(self):
        prefixes={p for _,p,_ in PREFIX_SCOPES}
        for required in ('demo/bot/','demo/order/','demo/shadow/folder/',
                         'demo/shadow/bot/','demo/paper/resting/',
                         'demo/paper/position/','demo/paper/order/',
                         'live/bot/','live/order/','live/write/','live/onboarding-op/'):
            self.assertIn(required,prefixes)
        self.assertIn('demo/shadow/checkpoint',SINGLETONS)
        self.assertIn('demo/paper/cash',SINGLETONS)
        self.assertIn('live/risk',SINGLETONS)
        self.assertIn('live/account',SINGLETONS)
        self.assertIn('default_transaction_read_only=on',CONNECTION_OPTIONS)
        self.assertIn('ORDER BY idempotency_key LIMIT %s',prefix_query(None))
        with self.assertRaises(ValueError):prefix_query("status='unsafe'")

    def test_scope_count_and_bytes_are_lower_bounds_when_capped(self):
        row=dict(parameter_bytes=100,progress_bytes=300)
        pool,c=self.pool(rows=[row]*MAX_PER_SCOPE)
        result=sample_rows(pool,prefix_query(None),('live/write/','live/write/zzzz',MAX_PER_SCOPE))
        self.assertTrue(result['truncated'])
        self.assertEqual(result['rows_seen'],MAX_PER_SCOPE)
        self.assertEqual(result['payload_bytes_lower_bound'],MAX_PER_SCOPE*400)
        self.assertEqual(c.execute.call_args.args[1][-1],MAX_PER_SCOPE)

    def test_complete_and_truncated_reporting(self):
        rows=[dict(parameter_bytes=5,progress_bytes=12)]
        pool,c=self.pool(rows=rows)
        report=inspect_control_backup(pool)
        self.assertTrue(report['candidate_count_exact'])
        self.assertFalse(report['exceeds_legacy_2000_record_cap'])
        self.assertEqual(report['total_rows_lower_bound'],len(PREFIX_SCOPES)+1)
        self.assertEqual(report['payload_bytes_lower_bound'],17*(len(PREFIX_SCOPES)+1))
        self.assertEqual(c.execute.call_count,len(PREFIX_SCOPES)+1)
        pool,_=self.pool(rows=rows*MAX_PER_SCOPE)
        report=inspect_control_backup(pool)
        self.assertFalse(report['candidate_count_exact'])
        self.assertTrue(report['legacy_query_would_fail_on_count'])

    def test_failed_prefix_returns_safe_error_class_without_aborting_others(self):
        pool,_=self.pool(rows=[dict(parameter_bytes=3,progress_bytes=4)],
                         errors=[TimeoutError('secret-uri-password')])
        report=inspect_control_backup(pool)
        self.assertEqual(len(report['failed_scopes']),1)
        self.assertEqual(report['failed_scopes'][0]['error_type'],'TimeoutError')
        self.assertNotIn('password',json.dumps(report))
        self.assertFalse(report['candidate_count_exact'])

    def test_connection_forced_read_only_and_safe_error_response(self):
        pool,_=self.pool(rows=[])
        factory=MagicMock()
        factory.return_value.__enter__.return_value=pool
        logs=[]
        report=audit_once('postgresql://secret',pool_factory=factory,
                emit=lambda message,**kwargs:logs.append(json.loads(message)))
        self.assertTrue(report['verified'])
        self.assertTrue(report['candidate_count_exact'])
        self.assertIn('default_transaction_read_only=on',
                      factory.call_args.kwargs['kwargs']['options'])
        self.assertNotIn('secret',json.dumps(logs))
        failed=[]
        broken=MagicMock(side_effect=RuntimeError('password=secret'))
        report=audit_once('postgresql://secret',pool_factory=broken,
                          emit=lambda message,**kwargs:failed.append(message))
        self.assertFalse(report['verified'])
        self.assertEqual(report['error_type'],'RuntimeError')
        self.assertNotIn('password',failed[0])

if __name__=='__main__':
    unittest.main()

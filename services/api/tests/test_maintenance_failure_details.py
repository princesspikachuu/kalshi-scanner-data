"""Backup diagnostics identify safe failure classes, never exception details.

The active worker writes original_records_retained=True on failure and must
not mark an incomplete R2 backup as verified.
"""
import json
import unittest
from unittest.mock import MagicMock,patch

from services.demo.maintenance import (backup_freshness_status,report_backup_freshness,
                                       failure_details,maintenance)


class BackupFailureDetailsTests(unittest.TestCase):
    def test_known_multipart_failure_codes(self):
        cases = {
            'Control backup index upper boundary hides rows': 'control_scope_boundary',
            'Control backup snapshot capacity exceeded': 'control_snapshot_capacity',
            'Single control record exceeds safe archive size': 'control_record_capacity',
            'Insufficient temporary disk headroom for control backup': 'backup_disk_headroom',
            'Spool size budget exceeded; no partial backup published': 'backup_spool_capacity',
            'No controls found; refusing empty recovery backup': 'backup_no_controls',
            'Incomplete local control backup spool': 'backup_spool_invalid',
            'Invalid control backup chunk reference': 'backup_manifest_invalid',
            'Control backup root digest or count mismatch': 'backup_manifest_mismatch',
            'R2 backup restore verification mismatch': 'backup_manifest_mismatch',
        }
        for message, code in cases.items():
            with self.subTest(message=message):
                fields = failure_details(ValueError(message), 'backup')
                self.assertEqual(fields['reason_code'], code)
                self.assertEqual(fields['error_type'], 'ValueError')
                self.assertEqual(fields['stage'], 'backup')
                self.assertNotIn('error', fields)
                self.assertNotIn(message, json.dumps(fields))

    def test_legacy_classifications_still_work(self):
        self.assertEqual(failure_details(ValueError('Backup chunk capacity reached'), 'backup')['reason_code'], 'backup_capacity')
        self.assertEqual(failure_details(ValueError('Archive verification failed'), 'archive')['reason_code'], 'checksum_mismatch')

    def test_unrecognized_error_text_cannot_leak_credentials(self):
        secret = 'postgresql://user:private-password@private-db.example/pocket_staging'
        output = failure_details(ValueError('Archive problem at ' + secret), 'backup')
        self.assertEqual(output, dict(stage='backup', error_type='ValueError', reason_code='operation_failed'))
        self.assertNotIn(secret, json.dumps(output))

    def test_allowlisted_provider_code_and_http_status_but_not_secret_response(self):
        class ProviderError(Exception):
            response = {
                'ResponseMetadata': {'HTTPStatusCode': 403},
                'Error': {'Code': 'AccessDenied', 'Message': 'secret data'},
            }
        output = failure_details(ProviderError('credentials are secret'), 'backup')
        self.assertEqual(output['reason_code'], 'operation_failed')
        self.assertEqual(output['http_status'], 403)
        self.assertEqual(output['provider_code'], 'AccessDenied')
        self.assertNotIn('secret', json.dumps(output))

    def test_sqlstate_is_reported_without_sql_or_sensitive_error_message(self):
        class DatabaseError(Exception):
            sqlstate = '57014'
        output = failure_details(DatabaseError('SELECT password FROM private_table'), 'backup')
        self.assertEqual(output['sqlstate'], '57014')
        self.assertNotIn('private_table', json.dumps(output))



class BackupFreshnessTests(unittest.TestCase):
    NOW = 2_000_000.0

    @staticmethod
    def receipt(at,verified=True):
        return dict(progress=dict(at=at,verified=verified,
                                  reference={'key':'demo/backups/private-secret'}))

    def test_fresh_then_overdue_at_configured_threshold(self):
        for hours in (1,24,168):
            with self.subTest(hours=hours):
                fresh=backup_freshness_status(
                    self.receipt(self.NOW-hours*3600+60),hours,self.NOW)
                self.assertEqual(fresh['state'],'fresh')
                self.assertEqual(fresh['age_minutes'],hours*60-1)
                self.assertTrue(fresh['recorded_verified'])
                self.assertFalse(fresh['r2_rechecked'])
                overdue=backup_freshness_status(
                    self.receipt(self.NOW-hours*3600),hours,self.NOW)
                self.assertEqual(overdue['state'],'overdue')
                self.assertEqual(overdue['age_minutes'],hours*60)

    def test_missing_unverified_malformed_and_future_receipts_are_not_fresh(self):
        cases=((None,'missing'),(self.receipt(self.NOW-10,False),'unverified'),
               (self.receipt(True),'unverified'),
               (self.receipt(float('nan')),'unverified'),
               (self.receipt(float('inf')),'unverified'),
               (self.receipt(self.NOW+1),'unverified'),
               (self.receipt(10**2000),'unverified'),
               ({'progress':{'verified':True,'at':'private secret'}},'unverified'),
               ({'progress':[]},'unverified'))
        for receipt,state in cases:
            with self.subTest(receipt_type=type(receipt).__name__,state=state):
                status=backup_freshness_status(receipt,24,self.NOW)
                self.assertEqual(status['state'],state)
                self.assertFalse(status['recorded_verified'])
                self.assertIsNone(status['age_minutes'])
                self.assertNotIn('private',json.dumps(status))

    def test_freshness_reporting_deduplicates_via_store_alert_key(self):
        store=MagicMock()
        store.get.return_value=self.receipt(self.NOW-25*3600)
        with patch('builtins.print') as emit:
            status=report_backup_freshness(store,24,self.NOW)
        self.assertEqual(status['state'],'overdue')
        args=store.alert.call_args.args
        self.assertEqual(args[0],'backup-freshness')
        self.assertIn('Regular High-Probability Favorites',args[1])
        self.assertIs(args[2],True)
        store.clear_alert.assert_not_called()
        logged=json.loads(emit.call_args.args[0])
        self.assertEqual(logged['event'],'demo_backup_freshness')
        self.assertEqual(logged['state'],'overdue')
        self.assertFalse(logged['r2_rechecked'])
        self.assertNotIn('private-secret',json.dumps(logged))

        store.reset_mock()
        store.get.return_value=self.receipt(self.NOW-3600)
        with patch('builtins.print'):
            result=report_backup_freshness(store,24,self.NOW)
        self.assertEqual(result['state'],'fresh')
        store.clear_alert.assert_called_once_with('backup-freshness')
        store.alert.assert_not_called()

    def test_freshness_alert_survives_r2_connection_failure(self):
        # The online Favorites paper maintenance path must keep the alert
        # independent of object-store construction or backup attempt outcome.
        store=MagicMock()
        store.get.side_effect=lambda key:{
            'policy':None,'storage-health':None,
            'backup-health':self.receipt(self.NOW-50*3600),
        }.get(key)
        connection=store.pool.connection.return_value.__enter__.return_value

        def execute(sql,*args):
            cursor=MagicMock()
            cursor.fetchone.return_value=(
                {'size':500_000} if 'pg_database_size(' in sql else
                {'numbackends':1,'xact_commit':1,'xact_rollback':0,
                 'blks_read':0,'blks_hit':1,'temp_bytes':0,'deadlocks':0})
            cursor.fetchall.return_value=[]
            return cursor
        connection.execute.side_effect=execute
        with patch('services.demo.maintenance.object_store',
                   side_effect=RuntimeError('private R2 connection details')),patch(
             'services.demo.maintenance.emails'),patch(
             'services.demo.maintenance.time.time',return_value=self.NOW),patch(
             'builtins.print') as emit:
            maintenance(store,{},MagicMock())
        alerts=[call.args[0] for call in store.alert.call_args_list]
        self.assertIn('backup',alerts)
        self.assertIn('backup-freshness',alerts)
        emitted=' '.join(call.args[0] for call in emit.call_args_list)
        self.assertIn('"event": "demo_backup_freshness"',emitted)
        self.assertIn('"state": "overdue"',emitted)
        self.assertNotIn('private R2 connection details',emitted)
        # Existing generic failure alert must not be cleared by freshness
        # reporting, and no backup data or R2 objects may be mutated here.
        cleared=[call.args[0] for call in store.clear_alert.call_args_list]
        self.assertNotIn('backup',cleared)
        store.put.assert_called()


if __name__ == '__main__':
    unittest.main()

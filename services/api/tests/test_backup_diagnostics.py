"""Backup failures stay actionable without disclosing SDK/SQL credentials."""
import contextlib
import io
import json
import unittest
from unittest.mock import Mock,MagicMock,patch
from services.demo.maintenance import failure_details,maintenance,archive_events

class BackupDiagnosticsTests(unittest.TestCase):
    def test_known_capacity_reason_and_provider_status_are_safe(self):
        self.assertEqual(failure_details(ValueError('Backup chunk capacity reached'),'backup')['reason_code'],'backup_capacity')
        error=RuntimeError('https://secret-user:secret-password@private-host')
        error.response={'ResponseMetadata':{'HTTPStatusCode':403},'Error':{'Code':'AccessDenied','Message':'secret-key'}}
        data=failure_details(error,'archive')
        self.assertEqual(data['http_status'],403);self.assertEqual(data['provider_code'],'AccessDenied')
        self.assertNotIn('secret',json.dumps(data))

    def test_unrecognized_provider_text_and_sql_text_are_not_logged(self):
        error=RuntimeError('secret-password');error.sqlstate='42501'
        error.response={'ResponseMetadata':{'HTTPStatusCode':'secret'},'Error':{'Code':'secret-key'}}
        data=failure_details(error,'backup')
        self.assertEqual(data['sqlstate'],'42501')
        self.assertNotIn('provider_code',data);self.assertNotIn('http_status',data)
        self.assertNotIn('secret',json.dumps(data))

    def test_maintenance_reports_failed_stage_and_retains_originals(self):
        store=Mock();store.pool=MagicMock();store.get.return_value=None
        store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'size':1000}
        objects=Mock();output=io.StringIO()
        with patch('services.demo.maintenance.object_store',return_value=objects),\
             patch('services.demo.maintenance.archive_events'),\
             patch('services.demo.maintenance.restore_requests'),\
             patch('services.demo.maintenance.backup',side_effect=ValueError('Backup chunk capacity reached')),\
             patch('services.demo.maintenance.emails'),contextlib.redirect_stdout(output):
            maintenance(store,{},Mock())
        event=json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(event['stage'],'backup');self.assertEqual(event['reason_code'],'backup_capacity')
        self.assertTrue(event['original_records_retained']);objects.client.close.assert_called_once()
        store.clear_alert.assert_called_once_with('storage')

    def test_archive_failure_does_not_suppress_control_backup(self):
        store=Mock();store.pool=MagicMock();store.get.return_value=None
        store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'size':1000}
        with patch('services.demo.maintenance.object_store',return_value=Mock()),\
             patch('services.demo.maintenance.archive_events',side_effect=RuntimeError('private SQL text')),\
             patch('services.demo.maintenance.restore_requests'),\
             patch('services.demo.maintenance.backup') as backup,\
             patch('services.demo.maintenance.emails'),contextlib.redirect_stdout(io.StringIO()):
            maintenance(store,{'MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED':'true'},Mock())
        backup.assert_called_once();store.alert.assert_called_once()

    def test_failed_object_verification_cannot_advance_archive_cursor(self):
        from datetime import datetime,timezone
        dt=datetime(2000,1,1,tzinfo=timezone.utc)
        store=Mock();store.pool=MagicMock();store.get.return_value=None
        store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchall.return_value=[
            dict(id='11111111-1111-1111-1111-111111111111',
                 idempotency_key='demo/shadow/event/11111111-1111-1111-1111-111111111111',
                 asset='crypto',status='succeeded',parameters={},
                 progress=dict(event='FAVORITE_STAT_DECISION'),
                 created_at=dt,started_at=None,finished_at=dt,
                 lease_expires_at=None,attempts=0,error_code=None,
                 available_at=dt,max_attempts=5,lease_token=None)]
        with patch('services.demo.maintenance.put_verified',
                   side_effect=ValueError('Archive verification failed')):
            with self.assertRaises(ValueError):
                archive_events(store,Mock(),{'archive_days':7},False)
        store.put.assert_not_called()


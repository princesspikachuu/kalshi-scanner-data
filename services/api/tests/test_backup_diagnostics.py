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
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        failures=[event for event in events if event.get('event')=='demo_backup_verification_failed']
        self.assertEqual(len(failures),1)
        failure=failures[0]
        self.assertEqual(failure['stage'],'backup');self.assertEqual(failure['reason_code'],'backup_capacity')
        self.assertTrue(failure['original_records_retained']);objects.client.close.assert_called_once()
        freshness=[event for event in events if event.get('event')=='demo_backup_freshness']
        self.assertEqual(len(freshness),1)
        self.assertEqual(freshness[0]['state'],'missing')
        self.assertFalse(freshness[0]['r2_rechecked'])
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
        backup.assert_called_once()
        self.assertEqual([call.args[0] for call in store.alert.call_args_list],
                         ['backup','backup-freshness'])

    def test_opt_in_reuse_is_gated_by_read_only_bucket_lifecycle(self):
        # Even an operator who opts in to reuse cannot bypass confirmed
        # completed-object retention safety. All fallback paths still back
        # up the full source with the existing immutable R2 writer.
        scenarios=(
            ('no_expiry',{'Rules':[dict(Status='Enabled',Filter={},
                AbortIncompleteMultipartUpload={'DaysAfterInitiation':7})]},True),
            ('unrelated_expiry',{'Rules':[dict(Status='Enabled',
                Filter={'Prefix':'unrelated/'},Expiration={'Days':1})]},True),
            ('backup_expiry',{'Rules':[dict(Status='Enabled',
                Filter={'Prefix':'demo/backups/'},Expiration={'Days':1})]},False),
            ('unparseable',{'Rules':None},False),
        )
        for label,response,safe in scenarios:
            with self.subTest(label=label):
                store=Mock();store.pool=MagicMock();store.get.return_value=None
                store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'size':1000}
                objects=Mock()
                objects.client.get_bucket_lifecycle_configuration.return_value=response
                output=io.StringIO()
                with patch('services.demo.maintenance.object_store',return_value=objects),\
                     patch('services.demo.maintenance.restore_requests'),\
                     patch('services.demo.control_backup_v2.backup_controls') as backup,\
                     patch('services.demo.maintenance.emails'),contextlib.redirect_stdout(output):
                    maintenance(store,dict(MT_CONTROL_BACKUP_V2_ENABLED='true',
                        MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED='true'),Mock())
                objects.client.get_bucket_lifecycle_configuration.assert_called_once_with(
                    Bucket=objects.bucket)
                if safe:
                    backup.assert_called_once_with(store,objects,reuse_previous=True)
                else:
                    backup.assert_called_once_with(store,objects)
                events=[json.loads(line) for line in output.getvalue().splitlines()]
                blocked=[e for e in events if
                         e.get('event')=='demo_backup_reuse_lifecycle_blocked']
                self.assertEqual(len(blocked),int(not safe))
                if blocked:
                    self.assertEqual(blocked[0]['fallback'],
                                     'independent_complete_backup')
                objects.client.close.assert_called_once()

    def test_denied_lifecycle_and_default_disabled_never_reuse(self):
        for flag in ('false','true'):
            with self.subTest(flag=flag):
                store=Mock();store.pool=MagicMock();store.get.return_value=None
                store.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'size':1000}
                objects=Mock()
                objects.client.get_bucket_lifecycle_configuration.side_effect=RuntimeError(
                    'secret: private credential must never be printed')
                output=io.StringIO()
                with patch('services.demo.maintenance.object_store',return_value=objects),\
                     patch('services.demo.maintenance.restore_requests'),\
                     patch('services.demo.control_backup_v2.backup_controls') as backup,\
                     patch('services.demo.maintenance.emails'),contextlib.redirect_stdout(output):
                    maintenance(store,dict(MT_CONTROL_BACKUP_V2_ENABLED='true',
                        MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED=flag),Mock())
                backup.assert_called_once_with(store,objects)
                self.assertEqual(
                    objects.client.get_bucket_lifecycle_configuration.call_count,
                    int(flag=='true'))
                self.assertNotIn('private credential',output.getvalue())
                self.assertNotIn('secret:',output.getvalue())

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


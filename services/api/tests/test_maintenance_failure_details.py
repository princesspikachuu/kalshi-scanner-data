"""Backup diagnostics identify safe failure classes, never exception details.

The active worker writes original_records_retained=True on failure and must
not mark an incomplete R2 backup as verified.
"""
import json
import unittest

from services.demo.maintenance import failure_details


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


if __name__ == '__main__':
    unittest.main()

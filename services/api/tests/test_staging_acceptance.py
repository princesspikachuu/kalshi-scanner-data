"""Acceptance probes never collect, mutate DB data, or expose provider diagnostics."""
from io import StringIO
import unittest
from unittest.mock import Mock, patch
from services.research import acceptance
from test_archives import MemoryObjects
from test_worker_runtime import environment


class AcceptanceTests(unittest.TestCase):
    def test_fixed_probe_reuses_one_immutable_marker(self):
        objects = MemoryObjects()
        first = acceptance.probe_r2(objects)
        second = acceptance.probe_r2(objects)
        self.assertTrue(first['verified']); self.assertTrue(first['created'])
        self.assertFalse(second['created']); self.assertEqual(first['object_key'], second['object_key'])
        self.assertLess(first['compressed_bytes'], 1024)

    def test_corrupt_read_and_broken_precondition_fail(self):
        for broken_read in [True, False]:
            objects = Mock()
            objects.put_if_absent.return_value = True
            if broken_read: objects.get.return_value = b'wrong'
            else: objects.get.return_value = acceptance.prepare(acceptance.PROBE_PROVIDER, acceptance.PROBE_PAYLOAD).body
            with self.assertRaises(ValueError): acceptance.probe_r2(objects)

    def test_write_is_opt_in_and_enabled_collection_blocks_both_actions(self):
        with patch.object(acceptance.R2Objects, 'connect') as connect, patch.object(acceptance, 'audit_database') as audit:
            with patch('sys.stderr', new_callable=StringIO):
                with self.assertRaises(SystemExit): acceptance.main(['r2'])
                with patch.dict(acceptance.os.environ, {'COLLECTION_ENABLED':'true'}, clear=True):
                    self.assertEqual(acceptance.main(['r2','--write-r2-probe']),1)
                    self.assertEqual(acceptance.main(['database']),1)
            connect.assert_not_called(); audit.assert_not_called()

    def test_r2_path_has_no_database_or_collector_and_closes_after_failure(self):
        objects = Mock(); objects.put_if_absent.side_effect = RuntimeError('private-sentinel')
        with patch.dict(acceptance.os.environ, environment(), clear=True), \
             patch.object(acceptance.R2Objects,'connect',return_value=objects), \
             patch.object(acceptance.psycopg,'connect') as database, \
             patch('sys.stderr',new_callable=StringIO) as errors:
            self.assertEqual(acceptance.main(['r2','--write-r2-probe']),1)
            database.assert_not_called(); objects.client.close.assert_called_once()
            self.assertNotIn('sentinel',errors.getvalue())

    def test_operator_audit_is_failure_status_without_printing_connection_values(self):
        with patch.dict(acceptance.os.environ, environment(), clear=True), \
             patch.object(acceptance,'audit_database',return_value={'privilege_boundary_ready':False}), \
             patch('sys.stdout',new_callable=StringIO) as output:
            self.assertEqual(acceptance.main(['database']),3)
            self.assertNotIn('sentinel',output.getvalue())

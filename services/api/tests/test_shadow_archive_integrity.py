"""Read-only R2 archive integrity check has no mutation or credential leakage."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.demo.shadow_archive_integrity import (
    CONNECTION_OPTIONS, MANIFEST_QUERY, SOURCE_QUERY,
    audit_once, inspect, is_authorized
)


class ShadowArchiveIntegrityTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(role='collector', enabled=False,
                               acceptance='off', operator_action='off')

    def env(self):
        return dict(MT_ARCHIVE_VERIFY_ONCE='true',
                    MT_STORAGE_RECOVERY_HOLD='true',
                    MT_ARCHIVE_RECOVERY_LOOP='false')

    def manifest(self, kind):
        raw = kind == 'shadow_event_r2_manifest'
        record_id = '11111111-1111-1111-1111-111111111111'
        progress = dict(format='shadow-r2-event-batch-v1' if raw else
                        'shadow-diagnostic-r2-manifest-v1',
                        reference=dict(key='demo/events/test.json.gz', size=42,
                                       sha256='a'*64), count=1)
        if raw:
            progress['ids'] = [record_id]
        else:
            progress.update(row_ids=[record_id], original_events=2)
        return dict(parameters=dict(kind=kind), progress=progress,
                    id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    idempotency_key='demo/shadow/archive-manifest/'+record_id)

    def pool(self, manifests, still_live=None):
        pool = MagicMock()
        c = pool.connection.return_value.__enter__.return_value

        def execute(sql, args=None):
            cursor = MagicMock()
            if sql == MANIFEST_QUERY:
                cursor.fetchall.return_value = manifests
            elif sql == SOURCE_QUERY:
                cursor.fetchone.return_value = still_live
            else:
                raise AssertionError('Unexpected or mutating query')
            return cursor

        c.execute.side_effect = execute
        return pool, c

    def test_only_explicit_recovery_held_disabled_collector_can_verify(self):
        self.assertFalse(is_authorized({}, self.settings()))
        self.assertTrue(is_authorized(self.env(), self.settings()))
        for update in (dict(MT_STORAGE_RECOVERY_HOLD='false'),
                       dict(MT_ARCHIVE_RECOVERY_LOOP='true')):
            with self.assertRaises(ValueError):
                is_authorized(dict(self.env(), **update), self.settings())
        for value in (dict(role='demo'), dict(enabled=True),
                      dict(acceptance='r2-v1'), dict(operator_action='prepare-roles-v1')):
            with self.assertRaises(ValueError):
                is_authorized(self.env(), SimpleNamespace(**dict(
                    dict(role='collector', enabled=False, acceptance='off',
                         operator_action='off'), **value)))

    def test_verified_manifest_and_raw_rows_absent(self):
        manifest = self.manifest('shadow_event_r2_manifest')
        pool, c = self.pool([manifest])
        record_id = manifest['progress']['ids'][0]
        with patch('services.demo.shadow_archive_integrity.verify_archived_manifest',
                   return_value=[dict(id=record_id)]) as verifier, patch(
                   'services.demo.shadow_archive_integrity.verify_batch_manifest') as other:
            report = inspect(pool, MagicMock())
        verifier.assert_called_once()
        other.assert_not_called()
        self.assertEqual(report['verified_manifests'], 1)
        self.assertEqual(report['deleted_rows_absent'], 1)
        self.assertEqual(report['original_events_verified'], 1)
        self.assertEqual(report['compressed_bytes_verified'], 42)
        self.assertEqual([call.args[0] for call in c.execute.call_args_list],
                         [MANIFEST_QUERY, SOURCE_QUERY])

    def test_verified_packed_event_ids_survive(self):
        manifest = self.manifest('diagnostic_batch_r2_manifest')
        pool, _ = self.pool([manifest])
        with patch('services.demo.shadow_archive_integrity.verify_batch_manifest',
                   return_value=[dict(id=manifest['progress']['row_ids'][0])]):
            report = inspect(pool, MagicMock())
        self.assertEqual(report['original_rows_verified'], 1)
        self.assertEqual(report['original_events_verified'], 2)

    def test_row_still_present_or_manifest_mismatch_fails_closed(self):
        manifest = self.manifest('shadow_event_r2_manifest')
        row = dict(id=manifest['progress']['ids'][0])
        pool, _ = self.pool([manifest], still_live=row)
        with patch('services.demo.shadow_archive_integrity.verify_archived_manifest',
                   return_value=[row]):
            with self.assertRaisesRegex(ValueError, 'still present'):
                inspect(pool, MagicMock())
        pool, _ = self.pool([manifest])
        with patch('services.demo.shadow_archive_integrity.verify_archived_manifest',
                   return_value=[dict(id='other')]):
            with self.assertRaisesRegex(ValueError, 'identities'):
                inspect(pool, MagicMock())

    def test_read_only_connection_one_shot_and_redacted_failure(self):
        pool, _ = self.pool([self.manifest('shadow_event_r2_manifest')])
        factory = MagicMock()
        factory.return_value.__enter__.return_value = pool
        objects = MagicMock()
        out = []
        with patch('services.demo.shadow_archive_integrity.verify_archived_manifest',
                   return_value=[dict(id='11111111-1111-1111-1111-111111111111')]):
            result = audit_once('postgresql://private-url', {}, pool_factory=factory,
                                store_factory=lambda _: objects,
                                emit=lambda s, **kwargs: out.append(json.loads(s)))
        self.assertTrue(result['verified'])
        self.assertTrue(result['no_deletion'])
        self.assertEqual(out[0]['deleted_rows_absent'], 1)
        self.assertIn('default_transaction_read_only=on',
                      factory.call_args.kwargs['kwargs']['options'])
        objects.client.close.assert_called_once()
        self.assertNotIn('private-url', json.dumps(out))
        failed = []
        with patch('services.demo.shadow_archive_integrity.verify_archived_manifest',
                   side_effect=RuntimeError('private-secret-url')):
            result = audit_once('postgresql://private-url', {}, pool_factory=factory,
                                store_factory=lambda _: MagicMock(),
                                emit=lambda s, **kwargs: failed.append(s))
        self.assertFalse(result['verified'])
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertNotIn('private-secret-url', failed[0])

    def test_empty_manifest_sample_is_not_reported_verified(self):
        pool, _ = self.pool([])
        factory = MagicMock()
        factory.return_value.__enter__.return_value = pool
        result = audit_once('postgresql://private-url', {}, pool_factory=factory,
                            store_factory=lambda _: MagicMock(),
                            emit=lambda *a, **k: None)
        self.assertFalse(result['verified'])
        self.assertEqual(result['reason'], 'no_archive_manifests_found')


if __name__ == '__main__':
    unittest.main()

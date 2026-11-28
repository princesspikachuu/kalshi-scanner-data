"""Disposable PostgreSQL tests: no silent high-key omissions in control backups.

The backup paths remain read-only. No external R2 calls are made.
"""
import unittest
from unittest.mock import patch

from services.api.tests import test_demo_postgres as fixture
from services.demo.control_backup_v2 import (
    SELECT_PREFIX, collect_snapshot, collect_snapshot_spooled, assert_no_hidden_control_tail,
)
from services.demo.control_backup_capacity_audit import PREFIX_SCOPES, census_shadow_bots


@unittest.skipUnless(fixture.URL, 'Disposable pocket_test PostgreSQL required')
class RealPostgresControlBackupTailTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_unusual_live_control_key_refuses_both_snapshot_paths(self):
        key='demo/shadow/bot/zzzzzz-legacy'
        self.demo.put('shadow/bot/zzzzzz-legacy',dict(event='CONTROL',status='resting'))
        # This previously appeared to be a complete empty snapshot because
        # the key sorts after the hard-coded end of the indexed window.
        with self.assertRaisesRegex(ValueError,'upper boundary'):
            collect_snapshot(self.store.pool)
        with self.assertRaisesRegex(ValueError,'upper boundary'):
            collect_snapshot_spooled(self.store.pool)
        with self.store.pool.connection() as conn:
            row=conn.execute(
                'SELECT idempotency_key FROM research_job WHERE idempotency_key=%s',
                (key,)).fetchone()
        self.assertEqual(row['idempotency_key'],key)

    def test_normal_control_snapshot_still_works(self):
        key='demo/shadow/bot/0001'
        self.demo.put('shadow/bot/0001',dict(event='CONTROL',status='resting'))
        captured=collect_snapshot(self.store.pool)
        self.assertIn(key,[row['idempotency_key'] for row in captured])
        staged=collect_snapshot_spooled(self.store.pool)
        try:
            self.assertGreater(staged['records'],0)
            self.assertGreater(staged['parts'],0)
        finally:
            staged['file'].close()

    def test_backup_scope_never_includes_neighboring_history(self):
        import json

        control = 'shadow/bot/valid'
        history = 'shadow/bot-performance-history/000000000001'
        self.demo.put(control, dict(desired='paused'))
        self.demo.put(history, dict(snapshot='untouched'))

        # Put the neighboring row inside the index range even under a
        # byte-order test database. Locale-sensitive production ranges can
        # include it without this expansion.
        wide_range = SELECT_PREFIX.replace('<%s', "<replace(%s, '/bot/zzzz', '/botz')")
        with patch('services.demo.control_backup_v2.SELECT_PREFIX', wide_range):
            captured = collect_snapshot(self.store.pool)
            self.assertEqual([row['idempotency_key'] for row in captured], ['demo/'+control])
            staged = collect_snapshot_spooled(self.store.pool)
        with staged['file'] as file:
            size = int.from_bytes(file.read(4), 'big')
            part = json.loads(file.read(size))
            self.assertEqual([row['idempotency_key'] for row in part['records']], ['demo/'+control])
            self.assertEqual(staged['records'], 1)
        self.assertEqual(census_shadow_bots(self.store.pool)['rows'], 1)
        self.assertEqual(self.demo.get(history)['progress'], dict(snapshot='untouched'))

    def test_every_control_prefix_keeps_high_suffix_inside_probe(self):
        # A word successor must enclose all suffixes, even where English
        # punctuation ordering differs from byte order (slash vs '0').
        for _,prefix,_ in PREFIX_SCOPES:
            for suffix in ('zzzz','zzzzzz-legacy','zzzz\u00e9'):
                with self.subTest(prefix=prefix,suffix=suffix):
                    key=prefix+suffix
                    from services.demo.store import DemoStore
                    writer=DemoStore(self.store.pool)
                    writer.namespace=key.split('/',1)[0]
                    writer.put(key.split('/',1)[1],dict(event='CONTROL'))
                    with self.store.pool.connection() as c:
                        try:
                            with self.assertRaisesRegex(ValueError,'upper boundary'):
                                assert_no_hidden_control_tail(c)
                        finally:
                            c.execute('DELETE FROM research_job WHERE idempotency_key=%s',(key,))


if __name__=='__main__':
    unittest.main()

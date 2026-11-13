"""Disposable PostgreSQL tests: no silent high-key omissions in control backups.

The backup paths remain read-only. No external R2 calls are made.
"""
import unittest

from services.api.tests import test_demo_postgres as fixture
from services.demo.control_backup_v2 import (
    collect_snapshot, collect_snapshot_spooled,
)


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


if __name__=='__main__':
    unittest.main()

"""MT-019 indexed namespace upper/lower boundary regression tests.

Only disposable pocket_test PostgreSQL is used by the database tests.
"""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.demo.shadow_prefix_boundary_guard import (
    ALLOWED_PREFIXES, EXACT_PREFIX_SQL, ABOVE_UPPER_SQL,
    assert_no_hidden_prefix_keys,
)
from services.demo.shadow_history_pages import RAW_PREFIX
from services.demo.shadow_archive_reader import PREFIX as MANIFEST_PREFIX
from services.demo.shadow_snapshot_index_scan import scan_postgres_index_snapshot
from services.demo.shadow_snapshot_window import read_postgres_snapshot_window
from services.demo.shadow_manifest_namespace_inventory import (
    audit_manifest_namespace_snapshot,
)


class PrefixBoundaryGuardUnitTests(unittest.TestCase):
    def test_disallow_unknown_duplicate_or_empty_prefix_before_query(self):
        connection = MagicMock()
        for keys in ([], ['arbitrary/'], [RAW_PREFIX, RAW_PREFIX],
                     [RAW_PREFIX]*4, 'not-a-prefix', [None]):
            with self.subTest(keys=keys):
                with self.assertRaises(ValueError):
                    assert_no_hidden_prefix_keys(connection, keys)
        connection.execute.assert_not_called()

    def test_no_matches_performs_only_two_exist_checks_per_prefix(self):
        connection = MagicMock()
        empty = MagicMock()
        empty.fetchone.return_value = None
        connection.execute.return_value = empty
        self.assertTrue(assert_no_hidden_prefix_keys(connection, [RAW_PREFIX]))
        self.assertEqual(
            [x.args[0] for x in connection.execute.call_args_list],
            [EXACT_PREFIX_SQL, ABOVE_UPPER_SQL])
        self.assertEqual(connection.execute.call_args_list[0].args[1],
                         (RAW_PREFIX,))
        self.assertEqual(connection.execute.call_args_list[1].args[1],
                         (RAW_PREFIX+'zzzz',RAW_PREFIX+'%'))

    def test_prefix_alone_is_hidden_and_refused(self):
        connection = MagicMock()
        found = MagicMock()
        found.fetchone.return_value = {'present': 1}
        connection.execute.return_value = found
        with self.assertRaisesRegex(ValueError, 'Bare index prefix'):
            assert_no_hidden_prefix_keys(connection, [RAW_PREFIX])
        self.assertEqual(connection.execute.call_count, 1)

    def test_prefix_outside_zzzz_refused(self):
        connection = MagicMock()
        no_match = MagicMock()
        no_match.fetchone.return_value = None
        found = MagicMock()
        found.fetchone.return_value = {'present': 1}
        connection.execute.side_effect = [no_match, found]
        with self.assertRaisesRegex(ValueError, 'Out-of-range'):
            assert_no_hidden_prefix_keys(connection, [MANIFEST_PREFIX])
        self.assertEqual(connection.execute.call_count, 2)


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL, 'Disposable PostgreSQL pocket_test required')
class RealDisposablePrefixBoundaryGuard(unittest.TestCase):
    setUp = fixture.DemoPostgres.setUp
    tearDown = fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def _insert(self, key, *, kind='shadow_event_r2_manifest'):
        from psycopg.types.json import Jsonb
        with self.store.pool.connection() as conn:
            conn.execute("""INSERT INTO research_job
                (id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                (str(uuid4()), Jsonb({'kind':kind}),
                 Jsonb({'format':'shadow-r2-event-batch-v1',
                        'event':'FAVORITE_STAT_DECISION'}), key))

    def test_raw_upper_outlier_blocks_two_offline_index_claims(self):
        # Both older scans would silently omit this source row because of
        # their "idempotency_key < prefix + 'zzzz'" window constraint.
        key = RAW_PREFIX+'zzzzzzzz'
        self._insert(key)
        with self.assertRaisesRegex(ValueError,'Out-of-range'):
            scan_postgres_index_snapshot(self.store.pool)
        with self.assertRaisesRegex(ValueError,'Out-of-range'):
            read_postgres_snapshot_window(self.store.pool)
        with self.store.pool.connection() as conn:
            still_here = conn.execute(
                'SELECT 1 AS found FROM research_job WHERE idempotency_key=%s',
                (key,)).fetchone()
        self.assertIsNotNone(still_here)

    def test_manifest_bare_prefix_not_mistaken_for_empty_history(self):
        key = MANIFEST_PREFIX
        self._insert(key)
        with self.assertRaisesRegex(ValueError, 'Bare index prefix'):
            audit_manifest_namespace_snapshot(self.store.pool)
        with self.assertRaisesRegex(ValueError, 'Bare index prefix'):
            scan_postgres_index_snapshot(self.store.pool)
        with self.store.pool.connection() as conn:
            still_here = conn.execute(
                'SELECT 1 AS found FROM research_job WHERE idempotency_key=%s',
                (key,)).fetchone()
        self.assertIsNotNone(still_here)

    def test_legacy_manifest_upper_outlier_cannot_hide_from_inventory(self):
        key = MANIFEST_PREFIX+'zzzzzz-legacy'
        self._insert(key)
        with self.assertRaisesRegex(ValueError, 'Out-of-range'):
            audit_manifest_namespace_snapshot(self.store.pool,page_size=1)
        with self.store.pool.connection() as conn:
            count = conn.execute(
                'SELECT COUNT(*) AS n FROM research_job WHERE idempotency_key=%s',
                (key,)).fetchone()['n']
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()

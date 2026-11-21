"""One-snapshot bounded SQL index scan tests (disposable PostgreSQL only)."""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.demo.shadow_snapshot_index_scan import scan_postgres_index_snapshot
from services.demo.shadow_snapshot_window import KEY_SQL, MANIFEST_KEYS_SQL
from services.demo.shadow_prefix_boundary_guard import EXACT_PREFIX_SQL, ABOVE_UPPER_SQL


class SnapshotIndexScanUnitTests(unittest.TestCase):
    def test_reject_invalid_limits_without_database_access(self):
        pool = MagicMock()
        for args in (
            dict(page_size=0), dict(page_size=True), dict(page_size=33),
            dict(max_pages_per_source=0), dict(max_pages_per_source=9),
            dict(max_total_keys=0), dict(max_total_keys=513),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    scan_postgres_index_snapshot(pool, **args)
        pool.connection.assert_not_called()

    def test_empty_snapshot_is_read_only_and_not_global_history(self):
        pool = MagicMock()
        connection = pool.connection.return_value.__enter__.return_value
        snapshot = MagicMock()
        snapshot.fetchone.return_value = {'snapshot': '12:18:'}
        empty = MagicMock()
        empty.fetchall.return_value = []
        no_match = MagicMock()
        no_match.fetchone.return_value = None
        connection.execute.side_effect = [
            MagicMock(), MagicMock(), snapshot, empty, empty, empty,
            *([no_match] * 6),
        ]
        audit = scan_postgres_index_snapshot(pool)
        self.assertTrue(audit['indexed_namespaces_fully_scanned_in_this_snapshot'])
        self.assertEqual(audit['total_indexed_source_rows'], 0)
        self.assertEqual(audit['transaction_snapshot'], '12:18:')
        self.assertFalse(audit['all_time_coverage_complete'])
        self.assertFalse(audit['safe_to_restart_writers'])
        self.assertTrue(audit['bounded_prefix_key_boundaries_verified'])
        commands = [call.args[0] for call in connection.execute.call_args_list]
        self.assertEqual(commands, [
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY',
            'SET LOCAL statement_timeout=5000',
            'SELECT txid_current_snapshot()::text AS snapshot',
            KEY_SQL, KEY_SQL, MANIFEST_KEYS_SQL,
            EXACT_PREFIX_SQL, ABOVE_UPPER_SQL,
            EXACT_PREFIX_SQL, ABOVE_UPPER_SQL,
            EXACT_PREFIX_SQL, ABOVE_UPPER_SQL,
        ])
        for call in connection.execute.call_args_list[3:6]:
            self.assertIn('idempotency_key LIKE %s', call.args[0])
            self.assertEqual(call.args[1][-1], 17)

    def test_bad_lookahead_key_is_rejected_before_receipt(self):
        pool = MagicMock()
        c = pool.connection.return_value.__enter__.return_value
        marker = MagicMock()
        marker.fetchone.return_value = {'snapshot': '1:2:'}
        result = MagicMock()
        result.fetchall.return_value = [
            {'idempotency_key': 'demo/shadow/event/0001'},
            {'idempotency_key': 'demo/shadow/event-batch/incorrect'},
        ]
        c.execute.side_effect = [MagicMock(), MagicMock(), marker, result]
        with self.assertRaises(ValueError):
            scan_postgres_index_snapshot(pool, page_size=1)

    def test_page_budget_refuses_unterminated_source(self):
        pool = MagicMock()
        c = pool.connection.return_value.__enter__.return_value
        marker = MagicMock()
        marker.fetchone.return_value = {'snapshot': '1:2:'}
        result = MagicMock()
        result.fetchall.return_value = [
            {'idempotency_key': 'demo/shadow/event/0001'},
            {'idempotency_key': 'demo/shadow/event/0002'},
        ]
        c.execute.side_effect = [MagicMock(), MagicMock(), marker, result]
        with self.assertRaisesRegex(ValueError, 'pagination budget'):
            scan_postgres_index_snapshot(
                pool, page_size=1, max_pages_per_source=1)

    def test_unordered_or_missing_snapshot_marker_fails(self):
        pool = MagicMock()
        c = pool.connection.return_value.__enter__.return_value
        missing = MagicMock()
        missing.fetchone.return_value = {'snapshot': ''}
        c.execute.side_effect = [MagicMock(), MagicMock(), missing]
        with self.assertRaisesRegex(ValueError, 'transaction snapshot'):
            scan_postgres_index_snapshot(pool)
        c.execute.reset_mock(side_effect=True)
        marker = MagicMock()
        marker.fetchone.return_value = {'snapshot': '1:2:'}
        result = MagicMock()
        result.fetchall.return_value = [
            {'idempotency_key': 'demo/shadow/event/0002'},
            {'idempotency_key': 'demo/shadow/event/0001'},
        ]
        c.execute.side_effect = [MagicMock(), MagicMock(), marker, result]
        with self.assertRaisesRegex(ValueError, 'Unsorted'):
            scan_postgres_index_snapshot(pool)


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL, 'Disposable pocket_test database required')
class ActualPostgresOneSnapshotIndexScan(unittest.TestCase):
    setUp = fixture.DemoPostgres.setUp
    tearDown = fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_three_sql_namespaces_multiple_pages_one_snapshot_no_writes(self):
        from psycopg.types.json import Jsonb
        from services.paper_demo.shadow.storage import UPSERT, entry
        from services.paper_demo.shadow.diagnostic_batches import compact_diagnostic_rows

        raw_ids = [
            self.demo.put('shadow/event/' + f'{n:04d}',
                          dict(event='SETTLED' if n == 4
                               else 'FAVORITE_STAT_DECISION',
                               time=100+n, fee_cents=3+n))
            for n in range(5)
        ]
        diagnostics = [
            entry('demo/shadow/event/'+str(uuid4()),
                  dict(series='KXTEST'),
                  dict(event='FAVORITE_STAT_DECISION', time=200+n))
            for n in range(2)
        ]
        packed = compact_diagnostic_rows(diagnostics, entry)
        self.assertEqual(len(packed), 1)
        with self.store.pool.connection() as c:
            c.execute(UPSERT, packed[0])
            manifest_id = str(uuid4())
            c.execute("""INSERT INTO research_job
                (id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                (manifest_id,
                 Jsonb({'kind':'shadow_event_r2_manifest'}),
                 Jsonb({'format':'shadow-r2-event-batch-v1','count':2}),
                 'demo/shadow/archive-manifest/'+manifest_id))
        first = scan_postgres_index_snapshot(self.store.pool, page_size=2)
        second = scan_postgres_index_snapshot(self.store.pool, page_size=4)
        self.assertEqual(first['source_keysets']['raw']['indexed_source_rows'],5)
        self.assertEqual(first['source_keysets']['raw']['keyset_pages'],3)
        self.assertEqual(first['source_keysets']['packed']['indexed_source_rows'],1)
        self.assertEqual(first['source_keysets']['manifests']['indexed_source_rows'],1)
        self.assertEqual(first['total_indexed_source_rows'],7)
        self.assertEqual(
            {source: first['source_keysets'][source]['index_key_digest']
             for source in ('raw','packed','manifests')},
            {source: second['source_keysets'][source]['index_key_digest']
             for source in ('raw','packed','manifests')})
        for flag in ('all_time_coverage_complete','safe_to_train',
                     'safe_to_restart_writers','archived_originals_verified',
                     'source_exhaustion_verified'):
            self.assertFalse(first[flag])
        with self.store.pool.connection() as c:
            count=c.execute("""SELECT count(*) AS n FROM research_job
                WHERE idempotency_key LIKE 'demo/shadow/event/%'""").fetchone()['n']
        self.assertEqual(count,len(raw_ids))

    def test_tiny_budget_fails_closed_on_real_postgres(self):
        for n in range(5):
            self.demo.put('shadow/event/'+f'{n:04d}',
                          dict(event='FAVORITE_STAT_DECISION',time=n))
        with self.assertRaises(ValueError):
            scan_postgres_index_snapshot(self.store.pool,
                                         page_size=2,max_pages_per_source=2)
        with self.assertRaises(ValueError):
            scan_postgres_index_snapshot(self.store.pool,
                                         page_size=2,max_total_keys=3)


if __name__ == '__main__':
    unittest.main()

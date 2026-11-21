"""Tests of full manifest namespace inventory, using disposable PG only."""
import unittest
from uuid import uuid4
from unittest.mock import MagicMock

from services.demo.shadow_manifest_namespace_inventory import (
    audit_manifest_namespace_snapshot, NAMESPACE_SQL,
)
from services.demo.shadow_prefix_boundary_guard import EXACT_PREFIX_SQL, ABOVE_UPPER_SQL


def archive_row(*, kind='shadow_event_r2_manifest',
                fmt='shadow-r2-event-batch-v1', status='succeeded',
                key=None, identifier=None):
    identifier = identifier or str(uuid4())
    key = key or 'demo/shadow/archive-manifest/' + identifier
    return dict(id=identifier,idempotency_key=key,
                status=status,parameters=dict(kind=kind),
                progress=dict(format=fmt,count=1),
                created_at=None)


def mocked(rows):
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    snapshot = MagicMock()
    snapshot.fetchone.return_value = {'snapshot':'100:104:'}
    selected = MagicMock()
    selected.fetchall.return_value = rows
    no_match=MagicMock()
    no_match.fetchone.return_value=None
    connection.execute.side_effect = [
        MagicMock(),MagicMock(),snapshot,selected,no_match,no_match]
    return pool,connection


class ManifestNamespaceInventoryUnitTests(unittest.TestCase):
    def test_bounded_options_fail_before_connection(self):
        pool=MagicMock()
        for kwargs in (
            dict(page_size=0),dict(page_size=26),dict(page_size=True),
            dict(max_pages=9),dict(max_pages=0),
            dict(max_keys=201),dict(max_keys=True),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    audit_manifest_namespace_snapshot(pool,**kwargs)
        pool.connection.assert_not_called()

    def test_empty_snapshot_does_not_claim_all_time_history(self):
        pool,c=mocked([])
        result=audit_manifest_namespace_snapshot(pool)
        self.assertTrue(result['full_prefix_keyset_terminal_in_one_snapshot'])
        self.assertEqual(result['namespace_rows'],0)
        self.assertEqual(result['unrecognized_or_unsafe_rows'],0)
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertFalse(result['safe_to_restart_writers'])
        self.assertTrue(result['bounded_prefix_key_boundaries_verified'])
        calls=[call.args[0] for call in c.execute.call_args_list]
        self.assertEqual(calls,[
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY',
            'SET LOCAL statement_timeout=5000',
            'SELECT txid_current_snapshot()::text AS snapshot',
            NAMESPACE_SQL,EXACT_PREFIX_SQL,ABOVE_UPPER_SQL,
        ])
        self.assertEqual(c.execute.call_args_list[3].args[1][-1],17)

    def test_invalid_manifest_records_are_reported_not_dropped(self):
        good=archive_row()
        missing=archive_row(kind='mystery')
        nonterminal=archive_row(status='failed')
        keybad=archive_row(key='demo/shadow/archive-manifest/not-a-uuid')
        rows=sorted([good,missing,nonterminal,keybad],
                    key=lambda row:row['idempotency_key'])
        pool,_=mocked(rows)
        result=audit_manifest_namespace_snapshot(pool)
        self.assertEqual(result['namespace_rows'],4)
        self.assertEqual(result['recognized_manifest_rows'],1)
        self.assertEqual(result['unrecognized_or_unsafe_rows'],3)
        self.assertTrue(result['recognized_only_query_may_hide_rows'])
        self.assertEqual(result['unrecognized_classification_counts'],{
            'invalid_manifest_metadata':1,
            'not_succeeded':1,
            'unrecognized_manifest_kind':1,
        })
        self.assertTrue(all('index_key_sha256' in example
                            and 'idempotency_key' not in example
                            for example in result['anomaly_examples']))
        self.assertFalse(result['r2_manifest_readback_verified'])

    def test_invalid_lookahead_or_unordered_rows_fail_closed(self):
        ok=archive_row()
        neighbor=archive_row(key='demo/shadow/other/'+str(uuid4()))
        pool,_=mocked([ok,neighbor])
        with self.assertRaisesRegex(ValueError,'Out-of-range'):
            audit_manifest_namespace_snapshot(pool,page_size=1)
        first,second=archive_row(),archive_row()
        unsorted=sorted([first,second],
                        key=lambda row:row['idempotency_key'],reverse=True)
        pool,_=mocked(unsorted)
        with self.assertRaisesRegex(ValueError,'Unsorted'):
            audit_manifest_namespace_snapshot(pool)

    def test_missing_terminal_page_and_total_budget_fail(self):
        rows=sorted([archive_row(),archive_row()],
                    key=lambda row:row['idempotency_key'])
        pool,_=mocked(rows)
        with self.assertRaisesRegex(ValueError,'page budget'):
            audit_manifest_namespace_snapshot(pool,page_size=1,max_pages=1)
        pool,_=mocked(rows)
        with self.assertRaisesRegex(ValueError,'key budget'):
            audit_manifest_namespace_snapshot(pool,page_size=2,max_keys=1)

    def test_fingerprint_deterministic_for_same_verified_inventory(self):
        rows=sorted([archive_row(),archive_row(kind='unknown')],
                    key=lambda row:row['idempotency_key'])
        first,_=mocked(rows)
        second,_=mocked(rows)
        a=audit_manifest_namespace_snapshot(first)
        b=audit_manifest_namespace_snapshot(second)
        self.assertEqual(a['full_prefix_key_digest'],b['full_prefix_key_digest'])
        self.assertEqual(a['classified_key_digest'],b['classified_key_digest'])


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL, 'Only disposable pocket_test PostgreSQL allowed')
class RealPostgresManifestNamespaceInventory(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_unknown_same_namespace_row_is_retained_and_inventoried(self):
        from psycopg.types.json import Jsonb
        from services.demo.shadow_snapshot_index_scan import scan_postgres_index_snapshot

        genuine=archive_row()
        unknown=archive_row(kind='unrecognized_legacy_manifest')
        with self.store.pool.connection() as c:
            for row in (genuine,unknown):
                c.execute("""INSERT INTO research_job
                    (id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                    (row['id'],Jsonb(row['parameters']),Jsonb(row['progress']),
                     row['idempotency_key']))
        filtered=scan_postgres_index_snapshot(self.store.pool,page_size=1)
        self.assertEqual(
            filtered['source_keysets']['manifests']['indexed_source_rows'],1)
        inventory=audit_manifest_namespace_snapshot(self.store.pool,page_size=1)
        self.assertEqual(inventory['namespace_rows'],2)
        self.assertEqual(inventory['recognized_manifest_rows'],1)
        self.assertEqual(inventory['unrecognized_or_unsafe_rows'],1)
        self.assertTrue(inventory['recognized_only_query_may_hide_rows'])
        with self.store.pool.connection() as c:
            count=c.execute("""SELECT COUNT(*) AS n FROM research_job
                WHERE idempotency_key LIKE 'demo/shadow/archive-manifest/%'
            """).fetchone()['n']
        self.assertEqual(count,2)

    def test_unknown_format_stays_visible_across_page_boundaries(self):
        from psycopg.types.json import Jsonb
        rows=[archive_row(),archive_row(fmt='old-unknown-format'),
              archive_row()]
        with self.store.pool.connection() as c:
            for row in rows:
                c.execute("""INSERT INTO research_job
                    (id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                    (row['id'],Jsonb(row['parameters']),Jsonb(row['progress']),
                     row['idempotency_key']))
        first=audit_manifest_namespace_snapshot(self.store.pool,page_size=1)
        second=audit_manifest_namespace_snapshot(self.store.pool,page_size=3)
        self.assertEqual(first['namespace_rows'],3)
        self.assertEqual(first['recognized_manifest_rows'],2)
        self.assertEqual(first['unrecognized_classification_counts'],
                         {'unrecognized_manifest_format':1})
        self.assertEqual(first['full_prefix_key_digest'],
                         second['full_prefix_key_digest'])
        self.assertEqual(first['classified_key_digest'],
                         second['classified_key_digest'])


if __name__=='__main__':
    unittest.main()

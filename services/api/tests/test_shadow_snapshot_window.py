"""Snapshot checks are SQL read-only and never global completeness proof."""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.demo.shadow_snapshot_window import (
    read_postgres_snapshot_window,KEY_SQL,MANIFEST_KEYS_SQL,
    SOURCE_PREFIXES,
)


class SnapshotWindowUnitTests(unittest.TestCase):
    def test_read_only_single_transaction_and_window_budget(self):
        pool=MagicMock()
        connection=pool.connection.return_value.__enter__.return_value
        snapshot=MagicMock()
        snapshot.fetchone.return_value={'snapshot':'101:107:'}
        empty=MagicMock()
        empty.fetchall.return_value=[]
        connection.execute.side_effect=[MagicMock(),MagicMock(),snapshot,
                                        empty,empty,empty]
        out=read_postgres_snapshot_window(pool,page_size=4)
        self.assertTrue(out['postgres_source_window_consistent'])
        self.assertEqual(out['isolation'],'repeatable_read_read_only')
        self.assertTrue(out['indexed_namespaces_fully_scanned_in_this_snapshot'])
        self.assertFalse(out['all_time_coverage_complete'])
        self.assertFalse(out['safe_to_train'])
        self.assertEqual(connection.execute.call_count,6)
        sqlcalls=[call.args[0] for call in connection.execute.call_args_list]
        self.assertEqual(sqlcalls[0],
                         'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        self.assertEqual(sqlcalls[1],'SET LOCAL statement_timeout=5000')
        self.assertEqual(sqlcalls[2],'SELECT txid_current_snapshot()::text AS snapshot')
        self.assertEqual(sqlcalls[3],KEY_SQL)
        self.assertEqual(sqlcalls[4],KEY_SQL)
        self.assertEqual(sqlcalls[5],MANIFEST_KEYS_SQL)
        for call in connection.execute.call_args_list[3:]:
            self.assertEqual(call.args[1][-1],5)

    def test_partial_windows_can_never_claim_entire_namespace(self):
        pool=MagicMock()
        connection=pool.connection.return_value.__enter__.return_value
        snap=MagicMock()
        snap.fetchone.return_value={'snapshot':'1:2:'}
        rows=MagicMock()
        rows.fetchall.return_value=[
            {'idempotency_key':'demo/shadow/event/0001'},
            {'idempotency_key':'demo/shadow/event/0002'}]
        empty=MagicMock()
        empty.fetchall.return_value=[]
        connection.execute.side_effect=[MagicMock(),MagicMock(),snap,rows,empty,empty]
        result=read_postgres_snapshot_window(pool,page_size=1)
        self.assertTrue(result['windows']['raw']['more'])
        self.assertEqual(result['windows']['raw']['next_cursor'],
                         'demo/shadow/event/0001')
        self.assertFalse(result['indexed_namespaces_fully_scanned_in_this_snapshot'])
        self.assertFalse(result['source_exhaustion_verified'])

    def test_bad_inputs_refused_without_sql(self):
        pool=MagicMock()
        for params in (
            dict(page_size=0),dict(page_size=33),dict(page_size=True),
            dict(cursors={'garbage':'x'}),dict(cursors={'raw':'../foo'}),
            dict(cursors={'manifests':'demo/shadow/archive-manifest/not-a-uuid'}),
        ):
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    read_postgres_snapshot_window(pool,**params)
        pool.connection.assert_not_called()

    def test_tampered_result_order_refused(self):
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        snap=MagicMock()
        snap.fetchone.return_value={'snapshot':'1:2:'}
        invalid=MagicMock()
        invalid.fetchall.return_value=[
            {'idempotency_key':'demo/shadow/event/0002'},
            {'idempotency_key':'demo/shadow/event/0001'}]
        c.execute.side_effect=[MagicMock(),MagicMock(),snap,invalid]
        with self.assertRaisesRegex(ValueError,'Unsorted'):
            read_postgres_snapshot_window(pool)


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class LiveDisposableSnapshotWindow(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_consistent_bounded_key_windows_do_not_change_rows(self):
        for number in range(5):
            self.demo.put('shadow/event/'+f'{number:04d}',
                          {'event':'FAVORITE_STAT_DECISION','time':number})
        result=read_postgres_snapshot_window(self.store.pool,page_size=4)
        raw=result['windows']['raw']
        self.assertEqual(raw['rows_in_window'],4)
        self.assertTrue(raw['more'])
        self.assertEqual(raw['next_cursor'],'demo/shadow/event/0003')
        self.assertEqual(result['isolation'],'repeatable_read_read_only')
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertFalse(result['safe_to_restart_writers'])
        next_window=read_postgres_snapshot_window(
            self.store.pool,page_size=4,cursors={'raw':raw['next_cursor']})
        self.assertEqual(next_window['windows']['raw']['rows_in_window'],1)
        self.assertFalse(next_window['windows']['raw']['more'])
        # Separate snapshot calls are explicitly not presented as globally
        # exhaustive even when the last page was reached.
        self.assertFalse(next_window['indexed_namespaces_fully_scanned_in_this_snapshot'])
        with self.store.pool.connection() as c:
            count=c.execute("""SELECT count(*) AS n FROM research_job WHERE
                idempotency_key>'demo/shadow/event/'
                AND idempotency_key<'demo/shadow/event/zzzz'""").fetchone()['n']
        self.assertEqual(count,5)


if __name__=='__main__':
    unittest.main()

"""Read-only logical PostgreSQL storage diagnostics (no production I/O)."""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.demo.shadow_pg_storage_footprint import (
    inspect_readonly_pg_footprint, DATABASE_SQL, RELATIONS_SQL,
)


def fake_pool(info, rows):
    pool=MagicMock()
    connection=pool.connection.return_value.__enter__.return_value
    db_result=MagicMock()
    db_result.fetchone.return_value=info
    relations_result=MagicMock()
    relations_result.fetchall.return_value=rows
    connection.execute.side_effect=[
        MagicMock(),MagicMock(),MagicMock(),db_result,relations_result
    ]
    return pool,connection


def relation(name='research_job', size=1000, dead=0):
    return dict(relation_name=name,total_bytes=size,heap_bytes=size//2,
                index_bytes=size//4,estimated_live_tuples=5,
                estimated_dead_tuples=dead)


class ReadonlyStorageFootprintUnitTests(unittest.TestCase):
    def test_invalid_limits_rejected_before_sql(self):
        pool=MagicMock()
        for arg in (0,True,1.0,13,-1,'10',None):
            with self.subTest(arg=arg):
                with self.assertRaises(ValueError):
                    inspect_readonly_pg_footprint(pool,top_relations=arg)
        pool.connection.assert_not_called()

    def test_sql_uses_read_only_transaction_and_bounded_catalog(self):
        pool,c=fake_pool(dict(database_name='pocket_test',
                              database_bytes=1024000),
                         [relation()])
        report=inspect_readonly_pg_footprint(pool,top_relations=1)
        self.assertEqual(report['database_bytes'],1024000)
        self.assertEqual(report['top_public_relations'][0]['relation_name'],
                         'research_job')
        self.assertEqual(report['relations_reported'],1)
        self.assertTrue(report['transaction_read_only'])
        self.assertEqual([call.args[0] for call in c.execute.call_args_list],[
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY',
            'SET LOCAL statement_timeout=5000',
            'SET LOCAL lock_timeout=1000',DATABASE_SQL,RELATIONS_SQL])
        self.assertEqual(c.execute.call_args_list[-1].args[1],(1,))
        self.assertNotIn('DELETE',RELATIONS_SQL.upper())
        self.assertNotIn('OFFSET',RELATIONS_SQL.upper())
        for flag in (
            'actual_physical_disk_headroom_verified',
            'actual_wal_headroom_verified',
            'reclaimable_bytes_estimated',
            'all_time_coverage_complete',
            'safe_to_archive_or_delete',
            'safe_to_restart_writers','safe_to_train'):
            self.assertFalse(report[flag])
        self.assertIsNone(report['wal_directory_bytes'])
        self.assertIsNone(report['render_physical_disk_free_bytes'])

    def test_bad_database_size_and_relation_data_fail_closed(self):
        bad_infos=[
            dict(database_name='pocket_test',database_bytes=-1),
            dict(database_name='pocket_test',database_bytes='123'),
            dict(database_name='',database_bytes=1),
        ]
        for info in bad_infos:
            with self.subTest(info=info):
                pool,_=fake_pool(info,[])
                with self.assertRaises(ValueError):
                    inspect_readonly_pg_footprint(pool)
        for rows in (
            [relation(size=-5)],
            [relation(name='')],
            [relation(dead=-1)],
            [relation(),relation(name='other',size=2000)],
        ):
            with self.subTest(rows=rows):
                pool,_=fake_pool(
                    dict(database_name='pocket_test',database_bytes=3000),
                    rows)
                with self.assertRaises(ValueError):
                    inspect_readonly_pg_footprint(pool)

    def test_empty_database_relations_not_mistaken_for_empty_disk(self):
        pool,_=fake_pool(dict(database_name='pocket_test',
                              database_bytes=32768),[])
        report=inspect_readonly_pg_footprint(pool,top_relations=2)
        self.assertEqual(report['relations_reported'],0)
        self.assertEqual(report['database_bytes'],32768)
        self.assertIsNone(report['render_physical_disk_used_bytes'])
        self.assertFalse(report['source_exhaustion_verified'])

    def test_dead_tuple_statistics_never_estimate_reclaimable_bytes(self):
        pool,_=fake_pool(dict(database_name='pocket_test',
                              database_bytes=1_000_000),
                         [relation(dead=100000)])
        out=inspect_readonly_pg_footprint(pool)
        self.assertEqual(out['top_public_relations'][0]['estimated_dead_tuples'],
                         100000)
        self.assertFalse(out['reclaimable_bytes_estimated'])
        self.assertFalse(out['safe_to_archive_or_delete'])


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL,'Only disposable pocket_test PostgreSQL allowed')
class RealDisposableStorageFootprint(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_real_pg_catalog_does_not_mutate_original_rows(self):
        ident=self.demo.put('shadow/event/'+str(uuid4()),
            dict(event='SETTLED',time=200,fee_cents=5),
            parameters={'series':'KXTEST'})
        with self.store.pool.connection() as c:
            before=c.execute('SELECT count(*) AS n FROM research_job').fetchone()['n']
        result=inspect_readonly_pg_footprint(self.store.pool,top_relations=12)
        self.assertEqual(result['database_name'],'pocket_test')
        self.assertGreater(result['database_bytes'],0)
        self.assertLessEqual(result['relations_reported'],12)
        self.assertTrue(all(
            isinstance(r['relation_name'],str) and r['total_bytes']>=0
            for r in result['top_public_relations']))
        self.assertFalse(result['actual_physical_disk_headroom_verified'])
        self.assertFalse(result['actual_wal_headroom_verified'])
        with self.store.pool.connection() as c:
            after=c.execute('SELECT count(*) AS n FROM research_job').fetchone()['n']
            retained=c.execute(
                'SELECT progress FROM research_job WHERE id=%s',(ident,)
            ).fetchone()
        self.assertEqual(before,after)
        self.assertEqual(retained['progress']['fee_cents'],5)


if __name__=='__main__':
    unittest.main()

"""A complete catalog must include controls beyond the former 800-row page."""
import unittest
import os
from uuid import uuid4
from unittest.mock import Mock
from services.paper_demo.shadow.bot_catalog import load_bots,BOT_LIMIT,BotCatalogCapacityError


class BotCatalogTests(unittest.TestCase):
    def test_over_800_keeps_tail_controls_and_every_saved_pause(self):
        rows=[dict(id=str(i),parameters=dict(id='bot-'+str(i)),
                   progress=dict(desired='paused' if i%2 else 'running')) for i in range(1001)]
        rows[-1]['parameters'].update(folder_id='favorites_statistics')
        store=Mock();store.bot_catalog.return_value=rows
        loaded=load_bots(store)
        self.assertEqual({r['id'] for r in loaded},{r['id'] for r in rows})
        self.assertEqual(len(loaded),1001)
        self.assertEqual(next(r for r in loaded if r['id']=='1000')['parameters']['folder_id'],'favorites_statistics')
        self.assertEqual(sum(r['progress']['desired']=='paused' for r in loaded),500)
        self.assertEqual(loaded,sorted(rows,key=lambda row:row['id'],reverse=True))
        store.bot_catalog.assert_called_once_with(BOT_LIMIT+1)

    def test_exact_capacity_and_empty_catalog_are_complete(self):
        store=Mock()
        for count in (0,BOT_LIMIT):
            store.bot_catalog.return_value=[dict(id=str(i)) for i in range(count)]
            self.assertEqual(len(load_bots(store)),count)

    def test_overflow_is_an_error_instead_of_a_partial_success(self):
        store=Mock();store.bot_catalog.return_value=[{} for _ in range(BOT_LIMIT+1)]
        with self.assertRaises(BotCatalogCapacityError):load_bots(store)

    def test_source_failure_never_becomes_an_empty_or_partial_catalog(self):
        store=Mock();store.bot_catalog.side_effect=RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):load_bots(store)


@unittest.skipUnless(os.environ.get('POCKET_TEST_DATABASE_URL'),'Requires disposable pocket_test PostgreSQL')
class BotCatalogPostgresTests(unittest.TestCase):
    def test_index_ordered_reader_returns_complete_controls_without_other_namespaces(self):
        from urllib.parse import urlparse
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from psycopg_pool import ConnectionPool
        from services.api.manage import migrate
        from services.demo.store import DemoStore
        url=os.environ['POCKET_TEST_DATABASE_URL']
        if urlparse(url).path!='/pocket_test':raise RuntimeError('Disposable pocket_test only')
        migrate(url);namespace='catalog-test-'+uuid4().hex
        records=[(uuid4(),namespace+'/shadow/bot/'+str(i),dict(id='bot-'+str(i)),
                  dict(desired='paused' if i%2 else 'running')) for i in range(1001)]
        records.append((uuid4(),namespace+'/unrelated',{},{}))
        try:
            with psycopg.connect(url) as c:
                with c.cursor() as cursor:
                    cursor.executemany("INSERT INTO research_job(id,asset,idempotency_key,parameters,progress,status) VALUES(%s,'crypto',%s,%s,%s,'succeeded')",
                                       [(ident,key,Jsonb(p),Jsonb(s)) for ident,key,p,s in records])
            with ConnectionPool(url,min_size=1,max_size=1,kwargs=dict(row_factory=dict_row)) as pool:
                store=DemoStore(pool);store.namespace=namespace
                rows=load_bots(store)
            self.assertEqual(len(rows),1001)
            self.assertEqual({r['id'] for r in rows},{str(r[0]) for r in records[:-1]})
            self.assertEqual([r['id'] for r in rows],sorted((str(r[0]) for r in records[:-1]),reverse=True))
            self.assertEqual(sum(r['progress']['desired']=='paused' for r in rows),500)
        finally:
            with psycopg.connect(url) as c:c.execute('DELETE FROM research_job WHERE id=ANY(%s::uuid[])',([r[0] for r in records],))

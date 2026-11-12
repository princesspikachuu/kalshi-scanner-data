"""Owner-accessible bounded hot and packed shadow history keyset pages.

Integration tests only mutate the explicitly disposable pocket_test database.
"""
import unittest
from uuid import uuid4

from unittest.mock import MagicMock, patch

from services.demo.shadow_history_pages import (
    RAW_PREFIX,PACKED_PREFIX,MAX_RAW_ROWS,MAX_PACKED_ROWS,
    RAW_SQL,PACKED_SQL,validate_cursor,page_history,
)
from services.demo.shadow_archive_reader import ArchiveReaderUnavailable
from services.demo.legacy_event_archive import FORMAT


class HistoryPageContractTests(unittest.TestCase):
    def test_source_and_cursor_are_strictly_bounded(self):
        self.assertEqual(validate_cursor('raw',None),RAW_PREFIX)
        self.assertEqual(validate_cursor('packed',None),PACKED_PREFIX)
        self.assertEqual(validate_cursor('raw',RAW_PREFIX+'one'),
                         RAW_PREFIX+'one')
        for source,cursor in (
            ('other',None),('raw','demo/order/x'),
            ('packed',RAW_PREFIX+'ab'),('raw',RAW_PREFIX+'../../secret'),
            ('raw',RAW_PREFIX+'bad/slash'),('raw','x'*300),
            ('packed',PACKED_PREFIX+'?weird'),('raw','demo/shadow/event-batch/x'),
        ):
            with self.subTest(source=source,cursor=cursor):
                with self.assertRaises(ValueError):
                    validate_cursor(source,cursor)

    def test_index_ordered_sql_uses_fixed_small_page_no_scan(self):
        self.assertEqual(MAX_RAW_ROWS,4)
        self.assertEqual(MAX_PACKED_ROWS,1)
        for sql in (RAW_SQL,PACKED_SQL):
            self.assertIn('idempotency_key>%s',sql)
            self.assertIn('idempotency_key<%s',sql)
            self.assertIn('ORDER BY idempotency_key LIMIT %s',sql)
            self.assertNotIn('count(*)',sql.lower())
            self.assertNotIn('offset',sql.lower())

    def test_hot_read_only_source_never_requests_r2_and_marks_scope(self):
        from datetime import datetime,timezone
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        row=dict(id=str(uuid4()),idempotency_key=RAW_PREFIX+'key',
                 parameters={},progress=dict(event='FAVORITE_STAT_DECISION',
                                             time=123,important='keep'),
                 created_at=datetime(2026,11,1,tzinfo=timezone.utc))
        c.execute.return_value.fetchall.return_value=[row]
        result=page_history(pool,'raw')
        self.assertEqual(result['items'][0]['progress']['important'],'keep')
        self.assertEqual(result['items'][0]['event_time'],123)
        self.assertFalse(result['more'])
        self.assertFalse(result['all_time_coverage_complete'])
        self.assertFalse(result['reclaimed_manifests_included'])
        self.assertEqual(result['archive_objects_verified'],0)
        self.assertEqual(result['source_keys'],[RAW_PREFIX+'key'])
        self.assertIsNone(result['request_cursor'])
        sqlcalls=[x.args for x in c.execute.call_args_list]
        self.assertEqual(sqlcalls[0][0],'SET LOCAL statement_timeout=5000')
        self.assertEqual(sqlcalls[1][0],RAW_SQL)
        self.assertEqual(sqlcalls[1][1][-1],5)


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class HostedShadowHistoryPages(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_raw_event_pages_cover_every_key_and_preserve_financial_history(self):
        originals={}
        for i in range(11):
            event='SETTLED' if i==7 else 'FAVORITE_STAT_DECISION'
            key='shadow/event/'+f'{i:04d}'
            ident=self.demo.put(key,dict(event=event,time=i,cash_cents=100+i),
                                parameters=dict(sample=i))
            originals[ident]='demo/'+key
        cursor=None;seen=[];prev_cursor=None;pages=0;page_chain=[];rolling=None
        while True:
            params={'cursor':cursor} if cursor else None
            response=self.client.get('/demo/shadow/history/raw',params=params)
            self.assertEqual(response.status_code,200,response.text)
            body=response.json();pages+=1
            self.assertEqual(body['request_cursor'],cursor)
            page_chain.append(body)
            from services.demo.shadow_keyset_receipts import extend_keyset_receipt
            rolling=extend_keyset_receipt(rolling,'raw',body)
            self.assertEqual(body['source'],'raw')
            self.assertFalse(body['all_time_coverage_complete'])
            self.assertFalse(body['reclaimed_manifests_included'])
            self.assertLessEqual(body['source_rows'],MAX_RAW_ROWS)
            self.assertEqual(body['source_rows'],body['original_events'])
            self.assertEqual(body['source_keys'],[item['key'] for item in body['items']])
            self.assertEqual(body['archive_objects_verified'],0)
            seen.extend(body['items'])
            if not body['more']:
                self.assertIsNone(body['next_cursor'])
                break
            self.assertTrue(body['next_cursor'].startswith(RAW_PREFIX))
            self.assertNotEqual(body['next_cursor'],prev_cursor)
            prev_cursor=cursor=body['next_cursor']
            self.assertLess(pages,8)
        self.assertEqual(pages,3)
        from services.demo.shadow_page_chain import verify_history_page_chain
        self.assertEqual(verify_history_page_chain(page_chain,'raw')['supplied_keys'],11)
        self.assertTrue(rolling['terminal'])
        self.assertEqual(rolling['source_rows'],11)
        self.assertEqual(rolling['original_events'],11)
        self.assertFalse(rolling['all_time_coverage_complete'])
        self.assertEqual({x['id'] for x in seen},set(originals))
        self.assertEqual(len(seen),len(originals))
        self.assertEqual([x['key'] for x in seen],sorted(originals.values()))
        self.assertIn('SETTLED',[x['progress']['event'] for x in seen])
        with self.store.pool.connection() as c:
            n=c.execute("""SELECT count(*) AS n FROM research_job WHERE
                idempotency_key>='demo/shadow/event/'
                AND idempotency_key<'demo/shadow/event/zzzz'""").fetchone()['n']
        self.assertEqual(n,len(originals))  # pagination never mutated source

    def test_packed_batches_recover_all_original_ids_without_double_counting(self):
        from services.paper_demo.shadow.storage import UPSERT,entry
        from services.paper_demo.shadow.diagnostic_batches import compact_diagnostic_rows
        originals=[]
        with self.store.pool.connection() as c:
            for b in range(3):
                raw=[]
                for i in range(2):
                    x=entry(RAW_PREFIX+str(uuid4()),dict(cohort=b),
                        dict(event='FAVORITE_STAT_DECISION',time=b*10+i,
                             original=f'b{b}-e{i}'))
                    originals.append(str(x[0]))
                    raw.append(x)
                packed=compact_diagnostic_rows(raw,entry)
                self.assertEqual(len(packed),1)
                c.execute(UPSERT,packed[0])
        cursor=None;seen=[];pages=0;page_chain=[];rolling=None
        while True:
            r=self.client.get('/demo/shadow/history/packed',
                              params={'cursor':cursor} if cursor else None)
            self.assertEqual(r.status_code,200,r.text)
            body=r.json();pages+=1
            page_chain.append(dict(body,request_cursor=cursor))
            from services.demo.shadow_keyset_receipts import extend_keyset_receipt
            rolling=extend_keyset_receipt(rolling,'packed',body)
            self.assertEqual(body['source_rows'],1)
            self.assertEqual(body['original_events'],2)
            self.assertEqual(len(body['source_keys']),1)
            self.assertEqual(body['source_keys'][0],body['items'][0]['packed_batch_key'])
            seen.extend(body['items'])
            if not body['more']:
                break
            self.assertIsInstance(body['next_cursor'],str)
            cursor=body['next_cursor']
            self.assertLess(pages,6)
        self.assertEqual(pages,3)
        from services.demo.shadow_page_chain import verify_history_page_chain
        self.assertEqual(verify_history_page_chain(page_chain,'packed')['supplied_keys'],3)
        self.assertTrue(rolling['terminal'])
        self.assertEqual(rolling['source_rows'],3)
        self.assertEqual(rolling['original_events'],6)
        self.assertFalse(rolling['safe_to_train'])
        self.assertEqual({x['id'] for x in seen},set(originals))
        self.assertEqual(len(seen),6)
        self.assertEqual({x['progress']['original'] for x in seen},
                         {f'b{b}-e{i}' for b in range(3) for i in range(2)})
        self.assertTrue(all(x['packed_batch_key'].startswith(PACKED_PREFIX)
                            for x in seen))

    def test_invalid_and_disabled_cold_cursors_fail_not_return_empty_history(self):
        receipt=dict(key='demo/events/'+'a'*64+'.json.gz',
                     sha256='a'*64,size=200)
        self.demo.put('shadow/event/0001',dict(archived=True,
                     archive_format=FORMAT,archive=receipt))
        self.assertEqual(self.client.get('/demo/shadow/history/raw').status_code,503)
        for path in ('/demo/shadow/history/unknown',
                     '/demo/shadow/history/raw?cursor=demo/order/one',
                     '/demo/shadow/history/raw?cursor=../etc/passwd',
                     '/demo/shadow/history/raw?extra=1',
                     '/demo/shadow/history/raw?cursor=a&cursor=b'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code,422)

    def test_owner_session_required_for_paginated_history(self):
        self.assertEqual(self.client.get('/demo/shadow/history/raw',
            headers={'x-pocket-proxy':'wrong'}).status_code,403)


if __name__ == '__main__':
    unittest.main()

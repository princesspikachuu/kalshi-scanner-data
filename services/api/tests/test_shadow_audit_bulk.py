"""Audit bulk SQL must retain each event in its original atomic write order."""
import unittest
from services.paper_demo.shadow.audit_bulk import ROW_SQL, persist_audit_rows


class CaptureCursor:
    def __init__(self):
        self.calls=[]
    def executemany(self,sql,rows):
        self.calls.append(('original',sql,[tuple(x) for x in rows]))
    def execute(self,sql,params):
        assert sql.count(ROW_SQL)<=64
        assert len(params)==4*sql.count(ROW_SQL)
        self.calls.append(('bulk',sql,[tuple(params[i:i+4])
                         for i in range(0,len(params),4)]))


class AuditBulkTests(unittest.TestCase):
    @staticmethod
    def row(i,kind='event'):
        key=('demo/shadow/event/' if kind=='event' else
             'demo/shadow/checkpoint/' if kind=='checkpoint' else
             'demo/shadow/report/')+str(i)
        return (f'uuid-{i}',dict(kind=kind),dict(detail='retain-'+str(i)),key)

    def test_grouped_statements_keep_all_rows_in_original_order(self):
        records=[self.row('check','checkpoint')]
        records.extend(self.row(i) for i in range(70))
        records.append(self.row('report','report'))
        records.extend(self.row(i) for i in range(70,79))
        cursor=CaptureCursor()
        report=persist_audit_rows(cursor,records,"ORIGINAL UPSERT")
        self.assertEqual(report['bulk_event_rows'],73)
        self.assertEqual(report['bulk_event_groups'],2)
        self.assertEqual(report['ordinary_upsert_rows'],8)
        flattened=[record for _,_,group in cursor.calls for record in group]
        self.assertEqual(flattened,records)
        self.assertEqual([name for name,_,_ in cursor.calls],
                         ['original','bulk','original','original','bulk'])
        self.assertTrue(all("ON CONFLICT(idempotency_key) DO UPDATE"
                            in sql for kind,sql,_ in cursor.calls if kind=='bulk'))

    def test_small_runs_use_exact_legacy_statement(self):
        records=[self.row('check','checkpoint')]
        records.extend(self.row(i) for i in range(7))
        cursor=CaptureCursor()
        report=persist_audit_rows(cursor,records,"ORIGINAL UPSERT")
        self.assertEqual(report['bulk_event_rows'],0)
        self.assertEqual(report['ordinary_upsert_rows'],8)
        self.assertEqual(len(cursor.calls),2)
        self.assertTrue(all(call[0]=='original' and call[1]=='ORIGINAL UPSERT'
                            for call in cursor.calls))
        self.assertEqual([row for _,_,chunk in cursor.calls for row in chunk],records)

    def test_event_chunk_bound_and_exact_event_details(self):
        records=[self.row(i) for i in range(192)]
        cursor=CaptureCursor()
        report=persist_audit_rows(cursor,records,"ORIGINAL UPSERT")
        self.assertEqual(report,dict(bulk_event_rows=192,bulk_event_groups=3,
                                     ordinary_upsert_rows=0))
        self.assertEqual([len(chunk) for _,_,chunk in cursor.calls],[64,64,64])
        self.assertEqual([row for _,_,chunk in cursor.calls for row in chunk],records)

    def test_repeated_key_falls_back_to_original_sequential_upsert(self):
        records=[self.row(i) for i in range(10)]
        # Preserve the historical last-row-wins behavior for an unexpected
        # duplicate idempotency key within one SQL chunk.
        repeated=list(records[4]);repeated[3]=records[2][3]
        records[4]=tuple(repeated)
        cursor=CaptureCursor()
        report=persist_audit_rows(cursor,records,'ORIGINAL UPSERT')
        self.assertEqual(report['bulk_event_rows'],0)
        self.assertEqual(report['ordinary_upsert_rows'],10)
        self.assertEqual(cursor.calls,[('original','ORIGINAL UPSERT',records)])

    def test_sql_failure_propagates_before_transaction_reports_success(self):
        class FailingCursor(CaptureCursor):
            def execute(self,sql,params):
                raise RuntimeError('simulated PostgreSQL failure')
        cursor=FailingCursor()
        with self.assertRaisesRegex(RuntimeError,'simulated PostgreSQL failure'):
            persist_audit_rows(cursor,[self.row(i) for i in range(15)],'UPSERT')

    def test_invalid_group_limits_are_rejected(self):
        for kwargs in ({'min_bulk':0},{'max_bulk':65},
                       {'min_bulk':9,'max_bulk':8}):
            with self.assertRaises(ValueError):
                persist_audit_rows(CaptureCursor(),[], 'UPSERT', **kwargs)


if __name__=='__main__':unittest.main()

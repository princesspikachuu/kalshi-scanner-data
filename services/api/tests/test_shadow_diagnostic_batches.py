"""Lossless diagnostic batching reduces row overhead, never trading evidence."""
import base64
import copy
import gzip
import hashlib
import json
import unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.paper_demo.shadow.storage import HostedAudit,entry
from services.paper_demo.shadow.diagnostic_batches import (
    BATCH_PREFIX,EVENT_PREFIX,MAX_EVENTS,compact_diagnostic_rows,
    decode_diagnostic_batch,merge_recent_events
)


class DiagnosticBatchTests(unittest.TestCase):
    def item(self,kind='FAVORITE_STAT_DECISION',index=1):
        return entry(EVENT_PREFIX+str(index),
                     dict(kind='EXPERIMENT',ticker='T'+str(index),time=float(index)),
                     dict(event=kind,time=float(index),details=dict(price=index,reason='evidence')))

    def compact(self,rows):
        return compact_diagnostic_rows(rows,entry)

    def test_original_uuid_parameters_and_evidence_survive_round_trip(self):
        original=[self.item(index=i) for i in range(2,27)]
        result=self.compact(original)
        self.assertEqual(len(result),1)
        self.assertTrue(result[0][3].startswith(BATCH_PREFIX))
        packed=result[0][2].obj
        self.assertEqual(packed['count'],25)
        decoded=decode_diagnostic_batch(packed)
        self.assertEqual([x['id'] for x in decoded],[str(r[0]) for r in original])
        self.assertEqual([x['key'] for x in decoded],[r[3] for r in original])
        self.assertEqual([x['parameters'] for x in decoded],[r[1].obj for r in original])
        self.assertEqual([x['progress'] for x in decoded],[r[2].obj for r in original])

    def test_financial_and_report_rows_never_packed_or_reordered(self):
        a=self.item(index=1);b=self.item(index=2)
        fill=self.item('FILL',3);settlement=self.item('SETTLED',4)
        report=entry('demo/shadow/report/T',{},dict(net_realized_pnl='11'))
        c=self.item(index=5);d=self.item(index=6)
        compacted=self.compact([a,b,fill,settlement,report,c,d])
        self.assertEqual(len(compacted),5)
        self.assertEqual(compacted[1],fill)
        self.assertEqual(compacted[2],settlement)
        self.assertEqual(compacted[3],report)
        self.assertEqual(decode_diagnostic_batch(compacted[0][2].obj)[0]['key'],a[3])
        self.assertEqual(decode_diagnostic_batch(compacted[4][2].obj)[1]['key'],d[3])
        self.assertEqual(self.compact([fill]),[fill])
        self.assertEqual(self.compact([a]),[a])

    def test_large_run_is_bounded_and_no_event_is_lost(self):
        original=[self.item(index=i) for i in range(130)]
        result=self.compact(original)
        self.assertEqual([x[2].obj['count'] for x in result],[64,64,2])
        restored=[x['id'] for row in result for x in decode_diagnostic_batch(row[2].obj)]
        self.assertEqual(restored,[str(r[0]) for r in original])

    def test_corrupt_checksum_count_or_financial_event_fails_closed(self):
        row=self.compact([self.item(index=1),self.item(index=2)])[0]
        original=row[2].obj
        for field,value in [('sha256','f'*64),('count',3),('decoded_bytes',1),
                            ('compressed_bytes',1),('encoding','wrong')]:
            altered=dict(original,**{field:value})
            with self.assertRaises(ValueError,msg=field):
                decode_diagnostic_batch(altered)
        records=decode_diagnostic_batch(original)
        records[1]['progress']['event']='SETTLED'
        raw=json.dumps(records,sort_keys=True,separators=(',',':')).encode()
        zipped=gzip.compress(raw,compresslevel=3,mtime=0)
        altered=dict(original,data=base64.b64encode(zipped).decode(),
                     sha256=hashlib.sha256(raw).hexdigest(),
                     decoded_bytes=len(raw),compressed_bytes=len(zipped))
        with self.assertRaisesRegex(ValueError,'Financial'):
            decode_diagnostic_batch(altered)

    def test_recent_activity_reconstructs_raw_and_packed_events(self):
        group=self.compact([self.item(index=1),self.item(index=2)])[0]
        now=datetime(2026,11,10,tzinfo=timezone.utc)
        raw=[dict(progress=dict(event='FILL'),created_at=now)]
        batch=[dict(progress=group[2].obj,created_at=now-timedelta(seconds=1))]
        merged=merge_recent_events(raw,batch)
        self.assertEqual([x['event'] for x in merged],
                         ['FILL','FAVORITE_STAT_DECISION','FAVORITE_STAT_DECISION'])
        self.assertEqual(len(merge_recent_events(raw,batch,limit=2)),2)

    def test_hosted_audit_prepare_preserves_every_written_event_and_checkpoint(self):
        audit=HostedAudit(MagicMock(),lambda:None)
        audit.checkpoint_snapshot=MagicMock(return_value=dict(checkpoint_encoding='test',
                                                               sha256='abc',bytes=1,data='hello'))
        audit.engine=SimpleNamespace(wallet=SimpleNamespace(cash='1000'),markets={})
        audit.fleet=MagicMock()
        records=[(float(i),'EXPERIMENT',dict(experiment_kind='FAVORITE_STAT_DECISION',
                                             folder_id='favorites_statistics',details='{}',
                                             ticker='T'+str(i))) for i in range(8)]
        records.append((9.0,'FILL',dict(ticker='T8',quantity='1')))
        batch,commands,written=audit.prepare(records)
        self.assertEqual(len(written),9)
        self.assertEqual(batch[0][3],'demo/shadow/checkpoint')
        self.assertEqual([r[3] for r in batch[1:3]][0].startswith(BATCH_PREFIX),True)
        self.assertEqual(len(batch),3)
        self.assertEqual(batch[-1][2].obj['event'],'FILL')
        self.assertEqual(len(decode_diagnostic_batch(batch[1][2].obj)),8)
        self.assertEqual(commands,[])


if __name__=='__main__':
    unittest.main()

"""Bounded dataset assembly preserves canonical bytes and rejects partial output."""
from contextlib import closing
import json
import unittest
from unittest.mock import patch
from services.research.datasets import RecordBuffer,_encode_dataset,DatasetLimit,_merge
from services.research.inventory import digest
from services.research.queue import EvidenceConflict


class DatasetMemoryTests(unittest.TestCase):
    def test_disk_merge_matches_canonical_order_and_provenance(self):
        with closing(RecordBuffer()) as buffer:
            buffer.add(('candles','B','2'),{'quote':{'close':'0.88'}},{'job':'recent'})
            buffer.add(('candles','A','1'),{'quote':{'open':'0.80'}},{'job':'historical'})
            buffer.add(('candles','B','2'),{'quote':{'open':'0.85'}},{'job':'historical'})
            buffer.add(('candles','B','2'),{'quote':{'close':'0.88'}},{'job':'recent'})
            self.assertEqual(buffer.counts('candles'),(2,2))
            records=list(buffer.records())
            self.assertEqual([r['ticker'] for r in records],['A','B'])
            self.assertEqual(records[1]['record'],{'quote':{'close':'0.88','open':'0.85'}})
            self.assertEqual(len(records[1]['provenance']),2)
            metadata={'format':'v1','unicode':'café 🐻','summary':{'records':2}}
            encoded,fingerprint=_encode_dataset(metadata,iter(records))
            expected={**metadata,'records':records}
            self.assertEqual(encoded,json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False))
            self.assertEqual(fingerprint,digest(expected))
            with self.assertRaises(EvidenceConflict):
                buffer.add(('candles','B','2'),{'quote':{'close':'0.20'}},{'job':'conflict'})

    def test_serialized_limit_stops_stream_without_reading_remaining_records(self):
        consumed=[]
        def records():
            for index in range(10000):
                consumed.append(index);yield {'row':index,'data':'x'*100}
        with patch('services.research.datasets.MAX_DATASET_BYTES',1000):
            with self.assertRaises(DatasetLimit):_encode_dataset({'format':'v1'},records())
        self.assertLess(len(consumed),10)

    def test_buffer_is_closed_after_failure(self):
        import sqlite3
        buffer=RecordBuffer()
        with self.assertRaises(RuntimeError):
            with closing(buffer):raise RuntimeError('failed preparation')
        with self.assertRaises(sqlite3.ProgrammingError):buffer.counts('candles')


    def test_scalar_fast_path_keeps_json_type_and_signed_zero_distinctions(self):
        for left,right in ((True,1),(1,1.0),(0.0,-0.0),('0.88','0.8')):
            with self.subTest(left=left,right=right):
                with self.assertRaises(EvidenceConflict):_merge(left,right)
        for value in (None,True,123,'0.88',0.5):self.assertEqual(_merge(value,value),value)

    def test_partitioned_trades_roundtrip_all_rows_and_keep_price_results_identical(self):
        from test_datasets import Fixture
        from services.research.datasets import iter_dataset_records
        from services.research.reports import prepare_report
        from services.research.archive import ArchiveInvalid
        fixture=Fixture();baseline=fixture.prepare();old=json.loads(baseline.payload_json)
        with patch('services.research.datasets.TRADE_PARTITION_THRESHOLD',1),patch('services.research.datasets.TRADE_PARTITION_BYTES',2000):
            partitioned=fixture.prepare()
        new=json.loads(partitioned.payload_json)
        self.assertTrue(new['record_partitions'])
        self.assertEqual(new['summary'],old['summary'])
        self.assertEqual(sorted(iter_dataset_records(new,fixture.archives),key=lambda r:(r['resource'],r['ticker'],r['identity'])),old['records'])
        def report(prepared):
            return json.loads(prepare_report('btc',[dict(id=1,payload=json.loads(prepared.payload_json),fingerprint=prepared.fingerprint)],latest_ids=[1]).payload_json)['historical']
        self.assertEqual(report(baseline),report(partitioned))
        key=new['record_partitions'][0]['receipt']['object_key'];fixture.archives.objects.data[key]=b'corrupt'
        with self.assertRaises(ArchiveInvalid):list(iter_dataset_records(new,fixture.archives))

    def test_known_row_limit_fails_before_reading_any_evidence_archive(self):
        from test_datasets import Fixture
        fixture=Fixture();keys={p['object_key'] for _,pages in fixture.attempts for p in pages}
        original=fixture.archives.read
        def read(receipt):
            if receipt['object_key'] in keys:self.fail('Limit was known before downloading evidence')
            return original(receipt)
        with patch.object(fixture.archives,'read',side_effect=read):
            with self.assertRaises(DatasetLimit):fixture.prepare(max_rows=3)

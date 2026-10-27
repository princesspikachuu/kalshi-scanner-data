"""Lossless storage avoids PostgreSQL's large nested-JSONB parse expansion."""
import base64
from copy import deepcopy
import gzip
import json
import unittest
from unittest.mock import patch
from services.research.datasets import storage_payload,decoded_dataset,STORAGE,MAX_DATASET_BYTES
from services.research.inventory import digest
from services.research.queue import EvidenceConflict
from services.research.reports import prepare_report
from test_reports import dataset


class DatasetStorageTests(unittest.TestCase):
    def encoded(self,payload):return json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)

    def test_large_payload_keeps_all_bytes_and_reduces_database_input(self):
        payload={'format':'raw-evidence-dataset-v1','records':[{'price':'0.8800','quantity':'1.0000','provenance':['same immutable receipt']*4} for _ in range(20000)]}
        encoded=self.encoded(payload);fingerprint=digest(payload)
        stored=storage_payload(encoded,fingerprint)
        self.assertEqual(stored['storage'],STORAGE)
        self.assertLess(len(self.encoded(stored)),len(encoded)//10)
        self.assertEqual(decoded_dataset(dict(id=1,payload=stored,fingerprint=fingerprint))['payload'],payload)

    def test_legacy_and_compressed_full_sample_report_are_identical(self):
        original=dataset();raw=self.encoded(original['payload'])
        self.assertEqual(storage_payload(raw,original['fingerprint']),original['payload'])
        with patch('services.research.datasets.COMPACT_THRESHOLD',0):stored=storage_payload(raw,original['fingerprint'])
        compact={**original,'payload':stored}
        self.assertEqual(prepare_report('btc',[original],latest_ids=[1]),prepare_report('btc',[compact],latest_ids=[1]))

    def test_corruption_metadata_trailing_members_and_decompression_bomb_fail(self):
        payload=dataset();raw=self.encoded(payload['payload'])
        with patch('services.research.datasets.COMPACT_THRESHOLD',0):stored=storage_payload(raw,payload['fingerprint'])
        variants=[dict(uncompressed_bytes=True),dict(uncompressed_bytes=MAX_DATASET_BYTES+1),dict(sha256='0'*64),dict(data='bad!'),dict(uncompressed_bytes=1),dict(data=base64.b64encode(gzip.compress(raw.encode())+gzip.compress(b'{}')).decode()),dict(data=base64.b64encode(gzip.compress(b'x'*1000000)).decode())]
        for changes in variants:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(EvidenceConflict):decoded_dataset({**payload,'payload':{**stored,**changes}})

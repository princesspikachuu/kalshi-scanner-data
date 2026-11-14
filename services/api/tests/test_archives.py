"""Immutable archive contract tests; no external bucket, credentials or network."""
import gzip
import hashlib
import unittest
from services.research.archive import ArchiveStore, ArchiveInvalid, prepare, decode, verify, MAX_COMPRESSED


class MemoryObjects:
    def __init__(self): self.data = {}; self.puts = 0; self.gets = 0
    def put_if_absent(self, key, body, content_type):
        self.puts += 1
        if key in self.data: return False
        self.data[key] = body
        return True
    def get(self, key, max_bytes):
        self.gets += 1
        body = self.data[key]
        if len(body) > max_bytes: raise ArchiveInvalid('Object too large')
        return body


class ArchiveTests(unittest.TestCase):
    def test_canonical_content_deduplicates_keys_and_gzip_is_reproducible(self):
        a = prepare('kalshi', {'markets': [{'price_dollars': '0.55', 'count': 2}], 'title': 'é'})
        b = prepare('kalshi', {'title': 'é', 'markets': [{'count': 2, 'price_dollars': '0.55'}]})
        self.assertEqual(a, b)
        self.assertEqual(a.sha256, hashlib.sha256(a.body).hexdigest())
        self.assertEqual(a.body[4:8], b'\0\0\0\0')
        self.assertEqual(decode(a.body), {'title': 'é', 'markets': [{'count': 2, 'price_dollars': '0.55'}]})
        self.assertNotEqual(a.key, prepare('kalshi', {'markets': []}).key)

    def test_upload_reads_back_verified_evidence_before_returning_receipt(self):
        objects = MemoryObjects()
        store = ArchiveStore(objects)
        first = store.upload('kalshi', {'markets': []})
        second = store.upload('kalshi', {'markets': []})
        self.assertEqual(first, second)
        self.assertEqual(len(objects.data), 1)
        self.assertEqual(objects.gets, 2)
        self.assertEqual(store.read(first), {'markets': []})
        self.assertEqual(first['content_type'], 'application/gzip')

    def test_existing_wrong_evidence_is_never_overwritten(self):
        objects = MemoryObjects()
        a = prepare('kalshi', {'cursor': 'two'})
        objects.data[a.key] = b'corrupt'
        with self.assertRaises(ArchiveInvalid): ArchiveStore(objects).upload('kalshi', {'cursor': 'two'})
        self.assertEqual(objects.data[a.key], b'corrupt')

    def test_storage_failures_do_not_return_checkpoint_receipts(self):
        class Broken(MemoryObjects):
            def get(self, key, max_bytes): raise TimeoutError('object unavailable')
        with self.assertRaises(TimeoutError): ArchiveStore(Broken()).upload('kalshi', {})

    def test_corruption_truncation_and_wrong_lengths_are_rejected(self):
        a = prepare('kalshi', {'a': 1})
        for body in (a.body[:-2], a.body + b'!', b'x' * (MAX_COMPRESSED + 1)):
            with self.assertRaises(ArchiveInvalid): verify(a.key, body)
        with self.assertRaises(ArchiveInvalid): verify(a.key, a.body, len(a.body) + 1)
        with self.assertRaises(ArchiveInvalid): decode(a.body[:-2])

    def test_bomb_duplicate_keys_nonfinite_invalid_utf8_and_deep_json_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'\xff', b'0', b'[' * 1000 + b']' * 1000):
            with self.assertRaises(ArchiveInvalid): decode(gzip.compress(raw, mtime=0))
        with self.assertRaises(ArchiveInvalid): decode(gzip.compress(b' ' * 10000), max_decoded=100)
        with self.assertRaises(ArchiveInvalid): decode(b'not gzip')

    def test_bad_input_and_credentials_shaped_keys_are_not_valid_object_paths(self):
        cycle = {}; cycle['self'] = cycle
        for value in ({'a': float('nan')}, {1: 'bad key'}, {'a': object()}, cycle, 'raw string'):
            with self.assertRaises(ArchiveInvalid): prepare('kalshi', value)
        for provider in ('../kalshi', 'https://host', '', 'Kalshi'):
            with self.assertRaises(ArchiveInvalid): prepare(provider, {})
        a = prepare('kalshi', {})
        for key in ('../file', 'https://host/secret', a.key.replace('/' + a.sha256[:2] + '/', '/xx/')):
            with self.assertRaises(ArchiveInvalid): verify(key, a.body)

    def test_receipt_tampering_is_rejected_before_reading(self):
        objects = MemoryObjects(); store = ArchiveStore(objects)
        receipt = store.upload('kalshi', {})
        for patch in ({'provider': 'other'}, {'sha256': 'b' * 64}, {'byte_length': -1}, {'content_type': 'text/plain'}, {'object_key': '../../file'}):
            before = objects.gets
            with self.assertRaises(ArchiveInvalid): store.read({**receipt, **patch})
            self.assertEqual(objects.gets, before)

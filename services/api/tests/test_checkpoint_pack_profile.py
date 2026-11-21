"""Checkpoint timing probes must not alter exact durable bytes or restore."""
import json
import unittest

from services.paper_demo.shadow.checkpoint_codec import (
    pack_checkpoint,unpack_checkpoint,BINARY_ENCODING,ENCODING,
)
from services.paper_demo.shadow.checkpoint_segments import CheckpointSegments


def sample():
    return dict(schema=1,wallet=dict(cash='1000.0166',lots=[]),
        experiments=dict(_summary=dict(history=list(range(5000))),
            maker=dict(model=dict(history=list(range(3000))))))


class CheckpointPackProfileTests(unittest.TestCase):
    def test_timing_probe_preserves_exact_checkpoint_digest_and_payload(self):
        data=sample()
        original=pack_checkpoint(data,threshold=0,binary=True,
                                 segments=CheckpointSegments())
        profile={}
        cache=CheckpointSegments()
        measured=pack_checkpoint(data,threshold=0,binary=True,
                                 segments=cache,profile=profile)
        self.assertEqual(measured,original)
        self.assertEqual(measured['checkpoint_encoding'],BINARY_ENCODING)
        self.assertEqual(unpack_checkpoint(measured),data)
        fields=('segment_pack_ms','cold_member_compression_ms','checksum_ms',
                'hot_compress_join_ms','base64_ms')
        self.assertEqual(set(profile),set(fields))
        self.assertTrue(all(type(profile[key]) is float and profile[key]>=0
                            for key in fields))
        self.assertLessEqual(profile['cold_member_compression_ms'],
                             profile['segment_pack_ms']+0.1)
        self.assertNotIn('history',json.dumps(profile))
        self.assertNotIn('cash',json.dumps(profile))

    def test_cached_cold_members_retain_exact_bytes_with_zero_recompression(self):
        data=sample();cache=CheckpointSegments();first={}
        before=pack_checkpoint(data,threshold=0,binary=True,segments=cache,
                               profile=first)
        self.assertGreater(first['cold_member_compression_ms'],0)
        hits=cache.metrics()['hits'];second={}
        after=pack_checkpoint(data,threshold=0,binary=True,segments=cache,
                              profile=second)
        self.assertEqual(after,before)
        self.assertEqual(second['cold_member_compression_ms'],0)
        self.assertGreater(cache.metrics()['hits'],hits)

    def test_binary_fallback_does_not_report_nonexistent_segment_phases(self):
        data=dict(value=2**100)
        metrics={}
        encoded=pack_checkpoint(data,threshold=0,binary=True,
                                segments=CheckpointSegments(),profile=metrics)
        self.assertEqual(encoded['checkpoint_encoding'],ENCODING)
        self.assertEqual(unpack_checkpoint(encoded),data)
        self.assertEqual(metrics,{})


if __name__=='__main__':
    unittest.main()

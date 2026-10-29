"""Bounded decoding of immutable compressed research evidence for paper replay.

Avoid materializing an entire 64 MiB dataset's candidate/record JSON tree.
The compressed bytes are verified before any observations enter simulation.
"""
import base64
import gzip
import hashlib
import io
import json

import ijson

from services.research.datasets import (
    STORAGE, FORMAT, MAX_DATASET_BYTES, decoded_dataset, iter_dataset_records,
)
from services.research.queue import EvidenceConflict


def replay_source(source, archives):
    asset=source['asset']
    packed=source['payload']
    if packed.get('storage')!=STORAGE:
        payload=decoded_dataset(source)['payload']
        if 'trades' not in payload['summary']['resources']:
            raise ValueError('Detailed trade evidence required')
        return asset,payload,iter_dataset_records(payload,archives)

    size=packed.get('uncompressed_bytes')
    if (not isinstance(size,int) or not 0<size<=MAX_DATASET_BYTES
            or packed.get('sha256')!=source['fingerprint']):
        raise EvidenceConflict('Invalid compressed dataset metadata')
    try:
        binary=base64.b64decode(packed['data'],validate=True)
        # Streaming hash and complete gzip validation, no expanded JSON blob.
        checksum=hashlib.sha256()
        count=0
        with gzip.GzipFile(fileobj=io.BytesIO(binary)) as stream:
            while True:
                block=stream.read(65536)
                if not block:break
                count+=len(block)
                if count>size:raise EvidenceConflict('Compressed dataset expanded beyond declared size')
                checksum.update(block)
        if count!=size or checksum.hexdigest()!=source['fingerprint']:
            raise EvidenceConflict('Compressed dataset fingerprint mismatch')
        def items(prefix):
            with gzip.GzipFile(fileobj=io.BytesIO(binary)) as stream:
                yield from ijson.items(stream,prefix,use_float=True)
        summary=next(items('summary'),None)
        candidates=list(items('candidates.item'))
        if not isinstance(summary,dict) or 'trades' not in summary.get('resources',[]):
            raise ValueError('Detailed trade evidence required')
        # Preserve original record and partition iteration order. Each R2
        # partition is verified before yielding any of its rows.
        def records():
            yield from items('records.item')
            for part in items('record_partitions.item'):
                from services.research.datasets import iter_dataset_records
                yield from iter_dataset_records(
                    dict(records=[],record_partitions=[part]),archives)
        return asset,dict(format=FORMAT,candidates=candidates,summary=summary),records()
    except (OSError,EOFError,ValueError,TypeError,KeyError,ijson.JSONError) as error:
        if isinstance(error,EvidenceConflict):raise
        raise EvidenceConflict('Compressed replay dataset integrity mismatch') from None

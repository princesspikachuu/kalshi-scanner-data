"""Transient report projections; source fingerprints always identify full evidence."""
import base64
import hashlib
import json
import zlib
from .datasets import STORAGE,MAX_DATASET_BYTES,FORMAT
from .inventory import digest
from .queue import EvidenceConflict

_VERIFIED=object()
_CANDIDATE=('ticker','event_ticker','series','close_time','result')


def _project_object(value):
    # JSON's bottom-up hook releases unused provenance/trade objects before the
    # full records list is retained. No source bytes or stored payload changes.
    if 'resource' in value and 'ticker' in value and 'record' in value:
        if value['resource']!='candles':return None
        return {key:value[key] for key in ('resource','ticker','record')}
    if all(key in value for key in _CANDIDATE):
        return {key:value[key] for key in _CANDIDATE}
    if value.get('format')==FORMAT:
        return dict(format=FORMAT,day=value['day'],candidates=value['candidates'],
                    records=[r for r in value['records'] if r is not None],summary=value['summary'])
    return value


def report_dataset(dataset):
    if dataset.get('_report_verified') is _VERIFIED:return dataset
    payload=dataset['payload']
    try:
        if payload.get('storage')==STORAGE:
            size=payload.get('uncompressed_bytes')
            if (type(size) is not int or not 0<size<=MAX_DATASET_BYTES or
                    payload.get('sha256')!=dataset['fingerprint']):raise ValueError()
            encoded=payload['data']
            if not isinstance(encoded,str) or len(encoded)>2*MAX_DATASET_BYTES:raise ValueError()
            compressed=base64.b64decode(encoded,validate=True)
            decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
            raw=decoder.decompress(compressed,size+1)
            if len(raw)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError()
            if hashlib.sha256(raw).hexdigest()!=dataset['fingerprint']:raise ValueError()
            # The canonical full source is hash-verified BEFORE projection.
            del compressed,decoder
            projected=json.loads(raw,object_hook=_project_object)
        else:
            if digest(payload)!=dataset['fingerprint']:raise ValueError()
            projected={**payload,'candidates':[_project_object(c) for c in payload['candidates']],
                'records':[_project_object(r) for r in payload['records'] if r['resource']=='candles']}
        if not isinstance(projected,dict) or projected.get('format')!=FORMAT:raise ValueError()
    except (ValueError,KeyError,TypeError,zlib.error,UnicodeError):
        raise EvidenceConflict('Report input integrity mismatch') from None
    return {**dataset,'payload':projected,'_report_verified':_VERIFIED}

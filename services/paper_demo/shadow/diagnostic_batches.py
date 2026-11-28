"""Lossless, bounded packing for high-volume non-financial shadow diagnostics.

The financial audit ledger remains one event per row. Each packed diagnostic
holds original event UUIDs, keys, parameters and progress so the evidence can
be restored exactly. Nothing is sampled or dropped.
"""
import base64
import gzip
import hashlib
import io
import json
from uuid import uuid4

EVENT_PREFIX='demo/shadow/event/'
BATCH_PREFIX='demo/shadow/event-batch/'
DIAGNOSTIC_EVENTS=frozenset({
    'FAVORITE_STAT_DECISION',
    'FAVORITE_ENTRY_DECISION',
    'FAVORITE_REPEAT_OPPORTUNITY',
    'FAVORITE_ENTRY_COHORT',
    'FAVORITE_TRIAL_QUALITY',
    'SCALPER_OBSERVATION_BATCH',
})
MAX_EVENTS=64
MAX_DECODED=4*1024*1024
MAX_COMPRESSED=2*1024*1024


def _payload(row):
    value=getattr(row[2],'obj',None)
    return value if isinstance(value,dict) else None


def _is_diagnostic(row):
    return (isinstance(row[3],str) and row[3].startswith(EVENT_PREFIX)
            and (_payload(row) or {}).get('event') in DIAGNOSTIC_EVENTS)


def _packed(group,make_entry):
    original=[dict(id=str(row[0]),key=row[3],
        parameters=getattr(row[1],'obj',None),progress=_payload(row)) for row in group]
    if any(not isinstance(x['parameters'],dict) or not isinstance(x['progress'],dict) for x in original):
        return None
    raw=json.dumps(original,sort_keys=True,separators=(',',':'),default=str).encode()
    if len(raw)>MAX_DECODED:return None
    compressed=gzip.compress(raw,compresslevel=3,mtime=0)
    if len(compressed)>MAX_COMPRESSED:return None
    encoded=base64.b64encode(compressed).decode('ascii')
    progress=dict(format='shadow-diagnostic-batch-v1',encoding='gzip-base64',
        sha256=hashlib.sha256(raw).hexdigest(),decoded_bytes=len(raw),
        compressed_bytes=len(compressed),count=len(group),data=encoded)
    parameters=dict(kinds=sorted({x['progress']['event'] for x in original}),
                    count=len(group),first_time=original[0]['progress'].get('time'),
                    last_time=original[-1]['progress'].get('time'))
    return make_entry(BATCH_PREFIX+str(uuid4()),parameters,progress)


def compact_diagnostic_rows(rows,make_entry):
    """Replace *consecutive* diagnostic rows with verified packed equivalents.

    The original financial/report/control ordering is unchanged. If the packed
    payload is too large or cannot be serialized, original rows are retained.
    """
    result=[];pending=[]
    def flush():
        if not pending:return
        packed=_packed(pending,make_entry) if len(pending)>=2 else None
        result.extend([packed] if packed is not None else pending)
        pending.clear()
    for row in rows:
        if not _is_diagnostic(row):
            flush();result.append(row);continue
        if len(pending)>=MAX_EVENTS:flush()
        pending.append(row)
    flush()
    return result


def decode_diagnostic_batch(progress):
    if not isinstance(progress,dict) or progress.get('format')!='shadow-diagnostic-batch-v1':
        raise ValueError('Unknown diagnostic batch version')
    if progress.get('encoding')!='gzip-base64' or type(progress.get('count')) is not int:
        raise ValueError('Invalid diagnostic batch encoding')
    if not 2<=progress['count']<=MAX_EVENTS:return _invalid()
    encoded=progress.get('data')
    if not isinstance(encoded,str) or len(encoded)>(MAX_COMPRESSED*4//3+8):
        raise ValueError('Oversize diagnostic payload')
    try:
        zipped=base64.b64decode(encoded,validate=True)
        if len(zipped)>MAX_COMPRESSED:raise ValueError('Oversize diagnostic body')
        with gzip.GzipFile(fileobj=io.BytesIO(zipped)) as source:
            raw=source.read(MAX_DECODED+1)
        if len(raw)>MAX_DECODED:raise ValueError('Decoded diagnostic payload is too large')
        if len(raw)!=progress.get('decoded_bytes') or len(zipped)!=progress.get('compressed_bytes'):
            raise ValueError('Diagnostic batch length mismatch')
        if hashlib.sha256(raw).hexdigest()!=progress.get('sha256'):
            raise ValueError('Diagnostic batch checksum mismatch')
        data=json.loads(raw)
    except (ValueError,TypeError,EOFError,OSError,UnicodeError) as error:
        raise ValueError('Invalid compressed diagnostic history') from None
    if not isinstance(data,list) or len(data)!=progress['count']:
        raise ValueError('Diagnostic count mismatch')
    ids=set()
    for item in data:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str):
            raise ValueError('Invalid diagnostic record')
        if item['id'] in ids or not str(item.get('key','')).startswith(EVENT_PREFIX):
            raise ValueError('Duplicate or unrelated diagnostic record')
        if not isinstance(item.get('parameters'),dict) or not isinstance(item.get('progress'),dict):
            raise ValueError('Incomplete diagnostic evidence')
        if item['progress'].get('event') not in DIAGNOSTIC_EVENTS:
            raise ValueError('Financial event in diagnostic batch')
        ids.add(item['id'])
    return data


def _invalid():
    raise ValueError('Invalid diagnostic count')


def merge_recent_events(raw_rows,batch_rows,limit=100):
    """Reconstruct the latest activity without expanding the dashboard snapshot."""
    merged=[]
    for row in raw_rows:
        merged.append((row['created_at'],0,row['progress']))
    for row in batch_rows:
        entries=decode_diagnostic_batch(row['progress'])
        for i,item in enumerate(entries):
            merged.append((row['created_at'],i,item['progress']))
    merged.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [item[2] for item in merged[:limit]]

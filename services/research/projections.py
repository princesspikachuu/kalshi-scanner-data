"""Resolve shared immutable provider objects into fenced per-scope evidence.

Legacy per-page envelopes remain readable. Selectors locate the original batch
entry and original row, not merely a reconstructed per-market copy.
"""
from dataclasses import asdict
import json
import math

from .inventory import digest
from .queue import EvidenceConflict

BATCH='candle-batch-projection-v1'


def _entry(scope,receipt,archives):
    from .evidence import evidence_page
    if (scope.resource,scope.source)!=('candles','recent'):
        raise EvidenceConflict('Batch projection requires recent candles')
    identity={k:receipt[k] for k in ('object_key','sha256','provider','content_type','byte_length')}
    if identity['provider']!='kalshi':raise EvidenceConflict('Wrong batch provider')
    prefix=digest(identity)+'/'
    cache=archives.batch_indexes
    saved=cache.get(prefix+scope.ticker)
    if saved is None:
        envelope=archives.read(receipt)
        if not isinstance(envelope,dict) or envelope.get('format')!='candle-batch-v1':raise EvidenceConflict('Wrong batch archive format')
        args=envelope.get('request');payload=envelope.get('response')
        if (not isinstance(args,dict) or set(args)!={'market_tickers','start_ts','end_ts','period_interval'}
                or args['period_interval']!=1 or type(args['period_interval']) is not int
                or type(args['start_ts']) is not int or type(args['end_ts']) is not int
                or args['start_ts']>=args['end_ts'] or not isinstance(args['market_tickers'],str)):
            raise EvidenceConflict('Invalid batch request')
        tickers=args['market_tickers'].split(',')
        if (not 1<=len(tickers)<=100 or len(set(tickers))!=len(tickers)
                or len(tickers)*(math.ceil((args['end_ts']-args['start_ts'])/60)+1)>10000
                or not isinstance(payload,dict) or not isinstance(payload.get('markets'),list)
                or len(payload['markets'])>len(tickers)
                or payload.get('adjusted_end_ts',args['end_ts'])!=args['end_ts']):
            raise EvidenceConflict('Invalid or truncated batch')
        seen=set();total=0;indexed={}
        for index,entry in enumerate(payload['markets']):
            if not isinstance(entry,dict):raise EvidenceConflict('Invalid batch market')
            ticker=entry.get('market_ticker');bars=entry.get('candlesticks')
            if (ticker not in tickers or ticker in seen or not isinstance(bars,list)
                    or entry.get('adjusted_end_ts',args['end_ts'])!=args['end_ts']):
                raise EvidenceConflict('Foreign, duplicate or truncated batch market')
            seen.add(ticker);total+=len(bars);timestamps=set()
            for bar in bars:
                ts=bar.get('end_period_ts') if isinstance(bar,dict) else None
                if (type(ts) is not int or not args['start_ts']<=ts<=args['end_ts'] or ts in timestamps):
                    raise EvidenceConflict('Invalid batch candle identity')
                timestamps.add(ts)
            if total>10000:raise EvidenceConflict('Batch candle limit exceeded')
            indexed[ticker]=dict(request=args,entry=entry,index=index)
        # Prime only after the complete batch structure has passed validation.
        for ticker,value in indexed.items():
            cache.put(prefix+ticker,json.dumps(value,separators=(',',':'),allow_nan=False).encode())
        value=indexed.get(scope.ticker)
        if value is None:raise EvidenceConflict('Missing batch member')
    else:value=json.loads(saved)
    args=value['request'];entry=value['entry'];index=value['index']
    if not args['start_ts']<=scope.start_ts<scope.end_ts<=args['end_ts']:
        raise EvidenceConflict('Batch does not cover scope window')
    selected=[(i,row) for i,row in enumerate(entry['candlesticks']) if scope.start_ts<=row['end_period_ts']<=scope.end_ts]
    response=dict(ticker=scope.ticker,candlesticks=[row for i,row in selected])
    rows,cursor=evidence_page(scope,response,'available')
    marker=dict(format=BATCH,request_sha256=digest(args),entry_index=index)
    selectors=[dict(format=BATCH,entry_index=index,row_index=i) for i,row in selected]
    return response,marker,selectors


def archive_evidence(scope,checkpoint,response,archives):
    receipt=response.payload.get('batch_receipt')
    if receipt is None:
        return archives.upload('kalshi',dict(scope=asdict(scope),checkpoint=checkpoint,response=response.payload)),checkpoint
    payload,marker,_=_entry(scope,receipt,archives)
    if response.availability!='available' or {**payload,'batch_receipt':receipt}!=response.payload:
        raise EvidenceConflict('Cached projection differs from verified batch')
    updated={**checkpoint,'projection':marker}
    _check_checkpoint(scope,updated,payload)
    return receipt,updated


def _check_checkpoint(scope,cp,payload):
    from .evidence import evidence_page
    rows,cursor=evidence_page(scope,payload,'available')
    if (type(cp.get('sequence')) is not int or type(cp.get('items')) is not int
            or cp.get('scope')!=scope.key or cp.get('sequence')!=0 or cp.get('cursor_in')!=''
            or cp.get('cursor_out')!=cursor or cp.get('availability')!='available' or cp.get('items')!=len(rows)):
        raise EvidenceConflict('Shared projection checkpoint mismatch')


def resolve_evidence(scope,page,archives):
    from .evidence import evidence_page
    cp=page['checkpoint'];receipt=page['receipt']
    if receipt['object_key']!=page['object_key'] or receipt['provider']!='kalshi':
        raise EvidenceConflict('Wrong evidence reference')
    if 'projection' in cp:
        payload,marker,selectors=_entry(scope,receipt,archives)
        if cp['projection']!=marker:raise EvidenceConflict('Projection selector mismatch')
        _check_checkpoint(scope,cp,payload)
    else:
        envelope=archives.read(receipt)
        if envelope.get('scope')!=asdict(scope) or envelope.get('checkpoint')!=cp:
            raise EvidenceConflict('Evidence envelope does not match committed progress')
        payload=envelope['response'];selectors=None
    rows,cursor=evidence_page(scope,payload,cp['availability'])
    if len(rows)!=cp['items'] or cursor!=cp['cursor_out']:
        raise EvidenceConflict('Evidence response does not match progress')
    return rows,cursor,selectors if selectors is not None else [None]*len(rows)

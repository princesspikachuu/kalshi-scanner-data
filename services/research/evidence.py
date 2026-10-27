"""Resumable raw candle/trade evidence bound to archived normalized membership."""
from dataclasses import asdict, dataclass
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
import math
import json
import re

from .inventory import InventoryWorker, ProviderPage, ProviderFailure, ProviderDeferred, digest, valid_cursor
from .kalshi import KalshiInventory, invalid, parse_json
from .normalize import CandidateBatch, VERSION, _closed
from .queue import EvidenceConflict, text_key


@dataclass(frozen=True)
class EvidenceScope:
    resource: str
    source: str
    series: str
    ticker: str
    result: str
    close_time: str
    start_ts: int
    end_ts: int
    candidate_key: str
    manifest_key: str
    manifest_sha256: str
    manifest_bytes: int

    page_namespace = 'evidence'

    def __post_init__(self):
        if self.resource not in ('candles','trades') or self.source not in ('recent','historical') or self.result not in ('yes','no'):
            raise ValueError('Invalid evidence scope')
        if not re.fullmatch(r'[A-Z0-9_-]{1,64}',self.series) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',self.ticker) or self.ticker in ('.','..'):
            raise ValueError('Invalid evidence identity')
        for value in (self.candidate_key,self.manifest_sha256):
            if not re.fullmatch(r'[0-9a-f]{64}',value): raise ValueError('Invalid evidence digest')
        close = math.ceil(_closed(self.close_time).timestamp())
        if (type(self.start_ts) is not int or type(self.end_ts) is not int
                or not close-86400 <= self.start_ts < self.end_ts <= close
                or self.end_ts-self.start_ts > 21600):
            raise ValueError('Evidence windows must be at most six hours within one day of close')
        if type(self.manifest_bytes) is not int or not 1 <= self.manifest_bytes <= 8*1024*1024:
            raise ValueError('Invalid manifest size')
        from .archive import validate_key
        validate_key(self.manifest_key)
        if self.manifest_key.split('/')[2] != 'research' or self.manifest_key.split('/')[-1] != self.manifest_sha256+'.json.gz':
            raise ValueError('Invalid manifest reference')

    @property
    def key(self): return digest(asdict(self))
    def parameters(self): return {'collector':'evidence-v1','scope':asdict(self)}
    def manifest_receipt(self):
        return dict(object_key=self.manifest_key,sha256=self.manifest_sha256,byte_length=self.manifest_bytes,
                    provider='research',content_type='application/gzip')

    def request(self,cursor):
        cursor = valid_cursor(cursor)
        if self.resource == 'candles':
            if cursor: raise ValueError('Candles are windowed, not cursor paginated')
            path = (f'/historical/markets/{self.ticker}/candlesticks' if self.source=='historical'
                    else f'/series/{self.series}/markets/{self.ticker}/candlesticks')
            return path,dict(start_ts=self.start_ts,end_ts=self.end_ts,period_interval=1)
        args = dict(ticker=self.ticker,min_ts=self.start_ts,max_ts=self.end_ts,limit=1000)
        if cursor: args['cursor'] = cursor
        return ('/historical/trades' if self.source=='historical' else '/markets/trades'),args


@dataclass(frozen=True)
class EvidencePlan:
    manifest_key: str
    manifest_sha256: str
    manifest_bytes: int
    batch_fingerprint: str
    scopes: tuple[EvidenceScope, ...]

    def manifest_receipt(self):
        return dict(object_key=self.manifest_key,sha256=self.manifest_sha256,byte_length=self.manifest_bytes,
                    provider='research',content_type='application/gzip')


def build_scopes(batch,archives,*,lookback_seconds,resources=('candles','trades')):
    """Archive the full ready membership, then plan ALL candidates, both sources.
    No enqueue or provider calls. Candles and optional execution trades stay
    separate resources; downstream must never shrink candle counts to trade rows.
    """
    if not isinstance(batch,CandidateBatch) or batch.version != VERSION or not batch.ready:
        raise ValueError('Verified ready candidate batch required')
    if type(lookback_seconds) is not int or not 60 <= lookback_seconds <= 86400:
        raise ValueError('Lookback must be 60..86400 seconds')
    resources = tuple(sorted(set(resources)))
    if not resources or any(v not in ('candles','trades') for v in resources): raise ValueError('Invalid resources')
    if len(batch.candidates)*math.ceil(lookback_seconds/21600)*len(resources)*2 > 100000:
        raise ValueError('Evidence plan too large; select explicit batch partitions')
    receipt = archives.upload('research',dict(format='candidate-manifest-v1',fingerprint=batch.fingerprint,batch=json.loads(json.dumps(asdict(batch)))))
    return plan_from_receipt(batch,receipt,lookback_seconds,resources)


def plan_from_receipt(batch,receipt,lookback_seconds,resources):
    """Pure canonical plan reconstruction for publication validation."""
    if type(lookback_seconds) is not int or not 60 <= lookback_seconds <= 86400:
        raise ValueError('Invalid evidence lookback')
    scopes = []
    for candidate in batch.candidates:
        if candidate.result not in ('yes','no') or not candidate.evidence:
            raise EvidenceConflict('Candidate lacks settled inventory provenance')
        end = math.ceil(_closed(candidate.close_time).timestamp())
        start = end-lookback_seconds
        while start < end:
            stop = min(end,start+21600)
            for resource in resources:
                for source in ('recent','historical'):
                    scopes.append(EvidenceScope(resource,source,candidate.series,candidate.ticker,candidate.result,
                        candidate.close_time,start,stop,digest(asdict(candidate)),receipt['object_key'],receipt['sha256'],receipt['byte_length']))
            start = stop
    return EvidencePlan(receipt['object_key'],receipt['sha256'],receipt['byte_length'],batch.fingerprint,tuple(scopes))


def scope_for_job(job,archives):
    p = job['parameters']
    if not isinstance(p,dict) or set(p) != {'collector','scope'} or p['collector'] != 'evidence-v1':
        raise ValueError('Not an evidence job')
    scope = EvidenceScope(**p['scope'])
    manifest = archives.read(scope.manifest_receipt())
    if not isinstance(manifest,dict) or manifest.get('format') != 'candidate-manifest-v1':
        raise EvidenceConflict('Invalid candidate manifest')
    batch = manifest.get('batch')
    if (not isinstance(batch,dict) or digest(batch) != manifest.get('fingerprint') or batch.get('version') != VERSION
            or not batch.get('inputs') or any(v.get('state') not in ('complete','empty') for v in batch['inputs'])):
        raise EvidenceConflict('Candidate manifest is incomplete or mismatched')
    candidates = [c for c in batch['candidates'] if digest(c)==scope.candidate_key]
    if len(candidates) != 1: raise EvidenceConflict('Candidate not in selected immutable membership')
    candidate = candidates[0]
    if (not candidate.get('evidence') or any(candidate[k] != getattr(scope,k) for k in ('ticker','series','result','close_time'))):
        raise EvidenceConflict('Evidence scope does not match candidate')
    return scope


def _decimal(value,*,price=True):
    if not isinstance(value,str): raise invalid()
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or (price and number>1) or (not price and number<=0): raise invalid()
    except InvalidOperation: raise invalid() from None


def evidence_page(scope,payload,availability):
    """Validate evidence without converting units or claiming fills/quote coverage."""
    if availability == 'unavailable':
        if payload != {'http_status':404}: raise invalid()
        return [],''
    if not isinstance(payload,dict): raise invalid()
    field = 'candlesticks' if scope.resource=='candles' else 'trades'
    rows = payload.get(field)
    if not isinstance(rows,list) or len(rows)>1000 or any(not isinstance(r,dict) for r in rows): raise invalid()
    if scope.resource=='candles':
        if payload.get('ticker') != scope.ticker or payload.get('cursor'): raise invalid()
        seen = set()
        for row in rows:
            ts = row.get('end_period_ts')
            if type(ts) is not int or not scope.start_ts <= ts <= scope.end_ts or ts in seen: raise invalid()
            seen.add(ts)
            for name in ('yes_bid','yes_ask','no_bid','no_ask','price'):
                quote = row.get(name)
                if quote is None: continue
                if not isinstance(quote,dict): raise invalid()
                for key,value in quote.items():
                    if (key.removesuffix('_dollars') in ('open','close','high','low','mean','previous','min','max')
                            and value is not None): _decimal(value)
        return rows,''
    if 'cursor' not in payload: raise invalid()
    try: cursor = valid_cursor('' if payload['cursor'] is None else payload['cursor'])
    except ValueError: raise invalid() from None
    seen = set()
    for row in rows:
        if row.get('ticker') != scope.ticker: raise invalid()
        try: trade_id = text_key(row.get('trade_id'))
        except ValueError: raise invalid() from None
        if trade_id in seen: raise invalid()
        seen.add(trade_id)
        try: stamp = _closed(row.get('created_time')).timestamp()
        except EvidenceConflict: raise invalid() from None
        if not scope.start_ts <= stamp <= scope.end_ts: raise invalid()
        for key in ('yes_price_dollars','no_price_dollars'): _decimal(row.get(key))
        _decimal(row.get('count_fp'),price=False)
        if 'is_block_trade' in row and type(row['is_block_trade']) is not bool: raise invalid()
        if 'taker_outcome_side' in row and row['taker_outcome_side'] not in ('yes','no'): raise invalid()
    return rows,cursor


class ManifestCache:
    """Bounded process-local cache of verified immutable manifests only."""
    def __init__(self,archives):self.archives=archives;self.values=OrderedDict();self.bytes=0
    def read(self,receipt):
        key=(receipt['object_key'],receipt['sha256'],receipt['byte_length'])
        if key in self.values:
            self.values.move_to_end(key);return self.values[key][0]
        value=self.archives.read(receipt);size=len(json.dumps(value).encode())
        if size<=8*1024*1024:
            while self.values and self.bytes+size>8*1024*1024:
                _,(_,old)=self.values.popitem(last=False);self.bytes-=old
            self.values[key]=(value,size);self.bytes+=size
        return value


class KalshiEvidence(KalshiInventory):
    def __init__(self,*,archives=None,**kwargs):
        super().__init__(**kwargs)
        self.archives=archives;self.batch=();self.responses={};self.single_only=OrderedDict()

    def cached(self,scope,cursor):
        return None if cursor else self.responses.get(scope.key)

    def acknowledge(self,scope):
        self.responses.pop(scope.key,None)

    def plan_batch(self,scopes):
        if self.archives is None:return
        if scopes and self.cached(scopes[0],'') is not None:
            self.batch=();return
        chosen=[];tickers=set()
        for scope in scopes:
            if (scope.resource,scope.source)!=('candles','recent') or scope.key in self.single_only:continue
            if self.cached(scope,'') is not None:continue
            if scope.ticker in tickers:continue
            trial=chosen+[scope]
            span=max(s.end_ts for s in trial)-min(s.start_ts for s in trial)
            # Inclusive minute bars: below upstream 100 markets / 10,000 bars.
            if len(trial)>100 or len(trial)*(math.ceil(span/60)+1)>9000:continue
            chosen=trial;tickers.add(scope.ticker)
        self.batch=tuple(chosen) if len(chosen)>1 else ()

    def _single_next(self,scope):
        self.single_only[scope.key]=True
        if len(self.single_only)>1000:self.single_only.popitem(last=False)

    def _batch_fetch(self,timeout_seconds):
        scopes=self.batch;self.batch=();self.responses={}
        args=dict(market_tickers=','.join(s.ticker for s in scopes),
            start_ts=min(s.start_ts for s in scopes),end_ts=max(s.end_ts for s in scopes),period_interval=1)
        response=self._read('/markets/candlesticks',args,timeout_seconds,parse_json,allow_missing=True,missing_statuses=(400,404,422))
        payload=response.payload
        if response.availability=='unavailable':
            for scope in scopes:self._single_next(scope)
            return
        entries=payload.get('markets') if isinstance(payload,dict) else None
        if not isinstance(entries,list) or len(entries)>len(scopes):raise invalid()
        by_ticker={s.ticker:s for s in scopes};seen=set();projected={};count=0
        for entry in entries:
            if not isinstance(entry,dict):raise invalid()
            ticker=entry.get('market_ticker');bars=entry.get('candlesticks')
            if ticker not in by_ticker or ticker in seen or not isinstance(bars,list):raise invalid()
            seen.add(ticker);count+=len(bars)
            if count>10000:raise invalid()
            scope=by_ticker[ticker]
            if 'adjusted_end_ts' in entry and entry['adjusted_end_ts']!=args['end_ts']:
                self._single_next(scope);continue
            if any(not isinstance(b,dict) or type(b.get('end_period_ts')) is not int
                   or not args['start_ts']<=b['end_period_ts']<=args['end_ts'] for b in bars):raise invalid()
            item=dict(ticker=ticker,candlesticks=[b for b in bars if scope.start_ts<=b['end_period_ts']<=scope.end_ts])
            evidence_page(scope,item,'available');projected[scope.key]=item
        # Omitted members/truncation are NOT an empty market: fetch individually.
        if 'adjusted_end_ts' in payload and payload['adjusted_end_ts']!=args['end_ts']:
            projected={}
        for scope in scopes:
            if scope.key not in projected:self._single_next(scope)
        receipt=self.archives.upload('kalshi',dict(format='candle-batch-v1',request=args,response=payload))
        for key,item in projected.items():
            item['batch_receipt']=receipt
            self.responses[key]=ProviderPage(item)

    def fetch(self,scope,cursor,timeout_seconds):
        if type(scope) is not EvidenceScope: raise ValueError('Validated evidence scope required')
        if not cursor and any(s.key==scope.key for s in self.batch):
            self._batch_fetch(timeout_seconds)
            cached=self.cached(scope,cursor)
            if cached is None:raise ProviderDeferred()
            return cached
        path,args = scope.request(cursor)
        def parser(body):
            payload = parse_json(body)
            evidence_page(scope,payload,'available')
            return payload
        return self._read(path,args,timeout_seconds,parser,allow_missing=True)


class EvidenceWorker(InventoryWorker):
    def __init__(self,queue,archives,provider,budget,*,endpoint_cost,**kwargs):
        manifests=ManifestCache(archives)
        super().__init__(queue,archives,provider,budget,endpoint_cost=endpoint_cost,
            scope_loader=lambda job:scope_for_job(job,manifests),page_parser=evidence_page,**kwargs)

    def prepare_batch(self,jobs):
        if hasattr(self.provider,'plan_batch'):
            self.provider.plan_batch([self.scope_loader(job) for job in jobs])

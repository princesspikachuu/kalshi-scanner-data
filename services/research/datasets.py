"""Verify and merge raw evidence; publish immutable versions with coverage summaries.

No observations, ROI, loss policy, provider requests or trading are computed here.
"""
from .telemetry import timed,timing,count

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from decimal import Decimal
import json
import math
import base64
import gzip
import hashlib
import zlib
import sqlite3
import tempfile
from contextlib import closing

from psycopg.types.json import Jsonb

from .evidence import EvidenceScope, evidence_page, plan_from_receipt
from .inventory import digest, inspect_pages
from .normalize import _closed, normalize_inventory
from .queue import EvidenceConflict, text_key
from .projections import resolve_evidence

FORMAT = 'raw-evidence-dataset-v1'
STORAGE = 'raw-evidence-gzip-v1'
MAX_DATASET_BYTES = 64*1024*1024
COMPACT_THRESHOLD = 256*1024
TRADE_PARTITION_THRESHOLD = 10000
TRADE_PARTITION_BYTES = 1024*1024


def storage_payload(encoded, fingerprint):
    # PostgreSQL JSONB expands deeply nested records before TOAST compression.
    # Compress canonical bytes in the worker instead; retain every original byte.
    raw=encoded.encode()
    if hashlib.sha256(raw).hexdigest()!=fingerprint:
        raw=json.dumps(json.loads(encoded),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if hashlib.sha256(raw).hexdigest()!=fingerprint:raise EvidenceConflict('Invalid dataset fingerprint')
    if len(raw)>MAX_DATASET_BYTES:raise ValueError('Dataset too large')
    if len(raw)<COMPACT_THRESHOLD:return json.loads(encoded)
    return dict(storage=STORAGE,uncompressed_bytes=len(raw),sha256=fingerprint,
                data=base64.b64encode(gzip.compress(raw,compresslevel=1,mtime=0)).decode())


def decoded_dataset(dataset):
    payload=dataset['payload']
    if payload.get('storage')!=STORAGE:return dataset
    size=payload.get('uncompressed_bytes')
    if (type(size) is not int or not 0<size<=MAX_DATASET_BYTES
            or payload.get('sha256')!=dataset['fingerprint']):
        raise EvidenceConflict('Invalid compressed dataset metadata')
    try:
        encoded=payload['data']
        if not isinstance(encoded,str) or len(encoded)>2*MAX_DATASET_BYTES:raise ValueError()
        compressed=base64.b64decode(encoded,validate=True)
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        raw=decoder.decompress(compressed,size+1)
        if len(raw)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError()
        if hashlib.sha256(raw).hexdigest()!=dataset['fingerprint']:raise ValueError()
        result=json.loads(raw)
        if not isinstance(result,dict) or result.get('format')!=FORMAT or digest(result)!=dataset['fingerprint']:raise ValueError()
    except (ValueError,KeyError,TypeError,zlib.error,UnicodeError):
        raise EvidenceConflict('Compressed dataset integrity mismatch') from None
    return {**dataset,'payload':result}



class CoverageIncomplete(ValueError):
    def __init__(self,gaps):
        self.gaps = tuple(gaps)
        super().__init__('Required evidence scopes have incomplete coverage')


@dataclass(frozen=True)
class PreparedDataset:
    payload_json: str
    fingerprint: str
    summary_json: str
    artifacts_json: str


def _merge(left,right):
    if isinstance(left,dict) and isinstance(right,dict):
        out = dict(left)
        for key,value in right.items(): out[key] = _merge(out[key],value) if key in out else value
        return out
    # Canonical scalar values need no JSON serialization or SHA allocation.
    # Keep JSON distinctions (including bool/int and int/float) exact.
    if type(left) is type(right) and (left is None or type(left) in (str,int,bool)):
        if left != right:raise EvidenceConflict('Conflicting duplicate evidence')
        return left
    if digest(left) != digest(right): raise EvidenceConflict('Conflicting duplicate evidence')
    return left


class DatasetLimit(ValueError):
    """A deterministic size bound; retrying the same evidence cannot help."""


class RecordBuffer:
    """Disk-backed merge: expanded quote/provenance dictionaries stay page-sized.

    The anonymous SQLite database is deleted on close, including on exceptions.
    It is scratch space only; fenced raw archives remain the recovery source.
    """
    def __init__(self):
        self.db=sqlite3.connect('')
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('CREATE TABLE records(resource TEXT,ticker TEXT,identity TEXT,record TEXT,provenance TEXT,PRIMARY KEY(resource,ticker,identity)) WITHOUT ROWID')

    def close(self):self.db.close()

    def add(self,key,canonical,ref):
        old=self.db.execute('SELECT record,provenance FROM records WHERE resource=? AND ticker=? AND identity=?',key).fetchone()
        provenance=[] if old is None else json.loads(old[1])
        if old is not None:canonical=_merge(json.loads(old[0]),canonical)
        if ref not in provenance:provenance.append(ref)
        self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',
            (*key,json.dumps(canonical,separators=(',',':'),allow_nan=False),json.dumps(provenance,separators=(',',':'))))

    def records(self,resource=None):
        query='SELECT * FROM records'
        args=()
        if resource is not None:query+=' WHERE resource=?';args=(resource,)
        for resource,ticker,identity,record,provenance in self.db.execute(query+' ORDER BY resource,ticker,identity',args):
            refs=json.loads(provenance);refs.sort(key=digest)
            yield dict(resource=resource,ticker=ticker,identity=identity,record=json.loads(record),provenance=refs)

    def counts(self,resource):
        return self.db.execute('SELECT count(*),count(DISTINCT ticker) FROM records WHERE resource=?',(resource,)).fetchone()


def _trade_partitions(records,archives,retain):
    """Preserve every merged trade/provenance row in verified bounded objects."""
    result=[];rows=[];size=0
    def save():
        receipt=archives.upload('research',dict(format='trade-record-partition-v1',records=rows))
        retain(receipt);result.append(dict(resource='trades',row_count=len(rows),receipt=receipt))
    for row in records:
        length=len(json.dumps(row,separators=(',',':'),allow_nan=False).encode())
        if rows and (size+length>TRADE_PARTITION_BYTES or len(rows)>=1000):save();rows=[];size=0
        if length>TRADE_PARTITION_BYTES:raise DatasetLimit('Single trade record exceeds partition size')
        rows.append(row);size+=length
    if rows:save()
    return result


def iter_dataset_records(payload,archives):
    """Materialize all evidence, including explicitly stored trade partitions."""
    yield from payload['records']
    for part in payload.get('record_partitions',[]):
        value=archives.read(part['receipt'])
        if (part.get('resource')!='trades' or value.get('format')!='trade-record-partition-v1'
                or not isinstance(value.get('records'),list) or len(value['records'])!=part['row_count']
                or any(r.get('resource')!='trades' for r in value['records'])):
            raise EvidenceConflict('Invalid trade record partition')
        yield from value['records']


def _encode_dataset(payload,records):
    """Canonical v1 bytes, one record at a time, with an early byte bound."""
    encoder=json.JSONEncoder(sort_keys=True,separators=(',',':'),allow_nan=False)
    def chunks():
        yield '{'
        for index,key in enumerate(sorted([*payload,'records'])):
            if index:yield ','
            yield json.dumps(key)+':'
            if key!='records':
                yield from encoder.iterencode(payload[key]);continue
            yield '['
            for n,record in enumerate(records):
                if n:yield ','
                # A single record is small; C's encoder is faster than iterencode.
                yield encoder.encode(record)
            yield ']'
        yield '}'
    fingerprint=hashlib.sha256();size=0
    with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as output:
        for chunk in chunks():
            raw=chunk.encode();size+=len(raw)
            if size>MAX_DATASET_BYTES:raise DatasetLimit('Dataset too large; explicit partitioning required')
            fingerprint.update(raw);output.write(chunk)
        output.seek(0)
        return output.read(),fingerprint.hexdigest()


def _dataset_digest(payload):
    fingerprint=hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':'),allow_nan=False).iterencode(payload):
        fingerprint.update(chunk.encode())
    return fingerprint.hexdigest()


def _number(value): return format(Decimal(value).normalize(),'f')

def _quantity(value):
    if value is None: return None
    if isinstance(value,bool): raise EvidenceConflict('Invalid evidence quantity')
    number = Decimal(str(value))
    if not number.is_finite() or number<0: raise EvidenceConflict('Invalid evidence quantity')
    return format(number.normalize(),'f')


def _canonical(resource,row):
    result = dict(row)
    if resource=='trades':
        result['created_time'] = _closed(row['created_time']).isoformat().replace('+00:00','Z')
        for key in ('yes_price_dollars','no_price_dollars','count_fp'): result[key] = _number(row[key])
    else:
        for field in ('yes_bid','yes_ask','no_bid','no_ask','price'):
            quote = row.get(field)
            if not isinstance(quote,dict): continue
            normalized = {}
            for key,value in quote.items():
                name = key.removesuffix('_dollars')
                converted = (_number(value) if value is not None and name in
                    ('open','close','high','low','mean','previous','min','max') else value)
                normalized[name] = _merge(normalized[name],converted) if name in normalized else converted
            result[field] = normalized
        for old,new in (('volume_fp','volume'),('open_interest_fp','open_interest')):
            if old in result:
                value = _quantity(result.pop(old))
                result[new] = _merge(_quantity(result[new]),value) if new in result else value
            elif new in result and result[new] is not None: result[new] = _quantity(result[new])
    return result


@timed('dataset.prepare')
def prepare_dataset(plan,attempts,archives,inventory_loader,*,max_rows=250000,archive_parallelism=2,
                    sampled_tickers=None):
    """inventory_loader(id) -> (DB job, committed pages with receipts).

    Rebuild normalized membership from transitive inventory, then require every
    planned recent/historical scope to finish (including explicit unavailable).
    Missing/failed/partial evidence cannot be published as a complete version.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 1000000: raise ValueError('Invalid row limit')
    if type(archive_parallelism) is not int or not 1<=archive_parallelism<=2:raise ValueError('Invalid archive parallelism')
    manifest_receipt = plan.manifest_receipt()
    manifest = archives.read(manifest_receipt)
    artifacts = {}
    def retain(receipt):
        kept = {k:receipt[k] for k in ('object_key','sha256','provider','content_type','byte_length')}
        old = artifacts.setdefault(kept['object_key'],kept)
        if old != kept: raise EvidenceConflict('Conflicting artifact reference')
    retain(manifest_receipt)
    if not isinstance(manifest,dict) or manifest.get('format')!='candidate-manifest-v1':
        raise EvidenceConflict('Invalid dataset manifest')
    raw = manifest['batch']
    inputs = []
    for entry in raw['inputs']:
        job,pages = inventory_loader(entry['job_id'])
        if job is None or str(job['id'])!=entry['job_id']: raise EvidenceConflict('Missing inventory membership')
        inputs.append((job,pages))
        for page in pages: retain(page['receipt'])
    window=(raw['window_start'],raw['window_end']) if 'window_start' in raw else None
    rebuilt = normalize_inventory(raw['series'],raw['day'],raw['generation'],inputs,archives,window=window,prelaunch=bool(raw.get('exclusions')))
    if not rebuilt.ready or rebuilt.fingerprint!=manifest.get('fingerprint') or rebuilt.fingerprint!=plan.batch_fingerprint:
        raise EvidenceConflict('Normalized membership no longer matches selected inputs')
    resources = tuple(sorted({s.resource for s in plan.scopes}))
    if rebuilt.candidates:
        first = rebuilt.candidates[0]
        starts = [s.start_ts for s in plan.scopes if s.ticker==first.ticker]
        if not starts: raise CoverageIncomplete(('missing_candidate_plan',))
        lookback = math.ceil(_closed(first.close_time).timestamp())-min(starts)
        expected = plan_from_receipt(rebuilt,manifest_receipt,lookback,resources)
        if asdict(expected)!=asdict(plan): raise EvidenceConflict('Evidence plan is incomplete or altered')
    elif plan.scopes: raise EvidenceConflict('Empty cohort has unexpected scopes')
    candidates=rebuilt.candidates
    preview=None
    if sampled_tickers is not None:
        from .sample import select_preview_candidates
        sample=select_preview_candidates(candidates)
        if len(candidates)<=100 or set(sampled_tickers)!={c.ticker for c in sample}:
            raise EvidenceConflict('Invalid sampled preview membership')
        candidates=sample
        preview=dict(format='stratified-market-preview-v1',limit=100,
                     selected_markets=len(sample),available_markets=len(rebuilt.candidates))
    tickers={c.ticker for c in candidates}
    if len({s.key for s in plan.scopes})!=len(plan.scopes):
        raise EvidenceConflict('Duplicate evidence plan')
    wanted = {s.key:s for s in plan.scopes if s.ticker in tickers}
    if len(wanted)>100000: raise EvidenceConflict('Oversized selected plan')
    grouped = {k:{} for k in wanted}
    for n,(job,pages) in enumerate(attempts):
        if n>=100000: raise ValueError('Too many evidence attempts')
        p = job['parameters']
        if p.get('collector')!='evidence-v1': raise EvidenceConflict('Unexpected evidence collector')
        scope = EvidenceScope(**p['scope'])
        if scope.key not in wanted: continue
        state = inspect_pages(scope,pages)
        jid = str(job['id'])
        value = (job['status'],state,pages)
        if jid in grouped[scope.key] and grouped[scope.key][jid]!=value: raise EvidenceConflict('Conflicting job membership')
        grouped[scope.key][jid] = value
    selected,coverage,gaps = [],[],[]
    for key,scope in sorted(wanted.items()):
        completed = [(jid,v) for jid,v in grouped[key].items() if v[0]=='succeeded' and v[1].state!='partial']
        if len(completed)>1: raise EvidenceConflict('Select explicit membership among completed evidence jobs')
        if not completed:
            gaps.append(key); continue
        jid,(_,state,pages) = completed[0]
        coverage.append(dict(scope=key,job_id=jid,state=state.state,resource=scope.resource,source=scope.source))
        selected.append((scope,jid,pages))
    if gaps: raise CoverageIncomplete(gaps)
    trade_items=sum(page['checkpoint']['items'] for scope,_,pages in selected if scope.resource=='trades' for page in pages)
    partition_trades=trade_items>TRADE_PARTITION_THRESHOLD and max_rows>=TRADE_PARTITION_THRESHOLD
    bounded_items=sum(page['checkpoint']['items'] for scope,_,pages in selected
        if not partition_trades or scope.resource!='trades' for page in pages)
    # Reject a known bound before spending minutes downloading its archives.
    if bounded_items>max_rows:raise DatasetLimit('Evidence row limit exceeded; no truncated dataset')
    # Adjacent scopes often point at the same verified candle-batch object.
    # Visit that object's pages together so bounded archive/entry caches can
    # serve them before unrelated objects evict the batch. All pages were
    # already fenced and inspected above; final records and provenance sort
    # independently of this read order.
    ordered_pages=_ordered_evidence_pages(selected)
    groups=[]
    for object_key,items in groupby(ordered_pages,key=lambda item:item[2]['receipt'].get('object_key')):
        pages=list(items)
        for offset in range(0,len(pages),8):groups.append((object_key,pages[offset:offset+8]))
    scanned = bounded_scanned = 0
    with closing(RecordBuffer()) as merged:
        with ThreadPoolExecutor(max_workers=archive_parallelism) as executor:
            i=0
            while i<len(groups):
                pair=groups[i:i+2] if archive_parallelism==2 and i+1<len(groups) and groups[i][0]!=groups[i+1][0] else groups[i:i+1]
                futures=[executor.submit(_resolve_evidence_group,pages,archives) for _,pages in pair]
                for future in futures:
                    for scope,jid,page,rows,selectors in future.result():
                        receipt=page['receipt'];retain(receipt)
                        for index,row in enumerate(rows):
                            scanned += 1
                            if not partition_trades or scope.resource!='trades':bounded_scanned+=1
                            if bounded_scanned>max_rows: raise DatasetLimit('Evidence row limit exceeded; no truncated dataset')
                            identity = str(row['end_period_ts']) if scope.resource=='candles' else row['trade_id']
                            key = (scope.resource,scope.ticker,identity)
                            canonical = _canonical(scope.resource,row)
                            ref = dict(job_id=jid,scope=scope.key,page_key=page['page_key'],object_key=receipt['object_key'],row_index=index)
                            if selectors[index] is not None:ref['projection']=selectors[index]
                            merged.add(key,canonical,ref)
                i+=len(pair)
        states = {state:sum(c['state']==state for c in coverage) for state in ('complete','empty','unavailable')}
        candle_records,candle_tickers=merged.counts('candles')
        trade_records,trade_tickers=merged.counts('trades')
        summary = dict(version='evidence-coverage-v1',candidate_count=len(candidates),
            candle_records=candle_records,trade_records=trade_records,
            candidates_with_candles=candle_tickers,candidates_without_candles=len(candidates)-candle_tickers,
            candidates_with_trades=trade_tickers,candidates_without_trades=len(candidates)-trade_tickers,
            scope_states=states,resources=list(resources),raw_rows_scanned=scanned)
        partitions=_trade_partitions(merged.records('trades'),archives,retain) if partition_trades else []
        artifact_list = sorted(artifacts.values(),key=lambda a:a['object_key'])
        payload = dict(format=FORMAT,artifacts=artifact_list,manifest=manifest_receipt,batch_fingerprint=rebuilt.fingerprint,day=rebuilt.day,
            candidates=[asdict(c) for c in candidates],scopes=[asdict(s) for s in wanted.values()],coverage=coverage,summary=summary)
        if partitions:payload['record_partitions']=partitions
        if preview is not None:payload['preview']=preview
        if raw.get('exclusions'):payload['exclusions']=raw['exclusions']
        if window is not None:payload['close_window']=dict(start=rebuilt.window_start,end=rebuilt.window_end)
        encoded,fingerprint = _encode_dataset(payload,merged.records('candles') if partition_trades else merged.records())
        return PreparedDataset(encoded,fingerprint,json.dumps(summary,sort_keys=True),json.dumps(artifact_list))


def _ordered_evidence_pages(selected):
    return sorted(((scope,jid,page) for scope,jid,pages in selected for page in pages),
        key=lambda item:(item[2]['receipt'].get('object_key',''),item[0].key,item[2]['page_key']))


def _resolve_evidence_group(pages,archives):
    result=[]
    for scope,jid,page in pages:
        receipt=page['receipt']
        if receipt.get('object_key')!=page['object_key'] or receipt.get('provider')!='kalshi':
            raise EvidenceConflict('Wrong evidence reference')
        rows,_,selectors=resolve_evidence(scope,page,archives)
        result.append((scope,jid,page,rows,selectors))
    return result


class DatasetStore:
    """Publish outside hosted infrastructure; pool must be explicitly supplied."""
    def __init__(self,pool): self.pool = pool

    @timed('dataset.publish')
    def publish(self,stream_key,prepared):
        text_key(stream_key,128)
        payload,summary,artifacts = map(json.loads,(prepared.payload_json,prepared.summary_json,prepared.artifacts_json))
        if (payload.get('format')!=FORMAT or _dataset_digest(payload)!=prepared.fingerprint or payload['summary']!=summary
                or payload.get('artifacts')!=artifacts or summary.get('version')!='evidence-coverage-v1'):
            raise EvidenceConflict('Prepared dataset integrity mismatch')
        day=payload['day']
        # Release the expanded record graph before compression/JSONB adaptation.
        del payload
        stored=storage_payload(prepared.payload_json,prepared.fingerprint)
        count('dataset.raw_bytes',len(prepared.payload_json.encode()))
        count('dataset.stored_bytes',len(json.dumps(stored).encode()))
        with timing('dataset.transaction'),self.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,91027))',(stream_key,))
            existing = c.execute('SELECT id FROM research_dataset WHERE stream_key=%s AND fingerprint=%s',(stream_key,prepared.fingerprint)).fetchone()
            if existing: return existing['id']
            c.execute('''INSERT INTO research_artifact(object_key,sha256,provider,content_type,byte_length)
                SELECT object_key,sha256,provider,content_type,byte_length
                FROM jsonb_to_recordset(%s::jsonb) AS a(object_key text,sha256 text,provider text,content_type text,byte_length bigint)
                ON CONFLICT(object_key) DO NOTHING''',(Jsonb(artifacts),))
            keys = [a['object_key'] for a in artifacts]
            saved = c.execute('SELECT object_key,sha256,provider,content_type,byte_length FROM research_artifact WHERE object_key=ANY(%s::text[])',(keys,)).fetchall()
            if {a['object_key']:a for a in saved}!={a['object_key']:a for a in artifacts}:
                raise EvidenceConflict('Artifact registry conflict')
            row = c.execute('''INSERT INTO research_dataset(stream_key,fingerprint,day,payload)
                VALUES(%s,%s,%s,%s) RETURNING id''',(stream_key,prepared.fingerprint,day,Jsonb(stored))).fetchone()
            dataset_id = row['id']
            c.execute('INSERT INTO research_summary(dataset_id,version,summary) VALUES(%s,%s,%s)',(dataset_id,summary['version'],Jsonb(summary)))
            c.execute('INSERT INTO research_dataset_artifact(dataset_id,object_key) SELECT %s,unnest(%s::text[])',(dataset_id,keys))
            return dataset_id

    def history(self,stream_key,*,before=None,limit=25):
        text_key(stream_key,128)
        if type(limit) is not int or not 1<=limit<=100 or (before is not None and (type(before) is not int or before<1)):
            raise ValueError('Invalid history page')
        boundary = 'AND d.id<%s' if before is not None else ''
        parameters = (stream_key,before,limit) if before is not None else (stream_key,limit)
        with self.pool.connection() as c:
            return c.execute(f'''SELECT d.id,d.fingerprint,d.day,d.published_at,s.version,s.summary
                FROM research_dataset d JOIN research_summary s ON s.dataset_id=d.id
                WHERE d.stream_key=%s {boundary}
                ORDER BY d.id DESC LIMIT %s''',parameters).fetchall()

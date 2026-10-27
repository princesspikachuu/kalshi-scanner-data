"""Verify and merge raw evidence; publish immutable versions with coverage summaries.

No observations, ROI, loss policy, provider requests or trading are computed here.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import math

from psycopg.types.json import Jsonb

from .evidence import EvidenceScope, evidence_page, plan_from_receipt
from .inventory import digest, inspect_pages
from .normalize import _closed, normalize_inventory
from .queue import EvidenceConflict, text_key

FORMAT = 'raw-evidence-dataset-v1'


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
    if digest(left) != digest(right): raise EvidenceConflict('Conflicting duplicate evidence')
    return left


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


def prepare_dataset(plan,attempts,archives,inventory_loader,*,max_rows=250000):
    """inventory_loader(id) -> (DB job, committed pages with receipts).

    Rebuild normalized membership from transitive inventory, then require every
    planned recent/historical scope to finish (including explicit unavailable).
    Missing/failed/partial evidence cannot be published as a complete version.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 1000000: raise ValueError('Invalid row limit')
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
    rebuilt = normalize_inventory(raw['series'],raw['day'],raw['generation'],inputs,archives,window=window)
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
    wanted = {s.key:s for s in plan.scopes}
    if len(wanted)!=len(plan.scopes) or len(wanted)>100000: raise EvidenceConflict('Duplicate or oversized plan')
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
    merged,scanned = {},0
    for scope,jid,pages in selected:
        for page in sorted(pages,key=lambda p:p['page_key']):
            receipt = page['receipt']
            if receipt['object_key']!=page['object_key'] or receipt['provider']!='kalshi': raise EvidenceConflict('Wrong evidence reference')
            envelope = archives.read(receipt)
            if envelope.get('scope')!=asdict(scope) or envelope.get('checkpoint')!=page['checkpoint']:
                raise EvidenceConflict('Evidence envelope does not match committed progress')
            cp = page['checkpoint']
            rows,cursor = evidence_page(scope,envelope['response'],cp['availability'])
            if len(rows)!=cp['items'] or cursor!=cp['cursor_out']: raise EvidenceConflict('Evidence response does not match progress')
            retain(receipt)
            for index,row in enumerate(rows):
                scanned += 1
                if scanned>max_rows: raise ValueError('Evidence row limit exceeded; no truncated dataset')
                identity = str(row['end_period_ts']) if scope.resource=='candles' else row['trade_id']
                key = (scope.resource,scope.ticker,identity)
                canonical = _canonical(scope.resource,row)
                ref = dict(job_id=jid,scope=scope.key,page_key=page['page_key'],object_key=receipt['object_key'],row_index=index)
                if key in merged:
                    saved = merged[key]
                    saved['record'] = _merge(saved['record'],canonical)
                    if ref not in saved['provenance']: saved['provenance'].append(ref)
                else: merged[key] = dict(resource=scope.resource,ticker=scope.ticker,identity=identity,record=canonical,provenance=[ref])
    records = []
    for key,value in sorted(merged.items()):
        value['provenance'].sort(key=digest); records.append(value)
    states = {state:sum(c['state']==state for c in coverage) for state in ('complete','empty','unavailable')}
    candle_tickers = {r['ticker'] for r in records if r['resource']=='candles'}
    trade_tickers = {r['ticker'] for r in records if r['resource']=='trades'}
    summary = dict(version='evidence-coverage-v1',candidate_count=len(rebuilt.candidates),
        candle_records=sum(r['resource']=='candles' for r in records),trade_records=sum(r['resource']=='trades' for r in records),
        candidates_with_candles=len(candle_tickers),candidates_without_candles=len(rebuilt.candidates)-len(candle_tickers),
        candidates_with_trades=len(trade_tickers),candidates_without_trades=len(rebuilt.candidates)-len(trade_tickers),
        scope_states=states,resources=list(resources),raw_rows_scanned=scanned)
    artifact_list = sorted(artifacts.values(),key=lambda a:a['object_key'])
    payload = dict(format=FORMAT,artifacts=artifact_list,manifest=manifest_receipt,batch_fingerprint=rebuilt.fingerprint,day=rebuilt.day,
        candidates=json.loads(json.dumps(asdict(rebuilt)))['candidates'],scopes=[asdict(s) for s in plan.scopes],coverage=coverage,records=records,summary=summary)
    if window is not None:payload['close_window']=dict(start=rebuilt.window_start,end=rebuilt.window_end)
    encoded = json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode())>64*1024*1024: raise ValueError('Dataset too large; explicit partitioning required')
    return PreparedDataset(encoded,digest(payload),json.dumps(summary,sort_keys=True),json.dumps(artifact_list))


class DatasetStore:
    """Publish outside hosted infrastructure; pool must be explicitly supplied."""
    def __init__(self,pool): self.pool = pool

    def publish(self,stream_key,prepared):
        text_key(stream_key,128)
        payload,summary,artifacts = map(json.loads,(prepared.payload_json,prepared.summary_json,prepared.artifacts_json))
        if (payload.get('format')!=FORMAT or digest(payload)!=prepared.fingerprint or payload['summary']!=summary
                or payload.get('artifacts')!=artifacts or summary.get('version')!='evidence-coverage-v1'):
            raise EvidenceConflict('Prepared dataset integrity mismatch')
        with self.pool.connection() as c:
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
                VALUES(%s,%s,%s,%s) RETURNING id''',(stream_key,prepared.fingerprint,payload['day'],Jsonb(payload))).fetchone()
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

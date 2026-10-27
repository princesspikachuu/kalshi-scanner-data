"""Verified settled inventory, all requested sources or no usable candidate batch.

No sampling, observations, ROI, publication, network fetch or trading occurs here.
"""
from .telemetry import timed,timing,count

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone

from .inventory import digest, inspect_pages, scope_for_job, scopes_for_days, valid_cursor
from .queue import EvidenceConflict, text_key

VERSION = 'settled-inventory-v1'


@dataclass(frozen=True, order=True)
class Evidence:
    job_id: str
    scope_key: str
    source: str
    page_key: str
    row_index: int
    object_key: str
    sha256: str
    byte_length: int

    def receipt(self):
        return dict(object_key=self.object_key, sha256=self.sha256, byte_length=self.byte_length,
                    provider='kalshi', content_type='application/gzip')


@dataclass(frozen=True)
class Candidate:
    ticker: str
    event_ticker: str
    series: str
    close_time: str
    result: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Input:
    scope_key: str
    job_id: str | None
    state: str
    pages: int
    items: int


@dataclass(frozen=True)
class CandidateBatch:
    day: str
    generation: str
    series: tuple[str, ...]
    inputs: tuple[Input, ...]
    candidates: tuple[Candidate, ...] = ()
    rows_scanned: int = 0
    version: str = VERSION

    @property
    def ready(self): return all(i.state in ('complete', 'empty') for i in self.inputs)

    @property
    def fingerprint(self): return digest(asdict(self))


@dataclass(frozen=True)
class WindowBatch(CandidateBatch):
    # Separate subclass preserves the exact fingerprints of all existing v1 batches.
    window_start: str = ''
    window_end: str = ''


class NormalizationLimit(ValueError):
    pass


def _closed(value):
    if not isinstance(value, str): raise EvidenceConflict('Invalid market close time')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None: raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise EvidenceConflict('Invalid market close time') from None


def _payload(scope, page, archives):
    receipt = page['receipt']
    if receipt.get('provider') != 'kalshi' or receipt.get('object_key') != page['object_key']:
        raise EvidenceConflict('Archive reference does not match committed page')
    envelope = archives.read(receipt)  # checksum, byte length, bounded gzip/JSON
    if (not isinstance(envelope, dict) or envelope.get('scope') != asdict(scope)
            or envelope.get('checkpoint') != page['checkpoint']):
        raise EvidenceConflict('Archive envelope does not match committed scope/checkpoint')
    cp, response = page['checkpoint'], envelope.get('response')
    if not isinstance(response, dict) or not isinstance(response.get('markets'), list) or 'cursor' not in response:
        raise EvidenceConflict('Invalid archived market page')
    cursor = valid_cursor('' if response['cursor'] is None else response['cursor'])
    if len(response['markets']) != cp['items'] or cursor != cp['cursor_out'] or cp['availability'] != 'available':
        raise EvidenceConflict('Archive response does not match checkpoint progress')
    return response['markets']


@timed('inventory.normalize')
def normalize_inventory(series, day, generation, attempts, archives, *, max_rows=250000, max_pages=10000, window=None):
    """attempts = iterable of (job, queue.page_evidence(job_id)).

    Exactly one succeeded terminal job is selected per requested scope; multiple
    completed jobs require explicit caller membership selection, never an implicit
    merge of refreshes. Incomplete scopes return a non-ready batch with NO candidate
    rows. Hash/envelope/conflict/limit errors raise rather than returning a subset.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 1000000 or type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise ValueError('Invalid normalization limits')
    if not series or len(series) > 100: raise ValueError('Expected 1..100 series')
    series = tuple(sorted(set(series)))
    scopes = scopes_for_days(series, [day], generation)
    wanted = {s.key: s for s in scopes}
    groups = {key: {} for key in wanted}
    for n, (job, pages) in enumerate(attempts):
        if n >= 2000: raise NormalizationLimit('Too many inventory attempts')
        scope = scope_for_job(job)
        if scope.key not in wanted: continue
        if len(pages) > max_pages: raise NormalizationLimit('Too many inventory pages')
        job_id = str(job['id'])
        state = inspect_pages(scope, pages)
        value = (job['status'], state, pages)
        if job_id in groups[scope.key] and groups[scope.key][job_id] != value:
            raise EvidenceConflict('Repeated job has different inventory evidence')
        groups[scope.key][job_id] = value
    inputs, selected = [], []
    for key, scope in sorted(wanted.items()):
        jobs = groups[key]
        complete = [(jid, v) for jid, v in jobs.items() if v[0] == 'succeeded' and v[1].state in ('complete','empty')]
        if len(complete) > 1:
            raise EvidenceConflict('Select explicit membership among completed inventory jobs')
        if complete:
            jid, (_, state, pages) = complete[0]
            inputs.append(Input(key, jid, state.state, state.pages, state.items))
            selected.append((scope, jid, pages))
        elif not jobs:
            inputs.append(Input(key, None, 'fetch', 0, 0))
        else:
            # Preserve every gap attempt's state instead of inventing a last-success
            # watermark. Sorted identifiers make output independent of input order.
            for jid, (status, state, _) in sorted(jobs.items()):
                label = ('unavailable' if state.state == 'unavailable' else
                         'failed' if status in ('failed','cancelled','succeeded') else 'resume')
                inputs.append(Input(key, jid, label, state.pages, state.items))
    start = datetime.combine(date.fromisoformat(day), time(), timezone.utc)
    end = start + timedelta(days=1)
    batch_type=CandidateBatch
    extra={}
    if window is not None:
        left,right=map(_closed,window)
        if not start<=left<right<=end:raise ValueError('Close window must be within the UTC day')
        start,end=left,right;batch_type=WindowBatch
        extra=dict(window_start=start.isoformat(),window_end=end.isoformat())
    base = dict(day=day, generation=generation, series=series, inputs=tuple(inputs),**extra)
    batch = batch_type(**base)
    if not batch.ready: return batch
    seen, candidates, rows_scanned, pages_scanned = {}, {}, 0, 0
    for scope, jid, pages in selected:
        for page in sorted(pages, key=lambda p: p['page_key']):
            pages_scanned += 1
            if pages_scanned > max_pages: raise NormalizationLimit('Too many inventory pages')
            rows = _payload(scope, page, archives)
            for index, row in enumerate(rows):
                rows_scanned += 1
                if rows_scanned > max_rows: raise NormalizationLimit('Too many inventory rows')
                if not isinstance(row, dict): raise EvidenceConflict('Invalid archived market row')
                ticker, event = text_key(row.get('ticker')), text_key(row.get('event_ticker'))
                closed = _closed(row.get('close_time'))
                if row.get('series_ticker', scope.series) != scope.series:
                    raise EvidenceConflict('Market series does not match inventory scope')
                identity = (event, scope.series, closed)
                # Check identity across ALL rows, even outside the target day, so
                # moved close times cannot make a conflicting duplicate disappear.
                previous = seen.setdefault(ticker, identity)
                if previous != identity: raise EvidenceConflict('Conflicting market identity')
                result = row.get('result')
                if not start <= closed < end or result not in ('yes','no'): continue
                receipt = page['receipt']
                ref = Evidence(jid,scope.key,scope.source,page['page_key'],index,
                               receipt['object_key'],receipt['sha256'],receipt['byte_length'])
                if ticker in candidates:
                    saved, refs = candidates[ticker]
                    if saved != result: raise EvidenceConflict('Conflicting settled market outcomes')
                    refs.add(ref)
                else: candidates[ticker] = (result, {ref})
    normalized = []
    for ticker, (result, refs) in sorted(candidates.items()):
        event, scoped_series, closed = seen[ticker]
        normalized.append(Candidate(ticker,event,scoped_series,closed.isoformat().replace('+00:00','Z'),
                                    result,tuple(sorted(refs))))
    return batch_type(**base, candidates=tuple(normalized), rows_scanned=rows_scanned)

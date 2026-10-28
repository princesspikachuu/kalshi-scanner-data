"""Incremental inventory planning and one-page worker steps; no hosted runner.

Inventory completion proves traversal only, never quote coverage or dataset
publication. A provider/transport must be injected explicitly; nothing starts on import.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as day_time, timezone
import hashlib
import json
import math
import re
import time

from .queue import EvidenceConflict
from .telemetry import count


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Scope:
    series: str
    source: str
    day: str | None
    generation: str

    def __post_init__(self):
        if not isinstance(self.series, str) or not re.fullmatch(r'[A-Z0-9_-]{1,64}', self.series):
            raise ValueError('Invalid series')
        if not isinstance(self.generation, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.generation):
            raise ValueError('Invalid collection generation')
        if self.source == 'historical':
            if self.day is not None: raise ValueError('Historical index has no close-date filter')
        elif self.source == 'recent':
            if not isinstance(self.day, str) or date.fromisoformat(self.day).isoformat() != self.day:
                raise ValueError('Invalid UTC close day')
        else:
            raise ValueError('Invalid inventory source')

    @property
    def key(self): return digest(asdict(self))

    def parameters(self): return {'collector': 'inventory-v1', 'scope': asdict(self)}

    def request(self, cursor):
        cursor = valid_cursor(cursor)
        args = {'series_ticker': self.series, 'limit': 1000}
        if cursor: args['cursor'] = cursor
        if self.source == 'recent':
            start = int(datetime.combine(date.fromisoformat(self.day), day_time(), timezone.utc).timestamp())
            args.update(min_close_ts=start-1, max_close_ts=start+86400)
        return ('/historical/markets' if self.source == 'historical' else '/markets', args)


def valid_cursor(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid pagination cursor')
    return value


def scopes_for_days(series, days, generation):
    """One historical index per series, plus each recent day; never route by close
    time against a settlement cutoff. Both sources may contain the day's markets.
    """
    if not days: return []
    if len(series) > 100 or len(days) > 366:
        raise ValueError('Plan too large')
    return list(dict.fromkeys(s for ticker in series for s in
                [Scope(ticker, 'historical', None, generation)] +
                [Scope(ticker, 'recent', day, generation) for day in days]))


def scope_for_job(job):
    p = job['parameters']
    if not isinstance(p, dict) or set(p) != {'collector', 'scope'} or p['collector'] != 'inventory-v1':
        raise ValueError('Not an inventory job')
    return Scope(**p['scope'])


def page_key(scope, sequence): return f'{getattr(scope, "page_namespace", "inventory")}/{scope.key}/{sequence:06d}'


@dataclass(frozen=True)
class Traversal:
    next_cursor: str = ''
    pages: int = 0
    items: int = 0
    state: str = 'partial'


def inspect_pages(scope, pages):
    """Reject missing, reordered, cyclic or foreign evidence; no partial success.
    Does not read objects: checks committed metadata, not current bucket health.
    """
    cursor, total, terminal = '', 0, 'partial'
    seen = {''}
    for i, page in enumerate(sorted(pages, key=lambda p: p['page_key'])):
        cp = page['checkpoint']
        if (terminal != 'partial' or page['page_key'] != page_key(scope, i)
                or cp.get('scope') != scope.key or cp.get('sequence') != i
                or cp.get('cursor_in') != cursor):
            raise EvidenceConflict('Invalid inventory checkpoint chain')
        cursor = valid_cursor(cp.get('cursor_out'))
        count = cp.get('items')
        if type(count) is not int or not 0 <= count <= 1000:
            raise EvidenceConflict('Invalid inventory item count')
        status = cp.get('availability')
        if status not in ('available', 'unavailable') or (status == 'unavailable' and (count or cursor)):
            raise EvidenceConflict('Invalid inventory availability')
        total += count
        if status == 'unavailable': terminal = 'unavailable'
        elif not cursor: terminal = 'complete' if total else 'empty'
        elif cursor in seen: raise EvidenceConflict('Repeated inventory cursor')
        seen.add(cursor)
    return Traversal(cursor, len(pages), total, terminal)


def plan(scopes, attempts):
    """attempts: (job, committed pages). Every requested scope gets a status.
    Reuse complete evidence from any attempt in this exact generation. Unavailable,
    failed and unfinished work stay explicit gaps, never zero-observation success.
    """
    index = {}
    for job, pages in attempts:
        scope = scope_for_job(job)
        state = inspect_pages(scope, pages).state
        if state in ('complete', 'empty') and job['status'] != 'succeeded':
            state = 'failed' if job['status'] in ('failed', 'cancelled') else 'resume'
        elif state == 'partial':
            state = 'failed' if job['status'] in ('failed', 'cancelled', 'succeeded') else 'resume'
        index.setdefault(scope.key, []).append((state, job['id']))
    result = []
    for scope in dict.fromkeys(scopes):
        choices = index.get(scope.key, [])
        # A failed later refresh never erases already completed immutable evidence.
        choice = next((v for v in choices if v[0] in ('complete', 'empty')), None)
        state, job_id = choice or (choices[-1] if choices else ('fetch', None))
        result.append({'scope': asdict(scope), 'state': state, 'job_id': job_id})
    return result


@dataclass(frozen=True)
class ProviderPage:
    payload: dict
    availability: str = 'available'
    origin_receipt: dict | None = None


class ProviderDeferred(Exception):
    """A batch was attempted; retry individually without recording provider failure."""


class ProviderFailure(Exception):
    def __init__(self, code, retry=True, delay=30, cooldown=None):
        if code not in ('provider_timeout', 'provider_rate_limit', 'provider_unavailable', 'provider_invalid'):
            raise ValueError('Invalid provider failure code')
        if type(retry) is not bool or type(delay) is not int or not 1 <= delay <= 3600:
            raise ValueError('Invalid provider retry')
        cooldown = delay if cooldown is None else cooldown
        if type(cooldown) is not int or not delay <= cooldown <= 2**40:
            raise ValueError('Invalid shared provider cooldown')
        self.code, self.retry, self.delay, self.cooldown = code, retry, delay, cooldown
        super().__init__(code)


def inventory_page(scope, payload, availability):
    if availability == 'unavailable':
        if payload != {}: raise ProviderFailure('provider_invalid', retry=False)
        return [], ''
    if not isinstance(payload, dict) or not isinstance(payload.get('markets'), list) or 'cursor' not in payload:
        raise ProviderFailure('provider_invalid', retry=False)
    rows = payload['markets']
    raw_cursor = '' if payload['cursor'] is None else payload['cursor']
    try: cursor = valid_cursor(raw_cursor)
    except ValueError: raise ProviderFailure('provider_invalid', retry=False) from None
    if len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise ProviderFailure('provider_invalid', retry=False)
    return rows, cursor


class InventoryWorker:
    """Call step for an already-claimed job, repeatedly while pending/throttled.
    provider.fetch(scope, cursor, timeout_seconds) performs exactly ONE read;
    no internal retries, sleeps or trading. The shared budget charges every read.
    archives is an ArchiveStore; queue is ResearchQueue; clock is monotonic.
    """
    def __init__(self, queue, archives, provider, budget, *, endpoint_cost, max_pages=10000, clock=time.monotonic,
                 scope_loader=scope_for_job, page_parser=inventory_page):
        if type(endpoint_cost) is not int or endpoint_cost < 1 or type(max_pages) is not int or not 1 <= max_pages <= 10000:
            raise ValueError('Invalid worker limits')
        self.queue, self.archives, self.provider, self.budget = queue, archives, provider, budget
        self.cost, self.max_pages, self.clock = endpoint_cost, max_pages, clock
        self.scope_loader, self.page_parser = scope_loader, page_parser
        self.reuse=None

    def archive_page(self,scope,checkpoint,response):
        if response.origin_receipt is not None:
            from .projections import archive_reused
            return archive_reused(scope,checkpoint,response,self.archives)
        return self.archives.upload('kalshi', {'scope': asdict(scope), 'checkpoint': checkpoint, 'response': response.payload}),checkpoint

    def step(self, job, *, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid monotonic deadline')
        scope = self.scope_loader(job)
        job_id, token = job['id'], job['lease_token']
        self.queue.heartbeat(job_id, token)
        state = inspect_pages(scope, self.queue.pages(job_id))
        if state.state != 'partial':
            self.queue.finish(job_id, token)
            return {'state': state.state, 'retry_after': 0}
        try:
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            if state.pages >= self.max_pages: raise ProviderFailure('provider_invalid', retry=False)
            cached = getattr(self.provider,'cached',lambda *_:None)(scope,state.next_cursor)
            if cached is None and self.reuse is not None:cached=self.reuse.lookup(job,scope,state.next_cursor)
            if cached is not None:count('provider.cached_page',1)
            delay = 0 if cached is not None else self.budget.take(self.cost)
            if delay: return {'state': 'throttled', 'retry_after': delay}
            remaining = deadline-self.clock()
            if remaining <= 0: raise ProviderFailure('provider_timeout')
            response = cached if cached is not None else self.provider.fetch(scope, state.next_cursor, min(10, remaining))
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            if not isinstance(response, ProviderPage) or response.availability not in ('available', 'unavailable'):
                raise ProviderFailure('provider_invalid', retry=False)
            payload = response.payload
            rows, cursor = self.page_parser(scope, payload, response.availability)
            cp = {'scope': scope.key, 'sequence': state.pages, 'cursor_in': state.next_cursor,
                  'cursor_out': cursor, 'items': len(rows), 'availability': response.availability}
            page = {'page_key': page_key(scope, state.pages), 'checkpoint': cp}
            # Validate continuation/cycles before upload or checkpoint.
            try: next_state = inspect_pages(scope, self.queue.pages(job_id) + [page])
            except EvidenceConflict: raise ProviderFailure('provider_invalid', retry=False) from None
            self.queue.heartbeat(job_id, token)
            receipt,cp = self.archive_page(scope,cp,response)
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            self.queue.checkpoint(job_id, token, page['page_key'], receipt, cp)
            if self.reuse is not None:self.reuse.remember(job,scope,cp,receipt)
            getattr(self.provider,'acknowledge',lambda *_:None)(scope)
            if next_state.state != 'partial': self.queue.finish(job_id, token)
            return {'state': next_state.state, 'retry_after': 0}
        except ProviderDeferred:
            return {'state':'partial','retry_after':0}
        except ProviderFailure as error:
            if error.code in ('provider_rate_limit', 'provider_unavailable'): self.budget.defer(error.cooldown)
            self.queue.fail(job_id, token, error.code, retry=error.retry, delay_seconds=error.delay)
            return {'state': 'failed', 'retry_after': error.delay if error.retry else 0}
        # All unexpected I/O/integrity errors propagate: no false success or unsafe
        # exception text saved. The bounded DB lease permits a later reclaim.

"""Durable research queue primitives. No exchange calls or trading operations.

Every worker write checks both its unexpired DB lease and a unique attempt token.
A stale process may still finish a network request; it cannot commit progress.
Keep remote fetch/upload work OUTSIDE these short database transactions.
"""
import json
import re
from .telemetry import timed,timing,count

from uuid import UUID, uuid4
from psycopg.types.json import Jsonb

ASSETS = frozenset(('weather', 'btc', 'eth', 'crypto', 'sports', 'weather_daily', 'financial_daily'))


class LeaseLost(RuntimeError):
    pass


class EvidenceConflict(ValueError):
    pass


def bounded_json(value):
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    if len(json.dumps(value, allow_nan=False).encode()) > 16384:
        raise ValueError('Object too large')
    return Jsonb(value)


def text_key(value, maximum=256):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid key')
    return value


def lease_seconds(value):
    if type(value) is not int or not 10 <= value <= 600:
        raise ValueError('Lease must be between 10 and 600 seconds')
    return value


class ResearchQueue:
    """Uses a dedicated worker pool; the API pool need not run collection jobs."""
    def __init__(self, pool):
        self.pool = pool

    def enqueue(self, asset, parameters, idempotency_key, max_attempts=5):
        if asset not in ASSETS or type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError('Invalid job')
        text_key(idempotency_key)
        payload = bounded_json(parameters)
        with self.pool.connection() as c:
            row = c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,max_attempts)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING *''',
                (uuid4(), asset, payload, idempotency_key, max_attempts)).fetchone()
            if row is None:
                row = c.execute('SELECT * FROM research_job WHERE idempotency_key=%s', (idempotency_key,)).fetchone()
                if row['asset'] != asset or row['parameters'] != parameters or row['max_attempts'] != max_attempts:
                    raise EvidenceConflict('Idempotency key belongs to different job parameters')
            return row

    def claim(self, seconds=120, *, job_id=None, collector=None, campaign_id=None, asset=None):
        seconds = lease_seconds(seconds)
        job_id=None if job_id is None else UUID(str(job_id))
        if collector is not None:text_key(collector,64)
        campaign_id=None if campaign_id is None else str(UUID(str(campaign_id)))
        if asset is not None and asset not in ASSETS:raise ValueError("Invalid asset")
        with self.pool.connection() as c:
            # The coordinator only schedules independently fenced child work.
            # Losing its process/DB connection is not a failed evidence attempt.
            c.execute('''UPDATE research_job SET status='queued',attempts=greatest(0,attempts-1),
                lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp()
                WHERE status='running' AND lease_expires_at<=clock_timestamp()
                AND parameters->>'collector'='campaign-v1' ''')
            # Expired attempts at the limit become terminal instead of being stranded.
            c.execute('''UPDATE research_job SET status='failed',finished_at=clock_timestamp(),
                error_code='attempts_exhausted',lease_token=NULL,lease_expires_at=NULL
                WHERE status='running' AND lease_expires_at<=clock_timestamp() AND attempts>=max_attempts''')
            return c.execute('''WITH candidate AS (
                SELECT id FROM research_job WHERE attempts<max_attempts
                AND (%s::uuid IS NULL OR id=%s::uuid)
                AND (%s::text IS NULL OR parameters->>'collector'=%s::text)
                AND (%s::text IS NULL OR parameters->>'campaign_id'=%s::text)
                AND (%s::text IS NULL OR asset=%s::text) AND
                ((status='queued' AND available_at<=clock_timestamp()) OR
                 (status='running' AND lease_expires_at<=clock_timestamp()))
                ORDER BY available_at,created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED
                ) UPDATE research_job j SET status='running',attempts=attempts+1,
                lease_token=%s,lease_expires_at=clock_timestamp()+%s*interval '1 second',
                started_at=COALESCE(started_at,clock_timestamp()),finished_at=NULL,error_code=NULL
                FROM candidate WHERE j.id=candidate.id RETURNING j.*''', (job_id,job_id,collector,collector,campaign_id,campaign_id,asset,asset,uuid4(), seconds)).fetchone()

    def claim_many(self,job_ids,seconds=120):
        seconds=lease_seconds(seconds);ids=[UUID(str(i)) for i in job_ids]
        if not 1<=len(ids)<=100 or len(set(ids))!=len(ids):raise ValueError('Invalid claim batch')
        with self.pool.connection() as c:
            return c.execute('''WITH chosen AS (
                SELECT id FROM research_job WHERE id=ANY(%s::uuid[]) AND attempts<max_attempts
                AND ((status='queued' AND available_at<=clock_timestamp()) OR
                     (status='running' AND lease_expires_at<=clock_timestamp()))
                ORDER BY id FOR UPDATE SKIP LOCKED)
                UPDATE research_job j SET status='running',attempts=attempts+1,lease_token=gen_random_uuid(),
                lease_expires_at=clock_timestamp()+%s*interval '1 second',
                started_at=coalesce(started_at,clock_timestamp()),finished_at=NULL,error_code=NULL
                FROM chosen WHERE j.id=chosen.id RETURNING j.*''',(ids,seconds)).fetchall()

    @timed('queue.cached_batch')
    def complete_cached(self,entries):
        """Atomically fence and save already-verified terminal candle projections."""
        if not 1<=len(entries)<=100:raise ValueError('Invalid checkpoint batch')
        ids=[UUID(str(e['job']['id'])) for e in entries]
        if len(set(ids))!=len(ids):raise EvidenceConflict('Duplicate batch job')
        artifacts={};pages=[]
        for e in entries:
            receipt=e['receipt'];cp=e['checkpoint'];job=e['job']
            if (cp.get('sequence')!=0 or cp.get('cursor_in')!='' or cp.get('cursor_out')!=''
                    or cp.get('availability')!='available'
                    or cp.get('projection',{}).get('format')!='candle-batch-projection-v1'):
                raise EvidenceConflict('Nonterminal cached projection')
            bounded_json(cp);text_key(e['page_key'])
            row={k:receipt[k] for k in ('object_key','sha256','provider','content_type','byte_length')}
            row.update(job_id=str(job['id']),metadata=receipt.get('metadata',{}))
            previous=artifacts.setdefault(row['object_key'],row)
            if any(previous[k]!=row[k] for k in ('sha256','provider','content_type','byte_length')):
                raise EvidenceConflict('Conflicting batch archive')
            pages.append(dict(job_id=str(job['id']),page_key=e['page_key'],object_key=receipt['object_key'],checkpoint=cp))
        with self.pool.connection() as c:
            owned=c.execute('''SELECT id,lease_token FROM research_job WHERE id=ANY(%s::uuid[])
                AND status='running' AND lease_expires_at>clock_timestamp() ORDER BY id FOR UPDATE''',(ids,)).fetchall()
            tokens={str(r['id']):str(r['lease_token']) for r in owned}
            if tokens!={str(e['job']['id']):str(e['job']['lease_token']) for e in entries}:raise LeaseLost('Cached batch lease changed')
            c.execute('''INSERT INTO raw_archive(object_key,sha256,provider,job_id,content_type,byte_length,metadata)
                SELECT object_key,sha256,provider,job_id::uuid,content_type,byte_length,metadata
                FROM jsonb_to_recordset(%s) AS a(object_key text,sha256 text,provider text,job_id text,content_type text,byte_length bigint,metadata jsonb)
                ON CONFLICT(object_key) DO NOTHING''',(Jsonb(list(artifacts.values())),))
            saved=c.execute('SELECT object_key,sha256,provider,content_type,byte_length FROM raw_archive WHERE object_key=ANY(%s::text[])',(list(artifacts),)).fetchall()
            fields=('object_key','sha256','provider','content_type','byte_length')
            if {r['object_key']:r for r in saved}!={k:{f:v[f] for f in fields} for k,v in artifacts.items()}:raise EvidenceConflict('Archive registry conflict')
            c.execute('''INSERT INTO collection_page(job_id,page_key,object_key,checkpoint)
                SELECT job_id::uuid,page_key,object_key,checkpoint FROM jsonb_to_recordset(%s)
                AS p(job_id text,page_key text,object_key text,checkpoint jsonb) ON CONFLICT(job_id,page_key) DO NOTHING''',(Jsonb(pages),))
            saved=c.execute('SELECT job_id,page_key,object_key,checkpoint FROM collection_page WHERE job_id=ANY(%s::uuid[])',(ids,)).fetchall()
            actual={str(r['job_id']):{**r,'job_id':str(r['job_id'])} for r in saved}
            if len(saved)!=len(pages) or actual!={p['job_id']:p for p in pages}:raise EvidenceConflict('Cached checkpoint conflict')
            c.execute('''UPDATE research_job SET status='succeeded',progress=jsonb_build_object('completed_pages',1),
                finished_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL WHERE id=ANY(%s::uuid[])''',(ids,))

    @staticmethod
    def _owned(c, job_id, token):
        row = c.execute('''SELECT * FROM research_job WHERE id=%s AND lease_token=%s
            AND status='running' AND lease_expires_at>clock_timestamp() FOR UPDATE''',
            (UUID(str(job_id)), UUID(str(token)))).fetchone()
        if row is None:
            raise LeaseLost('Collection lease expired, replaced or cancelled')
        return row

    @timed('queue.heartbeat')
    def heartbeat(self, job_id, token, seconds=120):
        seconds = lease_seconds(seconds)
        with self.pool.connection() as c:
            self._owned(c, job_id, token)
            c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()+%s*interval '1 second' WHERE id=%s", (seconds, job_id))

    @timed('queue.checkpoint')
    def checkpoint(self, job_id, token, page_key, archive, checkpoint):
        """Call only after immutable object upload + checksum verification succeeded.

        Archive references and page cursor are committed atomically. Replaying the
        same page is harmless; different evidence for that page is rejected. This
        is a per-job page checkpoint, NOT proof of complete time-range coverage.
        """
        text_key(page_key)
        text_key(archive['object_key'], 1024)
        text_key(archive['provider'], 64)
        text_key(archive['content_type'], 128)
        if not re.fullmatch('[0-9a-f]{64}', archive['sha256']):
            raise ValueError('Invalid checksum')
        if type(archive['byte_length']) is not int or archive['byte_length'] < 0:
            raise ValueError('Invalid byte length')
        checkpoint_payload = bounded_json(checkpoint)
        metadata = bounded_json(archive.get('metadata', {}))
        with self.pool.connection() as c:
            self._owned(c, job_id, token)
            c.execute('''INSERT INTO raw_archive(object_key,sha256,provider,job_id,content_type,byte_length,metadata)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(object_key) DO NOTHING''',
                (archive['object_key'], archive['sha256'], archive['provider'], job_id,
                 archive['content_type'], archive['byte_length'], metadata))
            saved = c.execute('SELECT * FROM raw_archive WHERE object_key=%s', (archive['object_key'],)).fetchone()
            for field in ('sha256', 'provider', 'content_type', 'byte_length'):
                if saved[field] != archive[field]:
                    raise EvidenceConflict('Archive key already refers to different evidence')
            c.execute('''INSERT INTO collection_page(job_id,page_key,object_key,checkpoint)
                VALUES(%s,%s,%s,%s) ON CONFLICT(job_id,page_key) DO NOTHING''',
                (job_id, page_key, archive['object_key'], checkpoint_payload))
            saved = c.execute('SELECT * FROM collection_page WHERE job_id=%s AND page_key=%s', (job_id, page_key)).fetchone()
            if saved['object_key'] != archive['object_key'] or saved['checkpoint'] != checkpoint:
                raise EvidenceConflict('Page already committed with different evidence')
            c.execute('''UPDATE research_job SET progress=jsonb_build_object('completed_pages',
                (SELECT count(*) FROM collection_page WHERE job_id=%s)) WHERE id=%s''', (job_id, job_id))
            return saved

    def pages_owned(self,job_id,token):
        """One read verifies current ownership and returns the page chain."""
        with self.pool.connection() as c:
            rows=c.execute('''SELECT p.page_key,p.object_key,p.checkpoint,p.completed_at
                FROM research_job j LEFT JOIN collection_page p ON p.job_id=j.id
                WHERE j.id=%s AND j.lease_token=%s AND j.status='running'
                    AND j.lease_expires_at>clock_timestamp() ORDER BY p.completed_at,p.page_key''',
                (UUID(str(job_id)),UUID(str(token)))).fetchall()
        if not rows:raise LeaseLost('Page owner expired, replaced or cancelled')
        return [r for r in rows if r['page_key'] is not None]

    def pages(self, job_id):
        with self.pool.connection() as c:
            return c.execute('SELECT page_key,object_key,checkpoint,completed_at FROM collection_page WHERE job_id=%s ORDER BY completed_at,page_key',
                             (UUID(str(job_id)),)).fetchall()

    def get(self, job_id):
        with self.pool.connection() as c:
            return c.execute('SELECT * FROM research_job WHERE id=%s', (UUID(str(job_id)),)).fetchone()

    def page_evidence(self, job_id):
        """Read committed pages with receipts; no lease or mutable job writes.

        Consumers must still verify archive bytes and envelope identity. A receipt
        from this join is a reference, not a claim that the object still exists.
        """
        with self.pool.connection() as c:
            return c.execute('''SELECT p.page_key,p.object_key,p.checkpoint,p.completed_at,
                jsonb_build_object('object_key',a.object_key,'sha256',a.sha256,
                    'provider',a.provider,'content_type',a.content_type,
                    'byte_length',a.byte_length,'metadata',a.metadata) AS receipt
                FROM collection_page p JOIN raw_archive a ON a.object_key=p.object_key
                WHERE p.job_id=%s ORDER BY p.page_key''', (UUID(str(job_id)),)).fetchall()

    def finish(self, job_id, token):
        """Worker signals completion; dataset publication is a separate transaction."""
        with self.pool.connection() as c:
            self._owned(c, job_id, token)
            c.execute("""UPDATE research_job SET status='succeeded',finished_at=clock_timestamp(),
                lease_token=NULL,lease_expires_at=NULL WHERE id=%s""", (job_id,))

    def fail(self, job_id, token, code, retry=True, delay_seconds=30):
        if not isinstance(code, str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}', code):
            raise ValueError('Use a safe error code, never an exception or provider response')
        if type(retry) is not bool or type(delay_seconds) is not int or not 0 <= delay_seconds <= 3600:
            raise ValueError('Invalid retry')
        with self.pool.connection() as c:
            row = self._owned(c, job_id, token)
            requeue = retry and row['attempts'] < row['max_attempts']
            c.execute('''UPDATE research_job SET status=%s,error_code=%s,lease_token=NULL,lease_expires_at=NULL,
                available_at=clock_timestamp()+%s*interval '1 second',
                finished_at=CASE WHEN %s THEN NULL ELSE clock_timestamp() END WHERE id=%s''',
                ('queued' if requeue else 'failed', code, delay_seconds, requeue, job_id))

    def defer_rate_limited(self,job_id,token,delay_seconds):
        """A paced retry is not a failed collection attempt; preserve every page."""
        if type(delay_seconds) is not int or not 1<=delay_seconds<=3600:raise ValueError('Invalid rate retry')
        with self.pool.connection() as c:
            row=self._owned(c,job_id,token)
            progress=dict(row['progress'])
            repeats=min(30,int(progress.get('rate_limit_retries',0)))
            wait=max(delay_seconds,min(30,2**min(repeats,5)))
            progress['rate_limit_retries']=repeats+1
            c.execute("""UPDATE research_job SET status='queued',attempts=attempts-1,
                error_code='provider_rate_limit',lease_token=NULL,lease_expires_at=NULL,
                available_at=clock_timestamp()+%s*interval '1 second',progress=%s WHERE id=%s""",
                (wait,Jsonb(progress),job_id))
            return wait

    def cancel(self, job_id):
        with self.pool.connection() as c:
            return c.execute("""UPDATE research_job SET status='cancelled',finished_at=clock_timestamp(),
                lease_token=NULL,lease_expires_at=NULL WHERE id=%s AND status IN ('queued','running') RETURNING id""",
                (UUID(str(job_id)),)).fetchone() is not None

    def yield_job(self,job_id,token,delay_seconds=0):
        """Healthy progress/wait is not a failed attempt. Release the lease for restart.

        Crashes and provider failures still consume attempts. Only fenced owners
        can refund the current healthy claim; completed pages remain immutable.
        """
        if type(delay_seconds) is not int or not 0<=delay_seconds<=3600:raise ValueError('Invalid yield delay')
        with self.pool.connection() as c:
            self._owned(c,job_id,token)
            c.execute("""UPDATE research_job SET status='queued',attempts=attempts-1,
                lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp()+%s*interval '1 second'
                WHERE id=%s""",(delay_seconds,job_id))

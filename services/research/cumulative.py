"""Immutable category reports from newest complete evidence for each close instant.

Partial rolling windows overlay only their own half-open UTC coverage. An empty
newer window supersedes older candidates inside that window; outside history stays.
No provider calls, dataset edits, sampling, or request-time report computation.
"""
from .telemetry import timed,timing,count

from collections import defaultdict
from datetime import datetime,timezone
import heapq
import json
from uuid import uuid4

from psycopg.types.json import Jsonb
from .inventory import digest
from .normalize import _closed
from .queue import ResearchQueue,EvidenceConflict
from .reports import ReportStore,PreparedReport,prepare_report_stream,SERIES,MAX_REPORT_BYTES,report_fingerprint

VERSION='category-window-selection-v1'
MAX_WINDOWS=50000


def select_windows(rows):
    """Sweep close-time coverage; greatest immutable dataset ID wins overlaps."""
    events=defaultdict(list)
    seen=set()
    for index,row in enumerate(rows):
        if index>=MAX_WINDOWS:raise ValueError('Category window limit exceeded; partition explicitly')
        identifier=row['dataset_id'];start,end=_closed(row['start_at']),_closed(row['end_at'])
        if type(identifier) is not int or identifier<1 or start>=end:raise ValueError('Invalid category coverage')
        key=(identifier,start,end)
        if key in seen:continue
        seen.add(key);events[start].append((identifier,1));events[end].append((identifier,-1))
    points=sorted(events);active=defaultdict(int);heap=[];result=[]
    for index,left in enumerate(points[:-1]):
        for identifier,change in events[left]:
            active[identifier]+=change
            if change>0:heapq.heappush(heap,-identifier)
        while heap and active[-heap[0]]<=0:heapq.heappop(heap)
        if not heap:continue
        identifier=-heap[0];right=points[index+1]
        a,b=left.isoformat(),right.isoformat()
        if result and result[-1]['dataset_id']==identifier and result[-1]['end_at']==a:
            result[-1]['end_at']=b
        else:result.append(dict(dataset_id=identifier,start_at=a,end_at=b))
        if len(result)>10000:raise ValueError('Category segment limit exceeded; partition explicitly')
    if len({r['dataset_id'] for r in result})>3661:raise ValueError('Category dataset limit exceeded; partition explicitly')
    return result


@timed('category.build')
def prepare_category(asset,datasets,manifest,revision,*,publication_complete=True):
    if asset not in SERIES or type(revision) is not int or revision<1:raise ValueError('Invalid category revision')
    windows=select_windows(manifest)
    if windows!=manifest:raise ValueError('Category manifest must be canonical')
    by_dataset=defaultdict(list)
    for row in windows:by_dataset[row['dataset_id']].append((_closed(row['start_at']),_closed(row['end_at'])))
    def include(identifier,candidate):
        close=_closed(candidate['close_time'])
        return any(start<=close<end for start,end in by_dataset[identifier])
    expected=set(by_dataset);loaded=set()
    def checked():
        for d in datasets:
            if d['id'] not in expected:raise EvidenceConflict('Unexpected category input')
            loaded.add(d['id']);yield d
        if loaded!=expected:raise EvidenceConflict('Missing category input')
    prepared=prepare_report_stream(asset,checked(),latest_ids=None,candidate_filter=include)
    payload=json.loads(prepared.payload_json)
    payload['selection']={'version':VERSION,'windows':manifest,'revision':revision}
    if not publication_complete:payload['publication']=dict(complete=False,revision=revision)
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode())+len(prepared.observations_json.encode())>MAX_REPORT_BYTES:raise ValueError('Category result exceeds bounded report size')
    return PreparedReport(encoded,report_fingerprint(encoded,prepared.observations_json),prepared.observations_json)


class CategoryReports:
    def __init__(self,pool):self.pool=pool;self.queue=ResearchQueue(pool)

    @staticmethod
    def enqueue(c,asset,campaign_id):
        c.execute('''INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
            VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO NOTHING''',
            (uuid4(),'category/'+str(campaign_id),asset,Jsonb({'collector':'category-report-v1'})))

    def _snapshot(self,c,asset):
        # One MVCC statement freezes both version revision and source windows.
        row=c.execute('''WITH sources AS MATERIALIZED (
            SELECT m.dataset_id,d.start_at,d.end_at,latest.id AS result_id,
                COALESCE((latest.report->'publication'->>'complete')::boolean,true) AS complete
            FROM research_campaign r JOIN LATERAL (SELECT id,report FROM research_result
                WHERE stream_key='campaign-'||replace(r.id::text,'-','') ORDER BY id DESC LIMIT 1) latest ON true
            JOIN research_result_dataset m ON m.result_id=latest.id
            JOIN research_dataset ds ON ds.id=m.dataset_id
            JOIN research_campaign_day d ON d.campaign_id=r.id AND d.day=ds.day
            WHERE r.asset=%s)
            SELECT (SELECT max(result_id) FROM sources) AS revision,
                (SELECT bool_and(complete) FROM sources) AS complete,
                (SELECT jsonb_agg(w) FROM (SELECT DISTINCT dataset_id,start_at,end_at
                    FROM sources ORDER BY dataset_id,start_at,end_at LIMIT 50001) w) AS windows''',(asset,)).fetchone()
        if not row['revision'] or not row['windows']:raise EvidenceConflict('No completed category coverage')
        return dict(revision=row['revision'],windows=select_windows(row['windows']),complete=row['complete'])

    def step(self,job):
        with self.pool.connection() as c:
            owned=self.queue._owned(c,job['id'],job['lease_token'])
            snapshot=owned['progress'].get('category_snapshot')
            if snapshot is None:
                snapshot=self._snapshot(c,job['asset'])
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',
                    (Jsonb({'category_snapshot':snapshot}),job['id']))
        ids=sorted({r['dataset_id'] for r in snapshot['windows']})
        def inputs():
            for identifier in ids:
                with self.pool.connection() as c:
                    row=c.execute("SELECT COALESCE((payload->>'uncompressed_bytes')::bigint,octet_length(payload::text)) AS bytes FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                    if not row or row['bytes']>64*1024*1024:raise EvidenceConflict('Category input missing or too large')
                    data=c.execute("SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                yield data
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        prepared=prepare_category(job['asset'],inputs(),snapshot['windows'],snapshot['revision'],publication_complete=snapshot.get('complete',True))
        # _save serializes each stream and refuses an older frozen revision.
        ReportStore(self.pool)._save('category-'+job['asset'],job['asset'],prepared,
                                    minimum_revision=snapshot['revision'])
        self.queue.finish(job['id'],job['lease_token'])

    def run_once(self):
        job=self.queue.claim(seconds=600,collector='category-report-v1')
        if job is None:return False
        try:self.step(job)
        except ValueError:self.queue.fail(job['id'],job['lease_token'],'category_report_blocked',retry=False)
        return True

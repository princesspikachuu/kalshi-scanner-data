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
import tempfile
from .report_inputs import report_dataset
from uuid import uuid4

from psycopg.types.json import Jsonb
from .inventory import digest
from . import report_jobs
from .normalize import _closed
from .queue import ResearchQueue,EvidenceConflict
from .reports import ReportStore,PreparedReport,prepare_report_stream,SERIES,MAX_REPORT_BYTES,report_fingerprint

VERSION='category-window-selection-v1'
MAX_WINDOWS=50000


def select_windows(rows):
    """Sweep close-time coverage; greatest immutable dataset ID wins overlaps."""
    cohorts=[r for r in rows if r.get('cohort')]
    if cohorts:
        legacy=select_windows([r for r in rows if not r.get('cohort')])
        additions={(r['dataset_id'],str(r['start_at']),str(r['end_at'])) for r in cohorts}
        return sorted(legacy+[dict(dataset_id=i,start_at=a,end_at=b,cohort=True) for i,a,b in additions],
                      key=lambda r:(r['dataset_id'],r['start_at'],r['end_at']))
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
    if any(r.get('cohort') for r in manifest):
        # Add rerun cohorts; choose one newest version for each actual market/day.
        # Spool raw inputs to disk rather than retaining a year of payloads in RAM.
        owners={}
        with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as saved:
            for d in checked():
                for candidate in report_dataset(d)['payload']['candidates']:
                    if include(d['id'],candidate):
                        key=(candidate['close_time'][:10],candidate['ticker'])
                        owners[key]=max(d['id'],owners.get(key,0))
                saved.write(json.dumps(d,default=str,separators=(',',':'))+'\n')
            saved.seek(0)
            prepared=prepare_report_stream(asset,(json.loads(line) for line in saved),latest_ids=None,
                candidate_filter=lambda identifier,c:include(identifier,c) and owners.get((c['close_time'][:10],c['ticker']))==identifier)
    else:prepared=prepare_report_stream(asset,checked(),latest_ids=None,candidate_filter=include)
    payload=json.loads(prepared.payload_json)
    payload['selection']={'version':VERSION,'windows':manifest,'revision':revision}
    if not publication_complete:payload['publication']=dict(complete=False,revision=revision)
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded)+len(prepared.observations_json)>MAX_REPORT_BYTES:raise ValueError('Category result exceeds bounded report size')
    return PreparedReport(encoded,report_fingerprint(encoded,prepared.observations_json),prepared.observations_json)


class CategoryReports:
    def __init__(self,pool):self.pool=pool;self.queue=ResearchQueue(pool)

    def recover_latest(self,asset):
        # A failed old category job must not hide already-published campaign
        # data. Create a new fenced build; never rewrite its frozen snapshot.
        with self.pool.connection() as c:
            row=c.execute('''SELECT max((SELECT id FROM research_result
                WHERE stream_key='campaign-'||replace(r.id::text,'-','') ORDER BY id DESC LIMIT 1)) AS revision
                FROM research_campaign r WHERE asset=%s''',(asset,)).fetchone()
            if row['revision']:
                self.enqueue(c,asset,'bounded-publication-v1/'+asset,source_revision=row['revision'])

    @staticmethod
    def enqueue(c,asset,campaign_id,*,source_revision=None,urgent=True):
        c.execute('''INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
            VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO NOTHING''',
            (uuid4(),'category/'+str(campaign_id),asset,Jsonb({'collector':'category-report-v1','urgent':urgent,**({'source_revision':source_revision} if source_revision is not None else {})})))

    def _snapshot(self,c,asset):
        # One MVCC statement freezes both version revision and source windows.
        row=c.execute('''WITH sources AS MATERIALIZED (
            SELECT m.dataset_id,d.start_at,d.end_at,(r.config ? 'collection_limit') AS cohort,latest.id AS result_id,
                COALESCE((latest.report->'publication'->>'complete')::boolean,true) AS complete
            FROM research_campaign r JOIN LATERAL (SELECT id,report FROM research_result
                WHERE stream_key='campaign-'||replace(r.id::text,'-','') ORDER BY id DESC LIMIT 1) latest ON true
            JOIN research_result_dataset m ON m.result_id=latest.id
            JOIN research_dataset ds ON ds.id=m.dataset_id
            JOIN research_campaign_day d ON d.campaign_id=r.id AND d.day=ds.day
            WHERE r.asset=%s)
            SELECT (SELECT max(result_id) FROM sources) AS revision,
                (SELECT bool_and(complete) FROM sources) AS complete,
                (SELECT jsonb_agg(w) FROM (SELECT DISTINCT dataset_id,start_at,end_at,cohort
                    FROM sources ORDER BY dataset_id,start_at,end_at LIMIT 50001) w) AS windows''',(asset,)).fetchone()
        if not row['revision'] or not row['windows']:raise EvidenceConflict('No completed category coverage')
        return dict(revision=row['revision'],windows=select_windows(row['windows']),complete=row['complete'])

    def step(self,job):
        if report_jobs.defer_unfrozen(self.queue,job,'category-'+job['asset'],'category_snapshot',urgent=job['parameters'].get('urgent',True)):return
        with self.pool.connection() as c:
            owned=self.queue._owned(c,job['id'],job['lease_token'])
            snapshot=owned['progress'].get('category_snapshot')
            if snapshot is None:
                snapshot=self._snapshot(c,job['asset'])
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',
                    (Jsonb({'category_snapshot':snapshot}),job['id']))
        with self.pool.connection() as c:
            current=c.execute("SELECT id,report->'selection'->>'revision' AS revision FROM research_result WHERE stream_key=%s ORDER BY id DESC LIMIT 1",('category-'+job['asset'],)).fetchone()
        if current and int(current['revision'] or 0)>=snapshot['revision']:
            # The newer sealed report already covers this immutable source
            # revision. A recovered frozen job need not rebuild it again.
            self.queue.finish(job['id'],job['lease_token']);return
        ids=sorted({r['dataset_id'] for r in snapshot['windows']})
        days=set()
        def inputs():
            for identifier in ids:
                with self.pool.connection() as c:
                    row=c.execute("SELECT COALESCE((payload->>'uncompressed_bytes')::bigint,octet_length(payload::text)) AS bytes FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                    if not row or row['bytes']>64*1024*1024:raise EvidenceConflict('Category input missing or too large')
                    data=c.execute("SELECT id,fingerprint,payload,day FROM research_dataset WHERE id=%s",(identifier,)).fetchone()
                days.add(str(data['day']))
                yield data
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        prepared=prepare_category(job['asset'],inputs(),snapshot['windows'],snapshot['revision'],publication_complete=snapshot.get('complete',True))
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        # _save serializes each stream and refuses an older frozen revision.
        ReportStore(self.pool)._save('category-'+job['asset'],job['asset'],prepared,
                                    minimum_revision=snapshot['revision'])
        with self.pool.connection() as c:
            self.queue._owned(c,job['id'],job['lease_token'])
            report_jobs.coalesce(c,job,snapshot['revision'])
        self.queue.finish(job['id'],job['lease_token'])
        print(json.dumps(dict(event='category_days_published',asset=job['asset'],days=len(days),
            revision=snapshot['revision'],complete=snapshot.get('complete',True))),flush=True)

    def run_once(self,*,campaign_id=None,asset=None):
        job=self.queue.claim(seconds=600,collector='category-report-v1',campaign_id=campaign_id,asset=asset)
        if job is None:return False
        try:self.step(job)
        except ValueError as error:
            print(json.dumps(dict(event='category_publication_blocked',asset=job['asset'],reason=str(error)[:200])),flush=True)
            self.queue.fail(job['id'],job['lease_token'],'category_report_blocked',retry=False)
        return True

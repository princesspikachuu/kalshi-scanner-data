"""Durable UTC date-range collection and opt-in hourly rolling refresh.

No service, scheduler or network request starts on import. Publication means RAW
coverage, not quote eligibility, research completion or a trading recommendation.
"""
from .telemetry import timed,timing,count
import json

from datetime import date,datetime,time,timedelta,timezone
from dataclasses import replace
from uuid import UUID,uuid4,uuid5
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from psycopg.types.json import Jsonb
from .availability import eligible_series
from .datasets import DatasetStore,DatasetLimit,CollectionInterrupted,prepare_dataset
from .evidence import build_scopes,plan_from_receipt
from .inventory import digest,scopes_for_days
from .normalize import Candidate,Input,Evidence,WindowBatch,normalize_inventory,batch_from_dict
from .queue import ResearchQueue,EvidenceConflict,LeaseLost
from .reports import MINUTES,SERIES,ReportStore
from .sample import select_preview_candidates

UTC=timezone.utc
MAX_DAYS=3660
ACTIVE_DAYS=7
JOB_BATCH_ROWS=64
JOB_BATCH_BYTES=128*1024


def utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError('Timezone-aware instant required')
    return value.astimezone(UTC)


def sections(start,end):
    start,end=utc(start),utc(end)
    if not start<end or end-start>timedelta(days=MAX_DAYS):raise ValueError('Select up to 3660 days')
    result=[]
    while start<end:
        stop=min(end,datetime.combine(start.date()+timedelta(days=1),time(),UTC))
        result.append(dict(day=start.date().isoformat(),start_at=start,end_at=stop))
        start=stop
    return result


def daily_due(now,local_time):
    if (not isinstance(local_time,str) or len(local_time)!=5 or local_time[2]!=':'
            or not local_time.replace(':','').isascii() or not local_time.replace(':','').isdigit()):
        raise ValueError('Select HH:MM Pacific time')
    hour,minute=map(int,local_time.split(':'))
    if hour>23 or minute>59:raise ValueError('Select HH:MM Pacific time')
    local=utc(now).astimezone(ZoneInfo('America/Los_Angeles'))
    candidate=local.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
    if candidate.astimezone(UTC)<=now:candidate+=timedelta(days=1)
    # Nonexistent spring-forward times normalize to the following valid instant.
    return candidate.astimezone(UTC)


def configuration(asset):
    if asset not in SERIES:raise ValueError('Unsupported research category')
    return dict(version='campaign-v1',series=sorted(SERIES[asset]),resources=['candles','trades'],
        lookback_seconds=max(MINUTES[asset])*60+120)


class CampaignStore:
    def __init__(self,pool,*,collection_limit=None):
        self.pool=pool;self.collection_limit=collection_limit

    def create(self,asset,start_date,end_date,request_key,*,now=None,refresh_existing=False):
        """Date controls are inclusive UTC dates; today's section ends at creation."""
        now=utc(now or datetime.now(UTC))
        if type(refresh_existing) is not bool:raise ValueError('Invalid refresh selection')
        start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
        if start.isoformat()!=start_date or end.isoformat()!=end_date or start>end or end>now.date():raise ValueError('Invalid close dates')
        left=datetime.combine(start,time(),UTC)
        right=min(datetime.combine(end+timedelta(days=1),time(),UTC),now)
        with self.pool.connection() as c:return self._create(c,asset,left,right,request_key,'backfill',dict(start_date=start_date,end_date=end_date,refresh_existing=refresh_existing))

    def _create(self,c,asset,start,end,key,mode,request_spec):
        config=configuration(asset);days=sections(start,end)
        if self.collection_limit is not None:config['collection_limit']=self.collection_limit
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('Invalid request key')
        # Serialize key races; retries return the original frozen request, including today's cutoff.
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,91029))',(key,))
        old=c.execute('SELECT * FROM research_campaign WHERE request_key=%s',(key,)).fetchone()
        if old:
            if old['asset']!=asset or old['mode']!=mode or old['request_spec']!=request_spec:
                raise EvidenceConflict('Request key belongs to another range')
            return str(old['id'])
        identifier,job=uuid4(),uuid4()
        c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,max_attempts)
            VALUES(%s,%s,%s,%s,5)''',(job,asset,Jsonb(dict(collector='campaign-v1',campaign_id=str(identifier))),f'campaign/{identifier}'))
        c.execute('''INSERT INTO research_campaign(id,job_id,asset,mode,start_at,end_at,config,config_hash,request_key,request_spec)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identifier,job,asset,mode,start,end,Jsonb(config),digest(config),key,Jsonb(request_spec)))
        c.execute('''INSERT INTO research_campaign_day(campaign_id,day,start_at,end_at)
            SELECT %s,day::date,start_at::timestamptz,end_at::timestamptz FROM jsonb_to_recordset(%s) AS d(day text,start_at text,end_at text)''',
            (identifier,Jsonb([dict(day=d['day'],start_at=d['start_at'].isoformat(),end_at=d['end_at'].isoformat()) for d in days])))
        return str(identifier)

    def _refresh_time(self,c,asset):
        row=c.execute("SELECT progress->>'local_time' AS local_time FROM research_job WHERE idempotency_key=%s",('refresh-schedule/'+asset,)).fetchone()
        return row['local_time'] if row else None

    def _save_refresh_time(self,c,asset,local_time):
        c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at,progress)
            VALUES(%s,%s,%s,%s,'succeeded',clock_timestamp(),%s)
            ON CONFLICT(idempotency_key) DO UPDATE SET progress=EXCLUDED.progress''',
            (uuid4(),asset,Jsonb(dict(collector='refresh-schedule-v1')),'refresh-schedule/'+asset,Jsonb(dict(local_time=local_time))))

    def set_refresh(self,asset,enabled,*,local_time=None):
        configuration(asset)
        if type(enabled) is not bool:raise ValueError('Invalid refresh preference')
        if local_time is not None:daily_due(datetime.now(UTC),local_time)
        with self.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,91030))',(asset,))
            c.execute('SELECT asset FROM research_refresh WHERE asset=%s FOR UPDATE',(asset,))
            current=self._refresh_time(c,asset)
            selected=local_time or current or '03:00'
            due=daily_due(datetime.now(UTC),selected)
            self._save_refresh_time(c,asset,selected)
            c.execute('''INSERT INTO research_refresh(asset,enabled,next_due) VALUES(%s,%s,%s)
                ON CONFLICT(asset) DO UPDATE SET enabled=EXCLUDED.enabled,
                next_due=CASE WHEN NOT research_refresh.enabled OR %s THEN EXCLUDED.next_due ELSE research_refresh.next_due END''',
                (asset,enabled,due,local_time is not None or current is None))
        return self.refresh(asset)

    def refresh(self,asset):
        configuration(asset)
        with self.pool.connection() as c:
            row=c.execute('SELECT asset,enabled,next_due FROM research_refresh WHERE asset=%s',(asset,)).fetchone() or dict(asset=asset,enabled=False,next_due=None)
            row.update(interval_seconds=86400,local_time=self._refresh_time(c,asset) or '03:00',timezone='America/Los_Angeles')
            latest=c.execute("SELECT id::text AS id FROM research_campaign WHERE asset=%s AND mode='rolling' ORDER BY created_at DESC,id DESC LIMIT 1",(asset,)).fetchone()
            row['latest_campaign_id']=latest['id'] if latest else None
            return row

    def schedule_due(self,*,now=None):
        """One exact preceding-24h reconciliation per local calendar day.

        Missed runs coalesce. DST follows Pacific wall time; overlapping work must
        finish first. The legacy interval column is not used by this scheduler.
        """
        now=utc(now or datetime.now(UTC)).replace(microsecond=0);created=[]
        with self.pool.connection() as c:
            due=c.execute("""SELECT * FROM research_refresh WHERE enabled AND (next_due<=%s OR NOT EXISTS(
                SELECT 1 FROM research_job WHERE idempotency_key='refresh-schedule/'||research_refresh.asset))
                ORDER BY asset FOR UPDATE SKIP LOCKED""",(now,)).fetchall()
            for row in due:
                local_time=self._refresh_time(c,row['asset'])
                if local_time is None:
                    # Existing hourly preferences migrate without creating an extra run.
                    local_time='03:00';self._save_refresh_time(c,row['asset'],local_time)
                    c.execute('UPDATE research_refresh SET next_due=%s WHERE asset=%s',(daily_due(now,local_time),row['asset']))
                    continue
                if row['next_due']>now:continue
                active=c.execute("""SELECT 1 FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                    WHERE r.asset=%s AND r.mode='rolling' AND j.status IN ('queued','running') LIMIT 1""",(row['asset'],)).fetchone()
                if active:continue
                bucket=now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
                key=f"auto-daily/{row['asset']}/{bucket}"
                created.append(self._create(c,row['asset'],now-timedelta(hours=24),now,key,'rolling',dict(day=bucket)))
                c.execute('UPDATE research_refresh SET next_due=%s WHERE asset=%s',(daily_due(now,local_time),row['asset']))
        return created

    def get(self,identifier):
        with self.pool.connection() as c:
            row=c.execute('''SELECT r.id,r.asset,r.mode,r.start_at,r.end_at,r.created_at,j.status,j.error_code,
                (SELECT result_id::text FROM research_campaign_result cr WHERE cr.campaign_id=r.id) AS result_id,
                count(d.*)::integer AS total_sections,count(d.dataset_id)::integer AS completed_sections
                FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                JOIN research_campaign_day d ON d.campaign_id=r.id WHERE r.id=%s
                GROUP BY r.id,j.status,j.error_code''',(UUID(str(identifier)),)).fetchone()
            if row:
                row['id']=str(row['id'])
                row['analyzed_sections']=c.execute('''SELECT count(*)::integer AS n FROM research_campaign_day d
                    WHERE d.campaign_id=%s AND d.dataset_id IS NOT NULL AND (
                        EXISTS(SELECT 1 FROM research_summary s WHERE s.dataset_id=d.dataset_id AND s.summary->'resources' ? 'trades')
                        OR EXISTS(SELECT 1 FROM research_job a WHERE a.idempotency_key='analysis-source/'||d.dataset_id::text AND a.status='succeeded'))''',(UUID(str(identifier)),)).fetchone()['n']
                result=c.execute('''SELECT rr.id::text AS id,rr.report->'publication' AS publication FROM research_result rr
                    WHERE rr.stream_key=%s ORDER BY rr.id DESC LIMIT 1''',('campaign-'+UUID(str(identifier)).hex,)).fetchone()
                row['reported_sections']=0;row['report_complete']=False
                if result:
                    row['result_id']=row['result_id'] or result['id']
                    publication=result['publication'] or dict(complete=True,reported_sections=row['completed_sections'])
                    row['reported_sections']=publication['reported_sections'];row['report_complete']=publication['complete']
                sample=c.execute('''SELECT id::text AS id,report->'publication' AS publication FROM research_result
                    WHERE stream_key=%s ORDER BY id DESC LIMIT 1''',('campaign-sample-'+UUID(str(identifier)).hex,)).fetchone()
                prior=c.execute('''SELECT (report->'publication'->>'reported_sections')::integer AS days
                    FROM research_result WHERE stream_key=%s
                    AND published_at<=clock_timestamp()-interval '5 minutes'
                    ORDER BY id DESC LIMIT 1''',('campaign-'+UUID(str(identifier)).hex,)).fetchone()
                row['report_days_last_five_minutes']=max(0,row['reported_sections']-(prior['days'] or 0 if prior else 0))
                row['sample_result_id']=sample['id'] if sample else None
                row['sample_reported_sections']=sample['publication'].get('reported_sections',0) if sample else 0
                detail=c.execute('''SELECT count(*)::integer AS work_items,
                    count(*) FILTER(WHERE status='succeeded')::integer AS completed_work_items,
                    coalesce(sum((progress->>'completed_pages')::bigint),0)::bigint AS saved_pages,
                    min(available_at) FILTER(WHERE status='queued' AND available_at>clock_timestamp()) AS retry_at
                    FROM research_job WHERE id IN (SELECT job_id FROM research_campaign_work WHERE campaign_id=%s)
                    AND parameters->'scope'->>'resource' IS DISTINCT FROM 'trades' ''',(UUID(str(identifier)),)).fetchone()
                row.update(detail)
                failure=c.execute('''SELECT error_code FROM research_job WHERE id IN
                    (SELECT job_id FROM research_campaign_work WHERE campaign_id=%s)
                    AND parameters->'scope'->>'resource' IS DISTINCT FROM 'trades'
                    AND error_code IS NOT NULL ORDER BY finished_at DESC NULLS LAST,id LIMIT 1''',(UUID(str(identifier)),)).fetchone()
                row['last_work_error']=failure['error_code'] if failure else None
            return row

    def next_wait(self):
        """Wake promptly for durable parent/report retry times, with a 5s idle cap."""
        with self.pool.connection() as c:
            row=c.execute('''SELECT min(extract(epoch FROM
                (CASE WHEN status='running' THEN lease_expires_at ELSE available_at END)-clock_timestamp())) AS seconds
                FROM research_job WHERE status IN ('queued','running') AND attempts<max_attempts
                AND parameters->>'collector' IN ('campaign-v1','category-report-v1','campaign-preview-v1')''').fetchone()
        return 5 if row['seconds'] is None else max(.1,min(5,float(row['seconds'])))

    def analysis_status(self):
        with self.pool.connection() as c:
            rows=c.execute("""WITH sources AS (
                SELECT r.asset,ds.day,ds.id,
                    (s.summary->'resources' ? 'trades' OR a.status='succeeded' OR EXISTS(
                        SELECT 1 FROM research_campaign_day cd JOIN research_summary cs ON cs.dataset_id=cd.dataset_id
                        WHERE cd.campaign_id=r.id AND cd.day=ds.day AND cs.summary->'resources' ? 'trades')) IS TRUE AS analyzed
                FROM research_dataset ds JOIN research_campaign r ON ds.stream_key IN (
                    'campaign-'||replace(r.id::text,'-',''),'campaign-candles-'||replace(r.id::text,'-',''))
                JOIN research_summary s ON s.dataset_id=ds.id
                LEFT JOIN research_job a ON a.idempotency_key='analysis-source/'||ds.id::text),
                days AS (SELECT asset,day,bool_and(analyzed) AS analyzed FROM sources GROUP BY asset,day)
                SELECT asset,count(*)::integer AS saved_days,count(*) FILTER(WHERE analyzed)::integer AS analyzed_days
                FROM days GROUP BY asset ORDER BY asset""").fetchall()
            collecting=bool(c.execute("""SELECT 1 FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE j.status IN ('queued','running') AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false) LIMIT 1""").fetchone())
            budget=c.execute("SELECT refill_per_second FROM research_read_budget WHERE name='kalshi-read'").fetchone()
        return dict(categories=rows,state='paused for collection' if collecting else 'working through saved data',
                    requests_per_second=budget['refill_per_second'] if budget else None)

    def worker_status(self):
        from .heartbeat import HEARTBEAT_ID,HEARTBEAT_KEY
        with self.pool.connection() as c:
            row=c.execute('''SELECT finished_at AS last_seen,
                finished_at>clock_timestamp()-interval '90 seconds' AS online
                FROM research_job WHERE id=%s AND idempotency_key=%s
                    AND status='succeeded' AND parameters->>'collector'='worker-heartbeat-v1' ''',
                (HEARTBEAT_ID,HEARTBEAT_KEY)).fetchone()
        return dict(state='online' if row and row['online'] else 'waiting',
                    last_seen=row['last_seen'] if row else None,heartbeat_ttl_seconds=90)

    def list(self,asset,*,before=None,limit=26,group=None):
        """Newest-first bounded campaign metadata; no archive/observation reads."""
        if asset!='all':configuration(asset)
        if type(limit) is not int or not 1<=limit<=51:raise ValueError('Invalid campaign limit')
        if before is not None:before=UUID(str(before))
        if group not in (None,'unfinished','finished'):raise ValueError('Invalid collection group')
        direction='ASC' if group=='unfinished' else 'DESC'
        comparison='>' if group=='unfinished' else '<'
        ordering='j.finished_at' if group=='finished' else 'r.created_at'
        boundary='bj.finished_at' if group=='finished' else 'b.created_at'
        predicate="AND j.status='succeeded' AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)" if group=='finished' else "AND j.status<>'succeeded' AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)" if group=='unfinished' else ''
        with self.pool.connection() as c:
            rows=c.execute(f'''WITH chosen AS MATERIALIZED (
                SELECT r.*, {ordering} AS sort_at FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE (%s='all' OR r.asset=%s) {predicate}
                AND (%s::uuid IS NULL OR ({ordering},r.id){comparison}(
                    SELECT {boundary},b.id FROM research_campaign b JOIN research_job bj ON bj.id=b.job_id
                    WHERE b.id=%s AND (%s='all' OR b.asset=%s)))
                ORDER BY {ordering} {direction},r.id {direction} LIMIT %s)
                SELECT r.id::text AS id,r.asset,r.mode,r.start_at,r.end_at,r.created_at,
                    j.status,j.error_code,cr.result_id::text AS result_id,
                    d.total_sections,d.completed_sections
                FROM chosen r JOIN research_job j ON j.id=r.job_id
                LEFT JOIN research_campaign_result cr ON cr.campaign_id=r.id
                CROSS JOIN LATERAL (SELECT count(*)::integer AS total_sections,
                    count(dataset_id)::integer AS completed_sections
                    FROM research_campaign_day WHERE campaign_id=r.id) d
                ORDER BY r.sort_at {direction},r.id {direction}''',(asset,asset,before,before,asset,asset,limit)).fetchall()
            return rows

    def count(self,asset,group):
        if asset!='all':configuration(asset)
        if group not in ('unfinished','finished'):raise ValueError('Invalid collection group')
        with self.pool.connection() as c:
            return c.execute('''SELECT count(*) AS n FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE (%s='all' OR r.asset=%s) AND (j.status='succeeded')=%s
                AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)''',(asset,asset,group=='finished')).fetchone()['n']

    def days(self,identifier,*,after=None,limit=50):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid section limit')
        if after is not None:after=date.fromisoformat(after)
        with self.pool.connection() as c:
            return c.execute('''SELECT day::text AS day,start_at,end_at,dataset_id::text AS dataset_id,
                CASE WHEN dataset_id IS NOT NULL THEN 'collected' WHEN manifest IS NOT NULL THEN 'evidence' WHEN EXISTS(SELECT 1 FROM research_campaign_work w WHERE w.campaign_id=research_campaign_day.campaign_id AND w.day=research_campaign_day.day) THEN 'inventory' ELSE 'pending' END AS stage
                FROM research_campaign_day WHERE campaign_id=%s AND (%s::date IS NULL OR day>%s::date)
                ORDER BY day LIMIT %s''',(UUID(str(identifier)),after,after,limit)).fetchall()

    def control(self,identifier,action):
        if action not in ('pause','resume','remove'):raise ValueError('Invalid collection control')
        with self.pool.connection() as c:
            row=c.execute('SELECT j.* FROM research_campaign r JOIN research_job j ON j.id=r.job_id WHERE r.id=%s FOR UPDATE OF j',(UUID(str(identifier)),)).fetchone()
            if row is None:return False
            if action in ('pause','remove') and row['status'] in ('queued','running'):
                ids=c.execute("""SELECT DISTINCT job_id FROM research_campaign_work WHERE campaign_id=%s
                    UNION SELECT id AS job_id FROM research_job WHERE parameters->>'collector'='campaign-assembly-v1'
                        AND idempotency_key>=%s AND idempotency_key<%s""",
                    (identifier,f'assembly/{identifier}/',f'assembly/{identifier}/zzzz')).fetchall()
                c.execute("""UPDATE research_job SET status='cancelled',finished_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE id=ANY(%s::uuid[]) AND status IN ('queued','running')""",([row['id']]+[r['job_id'] for r in ids],))
            if action=='remove':
                c.execute("UPDATE research_job SET progress=progress||%s WHERE id=%s",(Jsonb({'removed_from_queue':True}),row['id']))
            if action=='resume':
                c.execute("UPDATE research_job SET progress=progress-'removed_from_queue' WHERE id=%s",(row['id'],))
            if action=='resume' and row['status'] in ('cancelled','failed'):
                ids=c.execute("""SELECT DISTINCT job_id FROM research_campaign_work WHERE campaign_id=%s
                    UNION SELECT id AS job_id FROM research_job WHERE parameters->>'collector'='campaign-assembly-v1'
                        AND idempotency_key>=%s AND idempotency_key<%s""",
                    (identifier,f'assembly/{identifier}/',f'assembly/{identifier}/zzzz')).fetchall()
                c.execute("""UPDATE research_job SET status='queued',finished_at=NULL,error_code=NULL,attempts=0,available_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE id=ANY(%s::uuid[]) AND status IN ('cancelled','failed')""",([row['id']]+[r['job_id'] for r in ids],))
            return True


class CampaignWorker:
    """One child HTTP page or one local publication stage per claimed parent step."""
    def __init__(self,pool,archives,inventory_worker,evidence_worker,*,parallelism=1,stop=None,role='combined',preview_limit=100):
        if type(parallelism) is not int or not 1<=parallelism<=16:raise ValueError('Invalid evidence concurrency')
        if role not in ('combined','collector'):raise ValueError('Invalid campaign worker role')
        if preview_limit not in (100,300):raise ValueError("Invalid preview size")
        self.preview_limit=preview_limit
        self.role=role
        self.background_analysis=False;self.analysis_backlog=None
        self.parallelism=parallelism;self._bootstrapped=False
        self.on_work_tick=lambda:None
        self.cancelled=stop.is_set if stop is not None else lambda:False
        self.pool,self.archives=pool,archives
        self.queue=ResearchQueue(pool);self.datasets=DatasetStore(pool)
        self.inventory_worker,self.evidence_worker=inventory_worker,evidence_worker

    def _work_guard(self,parent,*,clock=monotonic):
        """Renew ownership and liveness during long verified local preparation."""
        last=clock()
        def check():
            nonlocal last
            if self.cancelled():return True
            now=clock()
            if now-last>=30:
                self.queue.heartbeat(parent['id'],parent['lease_token'],120 if self.role=='collector' else 600)
                self.on_work_tick()
                last=now
            return False
        return check

    def _insert_job_batch(self,campaign,day,phase,rows,parent):
        # Each bounded batch commits independently. A crash leaves reusable
        # immutable jobs/membership, never an incorrectly complete plan.
        with self.pool.connection() as c:
            self.queue._owned(c,parent['id'],parent['lease_token'])
            c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,max_attempts)
                SELECT id::uuid,asset,parameters,key,5 FROM jsonb_to_recordset(%s) AS r(id text,asset text,parameters jsonb,key text)
                ON CONFLICT(idempotency_key) DO NOTHING''',(Jsonb(rows),))
            c.execute('''INSERT INTO research_campaign_work(campaign_id,day,phase,job_id)
                SELECT %s,%s,%s,unnest(%s::uuid[]) ON CONFLICT DO NOTHING''',
                (campaign['id'],day['day'],phase,[row['id'] for row in rows]))

    @timed('campaign.plan')
    def _jobs(self,campaign,day,phase,scopes,parent):
        rows=[dict(id=str(uuid5(campaign['id'],s.key)),asset=campaign['asset'],parameters=s.parameters(),
            key=f"campaign/{campaign['id']}/{s.key}") for s in scopes]
        print(json.dumps(dict(event='collection_plan_started',asset=campaign['asset'],day=str(day['day']),phase=phase,jobs=len(rows))),flush=True)
        batch=[];size=0;guard=self._work_guard(parent)
        for row in rows:
            length=len(json.dumps(row,separators=(',',':')).encode())
            if length>JOB_BATCH_BYTES:raise DatasetLimit('Single collection job exceeds planning bound')
            if batch and (len(batch)>=JOB_BATCH_ROWS or size+length>JOB_BATCH_BYTES):
                if guard():raise CollectionInterrupted()
                self._insert_job_batch(campaign,day,phase,batch,parent);batch=[];size=0
            batch.append(row);size+=length
        if batch:
            if guard():raise CollectionInterrupted()
            self._insert_job_batch(campaign,day,phase,batch,parent)
        with self.pool.connection() as c:
            self.queue._owned(c,parent['id'],parent['lease_token'])
            if phase=='evidence':c.execute('UPDATE research_campaign_day SET evidence_planned=true WHERE campaign_id=%s AND day=%s',(campaign['id'],day['day']))
        print(json.dumps(dict(event='collection_plan_saved',asset=campaign['asset'],day=str(day['day']),phase=phase,jobs=len(rows))),flush=True)

    def _attempts(self,campaign,day,phase):
        # Bulk metadata reads only at a stage boundary, not once per HTTP page.
        args=(campaign['id'],day['day'],phase)
        with self.pool.connection() as c:
            jobs=c.execute("""SELECT j.* FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s ORDER BY j.id""",args).fetchall()
            pages=c.execute("""SELECT p.job_id,p.page_key,p.object_key,p.checkpoint,p.completed_at,
                jsonb_build_object('object_key',a.object_key,'sha256',a.sha256,'provider',a.provider,
                    'content_type',a.content_type,'byte_length',a.byte_length,'metadata',a.metadata) AS receipt
                FROM research_campaign_work w JOIN collection_page p ON p.job_id=w.job_id
                JOIN raw_archive a ON a.object_key=p.object_key
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s ORDER BY p.page_key""",args).fetchall()
        grouped={j['id']:[] for j in jobs}
        for page in pages:grouped[page['job_id']].append(page)
        return [(j,grouped[j['id']]) for j in jobs]

    def _one(self,campaign,day,phase,worker,deadline,*,resource=None,eligible=None,priority_tickers=None):
        args=(campaign['id'],day['day'],phase,resource,resource,eligible,eligible)
        priority=(list(priority_tickers) if priority_tickers is not None else None,)*2
        cached_ids=([uuid5(campaign['id'],key) for key in worker.provider.cached_scope_keys()]
            if phase=='evidence' and hasattr(worker.provider,'cached_scope_keys') else [])
        with self.pool.connection() as c:
            failed=c.execute("""SELECT 1 FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND (%s::text IS NULL OR j.parameters->'scope'->>'resource'=%s)
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'series'=ANY(%s::text[])) AND j.status IN ('failed','cancelled') LIMIT 1""",args).fetchone()
            if failed:raise EvidenceConflict('Child collection stopped')
            pending=c.execute("""SELECT 1 FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND (%s::text IS NULL OR j.parameters->'scope'->>'resource'=%s)
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'series'=ANY(%s::text[])) AND j.status<>'succeeded' LIMIT 1""",args).fetchone()
            if not pending:return None
            row=c.execute("""SELECT j.id FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND (%s::text IS NULL OR j.parameters->'scope'->>'resource'=%s)
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'series'=ANY(%s::text[])) AND
                ((j.status='queued' AND j.available_at<=clock_timestamp()) OR
                 (j.status='running' AND j.lease_expires_at<=clock_timestamp()))
                AND (%s::text[] IS NULL OR j.parameters->'scope'->>'ticker'=ANY(%s::text[]))
                ORDER BY CASE WHEN j.parameters->'scope'->>'resource'='candles' THEN 0 ELSE 1 END,
                    CASE WHEN j.id=ANY(%s::uuid[]) THEN 0 ELSE 1 END,j.available_at,j.id LIMIT 1""",args+priority+(cached_ids,)).fetchone()
        if row is None:return 5
        job=self.queue.claim(job_id=row['id'])
        if job is None:return 5
        if (phase=='evidence' and hasattr(worker,'prepare_batch') and
                job['parameters']['scope']['resource']=='candles' and job['parameters']['scope']['source']=='recent'):
            with self.pool.connection() as c:
                nearby=c.execute('''SELECT j.* FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                    WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND (%s::text IS NULL OR j.parameters->'scope'->>'resource'=%s)
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'series'=ANY(%s::text[])) AND
                    j.status='queued' AND j.available_at<=clock_timestamp() AND j.attempts<j.max_attempts
                    AND j.parameters->'scope'->>'resource'='candles'
                    AND j.parameters->'scope'->>'source'='recent'
                    AND coalesce((j.progress->>'completed_pages')::integer,0)=0
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'ticker'=ANY(%s::text[]))
                    ORDER BY GREATEST((j.parameters->'scope'->>'end_ts')::bigint,%s::bigint)
                            -LEAST((j.parameters->'scope'->>'start_ts')::bigint,%s::bigint),
                        abs((j.parameters->'scope'->>'start_ts')::bigint+(j.parameters->'scope'->>'end_ts')::bigint-%s::bigint),
                    j.available_at,j.id LIMIT 99''',(*args,*priority,job['parameters']['scope']['end_ts'],
                        job['parameters']['scope']['start_ts'],
                        job['parameters']['scope']['start_ts']+job['parameters']['scope']['end_ts'])).fetchall()
            worker.prepare_batch([job]+nearby)
        jobs=[job]
        # Batch-capable recent candles use the single HTTP path above. Other
        # evidence (including archived candles) overlaps I/O for at most 16 jobs.
        recent_candle=lambda j:(j['parameters']['scope']['resource'],j['parameters']['scope']['source'])==('candles','recent')
        if (phase=='evidence' and self.parallelism>1 and recent_candle(job) and hasattr(worker,'prepare_batch')
                and hasattr(worker.provider,'cached') and worker.provider.cached(worker.scope_loader(job),'') is not None):
            # The batch HTTP request and its immutable receipt already exist.
            # Overlap only cached projections: no concurrent batch mutation or
            # unbudgeted provider call, while PUT/readback/checkpoints still run.
            to_claim=[]
            for neighbor in nearby:
                if len(to_claim)>=self.parallelism-1:break
                scope=worker.scope_loader(neighbor)
                if worker.provider.cached(scope,'') is None:continue
                to_claim.append(neighbor['id'])
            if to_claim:jobs.extend(self.queue.claim_many(to_claim))
        if self.parallelism>1 and (phase=='inventory' or not recent_candle(job)):
            with self.pool.connection() as c:
                nearby=c.execute('''SELECT j.id FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                    WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND (%s::text IS NULL OR j.parameters->'scope'->>'resource'=%s)
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'series'=ANY(%s::text[])) AND
                    j.status='queued' AND j.available_at<=clock_timestamp() AND j.attempts<j.max_attempts
                    AND (%s::text[] IS NULL OR j.parameters->'scope'->>'ticker'=ANY(%s::text[]))
                    AND (%s='inventory' OR NOT (j.parameters->'scope'->>'resource'='candles' AND j.parameters->'scope'->>'source'='recent'))
                    ORDER BY CASE WHEN j.parameters->'scope'->>'resource'='candles' THEN 0 ELSE 1 END,j.available_at,j.id LIMIT %s''',(*args,*priority,phase,self.parallelism-1)).fetchall()
            if nearby:jobs.extend(self.queue.claim_many([row['id'] for row in nearby]))
        if (len(jobs)>1 and phase=='evidence' and recent_candle(job)
                and hasattr(worker,'complete_cached') and worker.complete_cached(jobs)):return 0
        def process(child):
            # A verified queue link still establishes membership. Supplying its
            # known PK prefix avoids scanning every collection's history per page.
            child['_campaign_context']=(str(campaign['id']),day['day'].isoformat())
            result=worker.step(child,deadline=deadline)
            if result['state'] in ('partial','throttled'):
                self.queue.yield_job(child['id'],child['lease_token'],min(3600,result['retry_after']))
            return min(3600,result['retry_after'])
        if len(jobs)==1:return process(job)
        # Every future is joined before releasing the parent; failures never
        # mark unsaved pages successful. Existing leases fence crash recovery.
        with ThreadPoolExecutor(max_workers=self.parallelism) as executor:
            waits=list(executor.map(process,jobs))
        return min(waits)

    def _plan(self,campaign,day):
        manifest=self.archives.read(day['manifest']);raw=manifest['batch']
        if digest(raw)!=manifest['fingerprint']:raise EvidenceConflict('Manifest mismatch')
        batch=batch_from_dict(raw)
        return plan_from_receipt(batch,day['manifest'],campaign['config']['lookback_seconds'],campaign['config']['resources'],selected_tickers=manifest.get('selected_tickers'))

    @timed('campaign.step')
    def step(self,parent,*,deadline):
        identifier=UUID(parent['parameters']['campaign_id'])
        selected=self.oldest_request() if self.role=='collector' else None
        prices_only=bool(selected and selected['price_pending'])
        self.queue.heartbeat(parent['id'],parent['lease_token'],120 if self.role=='collector' else 600)
        with self.pool.connection() as c:
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s AND job_id=%s',(identifier,parent['id'])).fetchone()
            if campaign is None:raise EvidenceConflict('Unknown collection campaign')
            # Finish a bounded window, including detailed trades, before opening
            # more dates. A year of previews must not starve completed days.
            day=c.execute('''WITH pending_assembly AS MATERIALIZED (
                SELECT parameters->>'day' AS day FROM research_job
                WHERE idempotency_key>=%s AND idempotency_key<%s
                    AND parameters->>'collector'='campaign-assembly-v1'
                    AND (parameters->>'kind' IN ('prices','enriched') OR (%s=300 AND parameters->>'kind'='sample')) AND status IN ('queued','running')),
                active_days AS MATERIALIZED (SELECT * FROM research_campaign_day
                    WHERE campaign_id=%s AND dataset_id IS NULL
                        AND (NOT %s OR NOT (%s::jsonb ? day::text)) ORDER BY day DESC LIMIT %s)
                SELECT * FROM active_days
                WHERE (%s='combined' OR NOT EXISTS(SELECT 1 FROM pending_assembly a WHERE a.day=active_days.day::text))
                ORDER BY CASE WHEN %s::jsonb ? day::text THEN 2
                              WHEN %s::jsonb ? day::text THEN %s ELSE %s END,
                    day DESC LIMIT 1''',
                (f'assembly/{identifier}/',f'assembly/{identifier}/zzzz',self.preview_limit,identifier,prices_only,Jsonb(parent['progress'].get('candle_previews',{})),ACTIVE_DAYS if self.role=='collector' else MAX_DAYS,self.role,Jsonb(parent['progress'].get('candle_previews',{})),
                    Jsonb(parent['progress'].get('sample_previews',{})),1 if self.preview_limit==300 else 0,0 if self.preview_limit==300 else 1)).fetchone()
        if day is None:
            if self.role=='collector':
                with self.pool.connection() as c:
                    missing=c.execute('SELECT 1 FROM research_campaign_day WHERE campaign_id=%s AND dataset_id IS NULL LIMIT 1',(identifier,)).fetchone()
                    complete=c.execute('SELECT 1 FROM research_campaign_result WHERE campaign_id=%s',(identifier,)).fetchone()
                if complete:
                    if 'collection_limit' in campaign['config']:
                        # Full-history statistics are independent analysis, not
                        # a prerequisite for declaring this collection complete.
                        self.queue.finish(parent['id'],parent['lease_token']);return 0
                    with self.pool.connection() as c:
                        category=c.execute('SELECT status FROM research_job WHERE idempotency_key=%s',('category/'+str(identifier),)).fetchone()
                    if category and category['status']=='failed':
                        self.queue.fail(parent['id'],parent['lease_token'],'campaign_category_blocked',retry=False);return 0
                    if category and category['status']=='succeeded':
                        self.queue.finish(parent['id'],parent['lease_token']);return 0
                    self.queue.yield_job(parent['id'],parent['lease_token'],1);return 1
                if not missing:self._enqueue_assembly(parent,campaign,None,'final')
                self.queue.yield_job(parent['id'],parent['lease_token'],1);return 1
            try:
                with self.pool.connection() as c:
                    ids=[r['dataset_id'] for r in c.execute('SELECT dataset_id FROM research_campaign_day WHERE campaign_id=%s ORDER BY dataset_id',(identifier,)).fetchall()]
                result=ReportStore(self.pool).publish_campaign(f'campaign-{identifier.hex}',campaign['asset'],ids,
                    publication=dict(complete=True,revision=2*len(ids),reported_sections=len(ids),total_sections=len(ids)))
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('INSERT INTO research_campaign_result VALUES(%s,%s) ON CONFLICT DO NOTHING',(identifier,result))
                    from .cumulative import CategoryReports
                    CategoryReports.enqueue(c,campaign['asset'],identifier,source_revision=result)
                self.queue.finish(parent['id'],parent['lease_token'])
            except ValueError:
                self.queue.fail(parent['id'],parent['lease_token'],'campaign_result_blocked',retry=False)
            return 0
        try:
            if day['manifest'] is None:
                # Immutable complete exact sections may be reused; rolling always refreshes.
                if campaign['mode']=='backfill' and 'collection_limit' not in campaign['config'] and not campaign['request_spec'].get('refresh_existing',False):
                    with self.pool.connection() as c:
                        reused=c.execute('''SELECT d.dataset_id FROM research_campaign_day d JOIN research_campaign r ON r.id=d.campaign_id
                            WHERE r.config_hash=%s AND d.start_at=%s AND d.end_at=%s AND d.dataset_id IS NOT NULL ORDER BY d.dataset_id DESC LIMIT 1''',
                            (campaign['config_hash'],day['start_at'],day['end_at'])).fetchone()
                        if reused:
                            self.queue._owned(c,parent['id'],parent['lease_token'])
                            c.execute('UPDATE research_campaign_day SET dataset_id=%s WHERE campaign_id=%s AND day=%s',(reused['dataset_id'],identifier,day['day']))
                    if reused:
                        with self.pool.connection() as c:
                            from .progressive import ProgressiveReports
                            ProgressiveReports.enqueue(c,identifier,campaign['asset'])
                        self.queue.yield_job(parent['id'],parent['lease_token']);return 0
                eligible,_=eligible_series(campaign['config']['series'],day['end_at'])
                scopes=scopes_for_days(eligible,[day['day'].isoformat()],identifier.hex) if eligible else []
                self._jobs(campaign,day,'inventory',scopes,parent)
                wait=self._one(campaign,day,'inventory',self.inventory_worker,deadline,eligible=eligible)
                if wait is not None:self.queue.yield_job(parent['id'],parent['lease_token'],wait);return wait
                attempts=self._attempts(campaign,day,'inventory')
                batch=normalize_inventory(campaign['config']['series'],day['day'].isoformat(),identifier.hex,attempts,self.archives,
                    window=(day['start_at'].isoformat(),day['end_at'].isoformat()),prelaunch=True)
                if not batch.ready:raise EvidenceConflict('Inventory incomplete')
                selection=None
                if 'collection_limit' in campaign['config']:
                    from .backlog import saved_tickers
                    used=saved_tickers(self.pool,day['day'])
                    selection=[c.ticker for c in select_preview_candidates(
                        [c for c in batch.candidates if c.ticker not in used],limit=300)]
                plan=build_scopes(batch,self.archives,lookback_seconds=campaign['config']['lookback_seconds'],
                    resources=campaign['config']['resources'],selected_tickers=selection)
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('UPDATE research_campaign_day SET manifest=%s WHERE campaign_id=%s AND day=%s',(Jsonb(plan.manifest_receipt()),identifier,day['day']))
                self._jobs(campaign,day,'evidence',plan.scopes,parent)
            else:
                if not day['evidence_planned']:
                    # Recover a crash between manifest persistence and job planning.
                    self._jobs(campaign,day,'evidence',self._plan(campaign,day).scopes,parent)
                sample=() if 'collection_limit' in campaign['config'] else self._sample_tickers(day,parent)
                if sample and self._sample_preview(parent,campaign,day,sample):
                    self.queue.yield_job(parent['id'],parent['lease_token']);return 0
                if self._candle_preview(parent,campaign,day):
                    self.queue.yield_job(parent['id'],parent['lease_token']);return 0
                wait=self._one(campaign,day,'evidence',self.evidence_worker,deadline,
                    resource='candles' if prices_only or day['day'].isoformat() not in parent['progress'].get('candle_previews',{}) else None,
                    priority_tickers=sample if sample and day['day'].isoformat() not in parent['progress'].get('sample_previews',{})
                        and day['day'].isoformat() not in parent.get('_sample_assembly_pending',set()) else None)
                if wait is not None:self.queue.yield_job(parent['id'],parent['lease_token'],wait);return wait
                if self.role=='collector':
                    if prices_only:
                        self.queue.yield_job(parent['id'],parent['lease_token'],1);return 1
                    self._enqueue_assembly(parent,campaign,day,'enriched')
                    self.queue.yield_job(parent['id'],parent['lease_token']);return 0
                plan=self._plan(campaign,day)
                attempts=self._attempts(campaign,day,'evidence')
                def inventory_loader(jid):return self.queue.get(jid),self.queue.page_evidence(jid)
                prepared=prepare_dataset(plan,attempts,self.archives,inventory_loader,cancelled=self._work_guard(parent))
                self.queue.heartbeat(parent['id'],parent['lease_token'],600)
                dataset=self.datasets.publish(f"campaign-{identifier.hex}",prepared)
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('UPDATE research_campaign_day SET dataset_id=%s WHERE campaign_id=%s AND day=%s',(dataset,identifier,day['day']))
                    from .progressive import ProgressiveReports
                    ProgressiveReports.enqueue(c,identifier,campaign['asset'])
                count('campaign.enriched_day_saved.'+campaign['asset'],1)
            self.queue.yield_job(parent['id'],parent['lease_token']);return 0
        except DatasetLimit:
            count('dataset.limit',1)
            self.queue.fail(parent['id'],parent['lease_token'],'campaign_dataset_limit',retry=False);return 0
        except EvidenceConflict:
            self.queue.fail(parent['id'],parent['lease_token'],'campaign_evidence_blocked',retry=False);return 0

    def _enqueue_assembly(self,parent,campaign,day,kind,*,tickers=()):
        """One immutable handoff per date/kind. Never holds the parent during assembly."""
        date_key=day['day'].isoformat() if day else 'final'
        key=f"assembly/{campaign['id']}/{date_key}/{kind}"
        parameters=dict(collector='campaign-assembly-v1',campaign_id=str(campaign['id']),day=date_key,kind=kind,tickers=list(tickers))
        with self.pool.connection() as c:
            self.queue._owned(c,parent['id'],parent['lease_token'])
            row=c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,max_attempts)
                VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                (uuid5(campaign['id'],key),campaign['asset'],Jsonb(parameters),key)).fetchone()
            saved=c.execute('SELECT status,parameters FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()
            if saved['parameters']!=parameters or saved['status'] in ('failed','cancelled'):
                raise EvidenceConflict('Assembly handoff blocked')
        if kind=='sample' and saved['status'] in ('queued','running'):
            parent.setdefault('_sample_assembly_pending',set()).add(date_key)
        return row is not None or saved['status']=='succeeded'

    def _sample_tickers(self,day,parent):
        key=day['day'].isoformat()
        saved=parent['progress'].get('sample_tickers',{})
        if key in saved:return tuple(saved[key])
        manifest=self.archives.read(day['manifest'])
        if manifest.get('format')!='candidate-manifest-v1' or digest(manifest['batch'])!=manifest.get('fingerprint'):
            raise EvidenceConflict('Invalid preview manifest')
        candidates=batch_from_dict(manifest['batch']).candidates
        selected=select_preview_candidates(candidates,limit=self.preview_limit) if len(candidates)>self.preview_limit else ()
        tickers=[c.ticker for c in selected]
        with self.pool.connection() as c:
            owned=self.queue._owned(c,parent['id'],parent['lease_token'])
            progress=owned['progress'];progress.setdefault('sample_tickers',{})[key]=tickers
            c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(progress),parent['id']))
        parent['progress']=progress
        return tuple(tickers)

    def _sample_preview(self,parent,campaign,day,tickers):
        key=day['day'].isoformat()
        if key in parent['progress'].get('sample_previews',{}):return False
        with self.pool.connection() as c:
            state=c.execute("""SELECT count(*) AS n,count(*) FILTER(WHERE j.status='succeeded') AS done
                FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase='evidence'
                    AND j.parameters->'scope'->>'resource'='candles'
                    AND j.parameters->'scope'->>'ticker'=ANY(%s::text[])""",
                (campaign['id'],day['day'],list(tickers))).fetchone()
        if not state['n'] or state['n']!=state['done']:return False
        if self.role=='collector':return self._enqueue_assembly(parent,campaign,day,'sample',tickers=tickers)
        plan=self._plan(campaign,day)
        candles=replace(plan,scopes=tuple(s for s in plan.scopes if s.resource=='candles'))
        attempts=[(j,p) for j,p in self._attempts(campaign,day,'evidence')
            if j['parameters']['scope']['resource']=='candles']
        prepared=prepare_dataset(candles,attempts,self.archives,
            lambda jid:(self.queue.get(jid),self.queue.page_evidence(jid)),sampled_tickers=set(tickers),cancelled=self._work_guard(parent))
        dataset=self.datasets.publish('campaign-sample-'+campaign['id'].hex,prepared)
        with self.pool.connection() as c:
            owned=self.queue._owned(c,parent['id'],parent['lease_token'])
            progress=owned['progress'];progress.setdefault('sample_previews',{})[key]=dataset
            c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(progress),parent['id']))
            from .sample_reports import SampleReports
            SampleReports.enqueue(c,campaign['id'],campaign['asset'])
        parent['progress']=progress
        return True

    def _candle_preview(self,parent,campaign,day):
        key=day['day'].isoformat()
        if key in parent['progress'].get('candle_previews',{}):return False
        with self.pool.connection() as c:
            state=c.execute("""SELECT count(*) AS n,count(*) FILTER(WHERE j.status='succeeded') AS done
                FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase='evidence'
                    AND j.parameters->'scope'->>'resource'='candles'""",(campaign['id'],day['day'])).fetchone()
        if state['n']!=state['done'] or (not state['n'] and self.role=='combined'):return False
        if self.role=='collector':return self._enqueue_assembly(parent,campaign,day,'prices')
        plan=self._plan(campaign,day)
        candles=replace(plan,scopes=tuple(s for s in plan.scopes if s.resource=='candles'))
        attempts=[(j,p) for j,p in self._attempts(campaign,day,'evidence') if j['parameters']['scope']['resource']=='candles']
        prepared=prepare_dataset(candles,attempts,self.archives,lambda jid:(self.queue.get(jid),self.queue.page_evidence(jid)),cancelled=self._work_guard(parent))
        dataset=self.datasets.publish('campaign-candles-'+campaign['id'].hex,prepared)
        with self.pool.connection() as c:
            owned=self.queue._owned(c,parent['id'],parent['lease_token'])
            progress=owned['progress'];progress.setdefault('candle_previews',{})[key]=dataset
            progress['last_price_day_at']=datetime.now(UTC).isoformat()
            c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(progress),parent['id']))
            from .progressive import ProgressiveReports
            ProgressiveReports.enqueue(c,campaign['id'],campaign['asset'])
        count('campaign.price_day_saved.'+campaign['asset'],1)
        return True

    def oldest_request(self):
        with self.pool.connection() as c:
            return c.execute("""SELECT r.id,r.job_id,r.asset,
                    EXISTS(SELECT 1 FROM research_campaign_day d WHERE d.campaign_id=r.id
                        AND d.dataset_id IS NULL
                        AND NOT (coalesce(j.progress->'candle_previews','{}'::jsonb) ? d.day::text)) AS price_pending
                FROM research_campaign r
                JOIN research_job j ON j.id=r.job_id WHERE (j.status IN ('queued','running') OR
                    (j.status='failed' AND j.error_code IN ('attempts_exhausted','campaign_step_failed')))
                AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)
                ORDER BY price_pending DESC,r.created_at,r.id LIMIT 1""").fetchone()

    def _claim_parent(self):
        if self.role=='collector':
            oldest=self.oldest_request()
            return self.queue.claim(seconds=120,job_id=oldest['job_id']) if oldest else None
        # A rate-limit wait on price work must not open a lane for a minutes-long
        # trade assembly. Publish every requested price date before enrichment.
        with self.pool.connection() as c:
            row=c.execute('''WITH candidates AS MATERIALIZED (
                SELECT j.id,j.status,j.available_at,j.lease_expires_at,r.created_at,r.id AS campaign_id,
                    coalesce((j.progress->>'last_price_day_at')::timestamptz,r.created_at) AS turn_at,
                    EXISTS(SELECT 1 FROM research_campaign_day d
                        WHERE d.campaign_id=r.id AND d.dataset_id IS NULL
                        AND NOT (coalesce(j.progress->'candle_previews','{}'::jsonb) ? d.day::text)
                        AND (%s='combined' OR NOT EXISTS(SELECT 1 FROM research_job a
                            WHERE a.idempotency_key='assembly/'||r.id::text||'/'||d.day::text||'/prices'
                            AND a.status IN ('queued','running')))) AS price_pending
                FROM research_job j JOIN research_campaign r ON r.job_id=j.id
                WHERE j.parameters->>'collector'='campaign-v1' AND j.attempts<j.max_attempts
                    AND j.status IN ('queued','running')
                    AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false))
                SELECT id FROM candidates
                WHERE ((status='queued' AND available_at<=clock_timestamp()) OR
                       (status='running' AND lease_expires_at<=clock_timestamp()))
                    AND (price_pending OR NOT EXISTS(SELECT 1 FROM candidates WHERE price_pending))
                ORDER BY CASE WHEN price_pending THEN 0 ELSE 1 END,turn_at,created_at,campaign_id LIMIT 1''',(self.role,)).fetchone()
        return self.queue.claim(seconds=600,job_id=row['id']) if row else None

    def run_once(self,*,deadline):
        from .progressive import ProgressiveReports
        from .sample_reports import SampleReports
        if not self._bootstrapped:
            # One-time recovery of crash-exhausted requests after the fixes.
            # Cancelled/removed requests are never resumed; durable pages stay.
            with self.pool.connection() as c:
                # One-time recovery of coordinator crashes under the former
                # unbounded planner. Explicit evidence failures stay stopped.
                c.execute('''UPDATE research_job p SET status='queued',attempts=0,error_code=NULL,
                    finished_at=NULL,lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp(),
                    progress=progress||jsonb_build_object('planning_recovery_version','bounded-plan-v1')
                    WHERE p.status='failed' AND p.error_code IN ('attempts_exhausted','campaign_step_failed')
                    AND p.parameters->>'collector'='campaign-v1'
                    AND p.progress->>'recovery_version'='2026-10-28-collection-v3'
                    AND p.progress->>'planning_recovery_version' IS DISTINCT FROM 'bounded-plan-v1'
                    AND NOT coalesce((p.progress->>'removed_from_queue')::boolean,false)
                    AND NOT EXISTS(SELECT 1 FROM research_campaign r JOIN research_campaign_work w ON w.campaign_id=r.id
                        JOIN research_job j ON j.id=w.job_id WHERE r.job_id=p.id AND j.status IN ('failed','cancelled'))''')
                recovered=c.execute('''UPDATE research_job SET status='queued',attempts=0,error_code=NULL,
                    finished_at=NULL,lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp(),
                    progress=progress||jsonb_build_object('recovery_version','2026-10-28-collection-v3',
                        'planning_recovery_version','bounded-plan-v1')
                    WHERE status='failed' AND error_code IN ('campaign_dataset_limit','attempts_exhausted','campaign_step_failed')
                    AND parameters->>'collector'='campaign-v1'
                    AND progress->>'recovery_version' IS DISTINCT FROM '2026-10-28-collection-v3'
                    AND NOT coalesce((progress->>'removed_from_queue')::boolean,false)
                    RETURNING id''').fetchall()
                if recovered:
                    c.execute('''UPDATE research_job SET status='queued',attempts=0,error_code=NULL,
                        finished_at=NULL,lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp()
                        WHERE status='failed' AND error_code='attempts_exhausted' AND id IN (
                            SELECT w.job_id FROM research_campaign_work w JOIN research_campaign r ON r.id=w.campaign_id
                            WHERE r.job_id=ANY(%s::uuid[]))''',([r['id'] for r in recovered],))
                # Resume only collections blocked exclusively by rate limits.
                # Bad evidence, user pauses/removals, and other failures stay put.
                c.execute("""UPDATE research_job p SET status='queued',attempts=0,error_code=NULL,
                    finished_at=NULL,lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp(),
                    progress=progress||jsonb_build_object('rate_recovery_version','short-backoff-v1')
                    WHERE p.status='failed' AND p.error_code='campaign_evidence_blocked'
                    AND p.parameters->>'collector'='campaign-v1'
                    AND p.progress->>'rate_recovery_version' IS DISTINCT FROM 'short-backoff-v1'
                    AND NOT coalesce((p.progress->>'removed_from_queue')::boolean,false)
                    AND EXISTS(SELECT 1 FROM research_campaign r JOIN research_campaign_work w ON w.campaign_id=r.id
                        JOIN research_job j ON j.id=w.job_id WHERE r.job_id=p.id
                        AND j.status='failed' AND j.error_code='provider_rate_limit')
                    AND NOT EXISTS(SELECT 1 FROM research_campaign r JOIN research_campaign_work w ON w.campaign_id=r.id
                        JOIN research_job j ON j.id=w.job_id WHERE r.job_id=p.id
                        AND j.status='failed' AND j.error_code IS DISTINCT FROM 'provider_rate_limit')""")
                c.execute("""UPDATE research_job j SET status='queued',attempts=0,error_code=NULL,
                    finished_at=NULL,lease_token=NULL,lease_expires_at=NULL,available_at=clock_timestamp(),
                    progress=progress||jsonb_build_object('rate_recovery_version','short-backoff-v1')
                    WHERE j.status='failed' AND j.error_code='provider_rate_limit'
                    AND j.progress->>'rate_recovery_version' IS DISTINCT FROM 'short-backoff-v1'
                    AND EXISTS(SELECT 1 FROM research_campaign_work w JOIN research_campaign r ON r.id=w.campaign_id
                        JOIN research_job p ON p.id=r.job_id WHERE w.job_id=j.id AND p.status IN ('queued','running')
                        AND NOT coalesce((p.progress->>'removed_from_queue')::boolean,false))""")
            ProgressiveReports(self.pool).bootstrap();SampleReports(self.pool).bootstrap();self._bootstrapped=True
        if self.role=='combined':
            if SampleReports(self.pool).run_once():return True
            if ProgressiveReports(self.pool).run_once():return True
            from .cumulative import CategoryReports
            if CategoryReports(self.pool).run_once():return True
        parent=self._claim_parent()
        if parent is None:
            if self.background_analysis:
                if self.analysis_backlog is None:
                    from .backlog import AnalysisBacklog
                    self.analysis_backlog=AnalysisBacklog(self)
                return self.analysis_backlog.run_once(deadline=deadline)
            return False
        try:self.step(parent,deadline=deadline)
        except CollectionInterrupted:
            self.queue.yield_job(parent['id'],parent['lease_token']);return True
        except LeaseLost:
            # A child can lose its lease while this parent is still owned.
            # Release that reservation so the collector does not idle for ten
            # minutes. A replaced/paused parent remains protected by its token.
            try:self.queue.yield_job(parent['id'],parent['lease_token'],1)
            except LeaseLost:pass
            raise
        except Exception:
            # Release an owned failed attempt immediately. Waiting for the full
            # ten-minute crash lease repeats expensive preparation silently.
            self.queue.fail(parent['id'],parent['lease_token'],'campaign_step_failed',
                delay_seconds=min(300,5*2**min(parent['attempts'],5)))
            raise
        return True

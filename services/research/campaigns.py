"""Durable UTC date-range collection and opt-in hourly rolling refresh.

No service, scheduler or network request starts on import. Publication means RAW
coverage, not quote eligibility, research completion or a trading recommendation.
"""
from .telemetry import timed,timing,count

from datetime import date,datetime,time,timedelta,timezone
from dataclasses import replace
from uuid import UUID,uuid4,uuid5
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from psycopg.types.json import Jsonb
from .datasets import DatasetStore,prepare_dataset
from .evidence import build_scopes,plan_from_receipt
from .inventory import digest,scopes_for_days
from .normalize import Candidate,Input,Evidence,WindowBatch,normalize_inventory
from .queue import ResearchQueue,EvidenceConflict,LeaseLost
from .reports import MINUTES,SERIES,ReportStore

UTC=timezone.utc
MAX_DAYS=3660


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
    def __init__(self,pool):self.pool=pool

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
                result=c.execute('''SELECT rr.id::text AS id,rr.report->'publication' AS publication FROM research_result rr
                    WHERE rr.stream_key=%s ORDER BY rr.id DESC LIMIT 1''',('campaign-'+UUID(str(identifier)).hex,)).fetchone()
                row['reported_sections']=0;row['report_complete']=False
                if result:
                    row['result_id']=row['result_id'] or result['id']
                    publication=result['publication'] or dict(complete=True,reported_sections=row['completed_sections'])
                    row['reported_sections']=publication['reported_sections'];row['report_complete']=publication['complete']
                detail=c.execute('''SELECT count(*)::integer AS work_items,
                    count(*) FILTER(WHERE status='succeeded')::integer AS completed_work_items,
                    coalesce(sum((progress->>'completed_pages')::bigint),0)::bigint AS saved_pages,
                    min(available_at) FILTER(WHERE status='queued' AND available_at>clock_timestamp()) AS retry_at
                    FROM research_job WHERE id IN (SELECT job_id FROM research_campaign_work WHERE campaign_id=%s)''',(UUID(str(identifier)),)).fetchone()
                row.update(detail)
                failure=c.execute('''SELECT error_code FROM research_job WHERE id IN
                    (SELECT job_id FROM research_campaign_work WHERE campaign_id=%s)
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
        predicate="AND j.status='succeeded'" if group=='finished' else "AND j.status<>'succeeded' AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)" if group=='unfinished' else ''
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
                AND (%s OR NOT coalesce((j.progress->>'removed_from_queue')::boolean,false))''',(asset,asset,group=='finished',group=='finished')).fetchone()['n']

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
                ids=c.execute('SELECT DISTINCT job_id FROM research_campaign_work WHERE campaign_id=%s',(identifier,)).fetchall()
                c.execute("""UPDATE research_job SET status='cancelled',finished_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE id=ANY(%s::uuid[]) AND status IN ('queued','running')""",([row['id']]+[r['job_id'] for r in ids],))
            if action=='remove' and row['status']!='succeeded':
                c.execute("UPDATE research_job SET progress=progress||%s WHERE id=%s",(Jsonb({'removed_from_queue':True}),row['id']))
            if action=='resume':
                c.execute("UPDATE research_job SET progress=progress-'removed_from_queue' WHERE id=%s",(row['id'],))
            if action=='resume' and row['status'] in ('cancelled','failed'):
                ids=c.execute('SELECT DISTINCT job_id FROM research_campaign_work WHERE campaign_id=%s',(identifier,)).fetchall()
                c.execute("""UPDATE research_job SET status='queued',finished_at=NULL,error_code=NULL,attempts=0,available_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE id=ANY(%s::uuid[]) AND status IN ('cancelled','failed')""",([row['id']]+[r['job_id'] for r in ids],))
            return True


class CampaignWorker:
    """One child HTTP page or one local publication stage per claimed parent step."""
    def __init__(self,pool,archives,inventory_worker,evidence_worker,*,parallelism=1):
        if type(parallelism) is not int or not 1<=parallelism<=4:raise ValueError('Invalid evidence concurrency')
        self.parallelism=parallelism;self._bootstrapped=False
        self.pool,self.archives=pool,archives
        self.queue=ResearchQueue(pool);self.datasets=DatasetStore(pool)
        self.inventory_worker,self.evidence_worker=inventory_worker,evidence_worker

    def _jobs(self,campaign,day,phase,scopes,parent):
        rows=[dict(id=str(uuid5(campaign['id'],s.key)),asset=campaign['asset'],parameters=s.parameters(),
            key=f"campaign/{campaign['id']}/{s.key}") for s in scopes]
        with self.pool.connection() as c:
            self.queue._owned(c,parent['id'],parent['lease_token'])
            c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,max_attempts)
                SELECT id::uuid,asset,parameters,key,5 FROM jsonb_to_recordset(%s) AS r(id text,asset text,parameters jsonb,key text)
                ON CONFLICT(idempotency_key) DO NOTHING''',(Jsonb(rows),))
            c.execute('''INSERT INTO research_campaign_work(campaign_id,day,phase,job_id)
                SELECT %s,%s,%s,id::uuid FROM jsonb_to_recordset(%s) AS r(id text)
                ON CONFLICT DO NOTHING''',(campaign['id'],day['day'],phase,Jsonb(rows)))
            if phase=='evidence':c.execute('UPDATE research_campaign_day SET evidence_planned=true WHERE campaign_id=%s AND day=%s',(campaign['id'],day['day']))

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

    def _one(self,campaign,day,phase,worker,deadline):
        args=(campaign['id'],day['day'],phase)
        with self.pool.connection() as c:
            failed=c.execute("""SELECT 1 FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND j.status IN ('failed','cancelled') LIMIT 1""",args).fetchone()
            if failed:raise EvidenceConflict('Child collection stopped')
            pending=c.execute("""SELECT 1 FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND j.status<>'succeeded' LIMIT 1""",args).fetchone()
            if not pending:return None
            row=c.execute("""SELECT j.id FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND
                ((j.status='queued' AND j.available_at<=clock_timestamp()) OR
                 (j.status='running' AND j.lease_expires_at<=clock_timestamp()))
                ORDER BY CASE WHEN j.parameters->'scope'->>'resource'='candles' THEN 0 ELSE 1 END,j.available_at,j.id LIMIT 1""",args).fetchone()
        if row is None:return 5
        job=self.queue.claim(job_id=row['id'])
        if job is None:return 5
        if (phase=='evidence' and hasattr(worker,'prepare_batch') and
                job['parameters']['scope']['resource']=='candles' and job['parameters']['scope']['source']=='recent'):
            with self.pool.connection() as c:
                nearby=c.execute('''SELECT j.* FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                    WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND
                    j.status='queued' AND j.available_at<=clock_timestamp() AND j.attempts<j.max_attempts
                    AND j.parameters->'scope'->>'resource'='candles'
                    AND j.parameters->'scope'->>'source'='recent'
                    AND coalesce((j.progress->>'completed_pages')::integer,0)=0
                    ORDER BY j.available_at,j.id LIMIT 99''',args).fetchall()
            worker.prepare_batch([job]+nearby)
        jobs=[job]
        # Batch-capable recent candles use the single HTTP path above. Other
        # evidence (including archived candles) overlaps I/O for at most 4 jobs.
        recent_candle=lambda j:(j['parameters']['scope']['resource'],j['parameters']['scope']['source'])==('candles','recent')
        if phase=='evidence' and self.parallelism>1 and not recent_candle(job):
            with self.pool.connection() as c:
                nearby=c.execute('''SELECT j.id FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                    WHERE w.campaign_id=%s AND w.day=%s AND w.phase=%s AND
                    j.status='queued' AND j.available_at<=clock_timestamp() AND j.attempts<j.max_attempts
                    AND NOT (j.parameters->'scope'->>'resource'='candles' AND j.parameters->'scope'->>'source'='recent')
                    ORDER BY CASE WHEN j.parameters->'scope'->>'resource'='candles' THEN 0 ELSE 1 END,j.available_at,j.id LIMIT %s''',(*args,self.parallelism-1)).fetchall()
            for row in nearby:
                child=self.queue.claim(job_id=row['id'])
                if child is not None:jobs.append(child)
        def process(child):
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
        batch=WindowBatch(**{**raw,'series':tuple(raw['series']),'inputs':tuple(Input(**r) for r in raw['inputs']),
            'candidates':tuple(Candidate(**{**r,'evidence':tuple(Evidence(**e) for e in r['evidence'])}) for r in raw['candidates'])})
        return plan_from_receipt(batch,day['manifest'],campaign['config']['lookback_seconds'],campaign['config']['resources'])

    @timed('campaign.step')
    def step(self,parent,*,deadline):
        identifier=UUID(parent['parameters']['campaign_id'])
        self.queue.heartbeat(parent['id'],parent['lease_token'],600)
        with self.pool.connection() as c:
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s AND job_id=%s',(identifier,parent['id'])).fetchone()
            if campaign is None:raise EvidenceConflict('Unknown collection campaign')
            day=c.execute('''SELECT * FROM research_campaign_day WHERE campaign_id=%s AND dataset_id IS NULL
                ORDER BY CASE WHEN %s::jsonb ? day::text THEN 1 ELSE 0 END,day LIMIT 1''',
                (identifier,Jsonb(parent['progress'].get('candle_previews',{})))).fetchone()
        if day is None:
            try:
                with self.pool.connection() as c:
                    ids=[r['dataset_id'] for r in c.execute('SELECT dataset_id FROM research_campaign_day WHERE campaign_id=%s ORDER BY dataset_id',(identifier,)).fetchall()]
                result=ReportStore(self.pool).publish_campaign(f'campaign-{identifier.hex}',campaign['asset'],ids,
                    publication=dict(complete=True,revision=2*len(ids),reported_sections=len(ids),total_sections=len(ids)))
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('INSERT INTO research_campaign_result VALUES(%s,%s) ON CONFLICT DO NOTHING',(identifier,result))
                    from .cumulative import CategoryReports
                    CategoryReports.enqueue(c,campaign['asset'],identifier)
                self.queue.finish(parent['id'],parent['lease_token'])
            except ValueError:
                self.queue.fail(parent['id'],parent['lease_token'],'campaign_result_blocked',retry=False)
            return 0
        try:
            if day['manifest'] is None:
                # Immutable complete exact sections may be reused; rolling always refreshes.
                if campaign['mode']=='backfill' and not campaign['request_spec'].get('refresh_existing',False):
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
                scopes=scopes_for_days(campaign['config']['series'],[day['day'].isoformat()],identifier.hex)
                self._jobs(campaign,day,'inventory',scopes,parent)
                wait=self._one(campaign,day,'inventory',self.inventory_worker,deadline)
                if wait is not None:self.queue.yield_job(parent['id'],parent['lease_token'],wait);return wait
                attempts=self._attempts(campaign,day,'inventory')
                batch=normalize_inventory(campaign['config']['series'],day['day'].isoformat(),identifier.hex,attempts,self.archives,
                    window=(day['start_at'].isoformat(),day['end_at'].isoformat()))
                if not batch.ready:raise EvidenceConflict('Inventory incomplete')
                plan=build_scopes(batch,self.archives,lookback_seconds=campaign['config']['lookback_seconds'],resources=campaign['config']['resources'])
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('UPDATE research_campaign_day SET manifest=%s WHERE campaign_id=%s AND day=%s',(Jsonb(plan.manifest_receipt()),identifier,day['day']))
                self._jobs(campaign,day,'evidence',plan.scopes,parent)
            else:
                if not day['evidence_planned']:
                    # Recover a crash between manifest persistence and job planning.
                    self._jobs(campaign,day,'evidence',self._plan(campaign,day).scopes,parent)
                if self._candle_preview(parent,campaign,day):
                    self.queue.yield_job(parent['id'],parent['lease_token']);return 0
                wait=self._one(campaign,day,'evidence',self.evidence_worker,deadline)
                if wait is not None:self.queue.yield_job(parent['id'],parent['lease_token'],wait);return wait
                plan=self._plan(campaign,day)
                attempts=self._attempts(campaign,day,'evidence')
                def inventory_loader(jid):return self.queue.get(jid),self.queue.page_evidence(jid)
                prepared=prepare_dataset(plan,attempts,self.archives,inventory_loader)
                self.queue.heartbeat(parent['id'],parent['lease_token'],600)
                dataset=self.datasets.publish(f"campaign-{identifier.hex}",prepared)
                with self.pool.connection() as c:
                    self.queue._owned(c,parent['id'],parent['lease_token'])
                    c.execute('UPDATE research_campaign_day SET dataset_id=%s WHERE campaign_id=%s AND day=%s',(dataset,identifier,day['day']))
                    from .progressive import ProgressiveReports
                    ProgressiveReports.enqueue(c,identifier,campaign['asset'])
            self.queue.yield_job(parent['id'],parent['lease_token']);return 0
        except EvidenceConflict:
            self.queue.fail(parent['id'],parent['lease_token'],'campaign_evidence_blocked',retry=False);return 0

    def _candle_preview(self,parent,campaign,day):
        key=day['day'].isoformat()
        if key in parent['progress'].get('candle_previews',{}):return False
        with self.pool.connection() as c:
            state=c.execute("""SELECT count(*) AS n,count(*) FILTER(WHERE j.status='succeeded') AS done
                FROM research_campaign_work w JOIN research_job j ON j.id=w.job_id
                WHERE w.campaign_id=%s AND w.day=%s AND w.phase='evidence'
                    AND j.parameters->'scope'->>'resource'='candles'""",(campaign['id'],day['day'])).fetchone()
        if not state['n'] or state['n']!=state['done']:return False
        plan=self._plan(campaign,day)
        candles=replace(plan,scopes=tuple(s for s in plan.scopes if s.resource=='candles'))
        attempts=[(j,p) for j,p in self._attempts(campaign,day,'evidence') if j['parameters']['scope']['resource']=='candles']
        prepared=prepare_dataset(candles,attempts,self.archives,lambda jid:(self.queue.get(jid),self.queue.page_evidence(jid)))
        dataset=self.datasets.publish('campaign-candles-'+campaign['id'].hex,prepared)
        with self.pool.connection() as c:
            owned=self.queue._owned(c,parent['id'],parent['lease_token'])
            progress=owned['progress'];progress.setdefault('candle_previews',{})[key]=dataset
            c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(progress),parent['id']))
            from .progressive import ProgressiveReports
            ProgressiveReports.enqueue(c,campaign['id'],campaign['asset'])
        return True

    def run_once(self,*,deadline):
        from .progressive import ProgressiveReports
        if not self._bootstrapped:
            ProgressiveReports(self.pool).bootstrap();self._bootstrapped=True
        if ProgressiveReports(self.pool).run_once():return True
        from .cumulative import CategoryReports
        if CategoryReports(self.pool).run_once():return True
        parent=self.queue.claim(seconds=600,collector='campaign-v1')
        if parent is None:return False
        self.step(parent,deadline=deadline)
        return True

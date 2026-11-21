"""Provider-free consumer of durable dataset handoffs and report jobs.

Only this role expands saved evidence. The collector can fetch the next date
while this process owns an independent assembly lease. No new database grants,
provider quota, or changes to the collected cohort are required.
"""
from dataclasses import replace
from datetime import datetime,timezone
import json
from uuid import UUID
from psycopg.types.json import Jsonb
from .campaigns import CampaignWorker
from .datasets import prepare_dataset,CollectionInterrupted,DatasetLimit,CoverageIncomplete
from .queue import EvidenceConflict,LeaseLost
from .reports import ReportStore
from .progressive import ProgressiveReports
from .sample_reports import SampleReports
from .cumulative import CategoryReports


class ProcessingWorker(CampaignWorker):
    def __init__(self,pool,archives,*,stop=None):
        super().__init__(pool,archives,None,None,stop=stop)
        self._category_recovered=set()

    @staticmethod
    def _active(c,identifier,*,lock=False,allow_finished=False):
        row=c.execute('''SELECT j.* FROM research_campaign r JOIN research_job j ON j.id=r.job_id
            WHERE r.id=%s'''+(' FOR UPDATE OF j' if lock else ''),(identifier,)).fetchone()
        if (row is None or row['status'] not in (('queued','running','succeeded') if allow_finished else ('queued','running'))
                or (row['progress'].get('removed_from_queue') and not allow_finished)):
            raise LeaseLost('Campaign stopped')
        return row

    def _claim_assembly(self,*,prices_only=False):
        selected=self.oldest_request()
        if selected is None:return None
        with self.pool.connection() as c:
            row=c.execute("""SELECT a.id FROM research_job a JOIN research_campaign r
                ON r.id::text=a.parameters->>'campaign_id' JOIN research_job p ON p.id=r.job_id
                WHERE a.idempotency_key>='assembly/' AND a.idempotency_key<'assemblz'
                    AND a.parameters->>'collector'='campaign-assembly-v1'
                    AND r.id=%s AND (NOT %s OR a.parameters->>'kind'='prices')
                    AND a.parameters->>'kind' IN ('prices','enriched','sample')
                    AND a.attempts<a.max_attempts AND p.status IN ('queued','running')
                    AND NOT coalesce((p.progress->>'removed_from_queue')::boolean,false)
                    AND ((a.status='queued' AND a.available_at<=clock_timestamp()) OR
                         (a.status='running' AND a.lease_expires_at<=clock_timestamp()))
                    AND (a.parameters->>'kind' NOT IN ('enriched','final') OR NOT %s)
                ORDER BY CASE a.parameters->>'kind' WHEN 'prices' THEN 0 WHEN 'sample' THEN 1
                    WHEN 'final' THEN 2 ELSE 3 END,a.created_at,a.id LIMIT 1""",(selected['id'],prices_only,selected['price_pending'])).fetchone()
        return self.queue.claim(seconds=600,job_id=row['id']) if row else None

    def _claim_final_report(self):
        # Full analysis continues after a request has left the collection queue.
        with self.pool.connection() as c:
            row=c.execute("""SELECT a.id FROM research_job a JOIN research_campaign r
                ON r.id::text=a.parameters->>'campaign_id'
                JOIN research_job p ON p.id=r.job_id
                WHERE a.parameters->>'collector'='campaign-assembly-v1'
                AND a.parameters->>'kind'='final' AND p.status='succeeded'
                AND a.attempts<a.max_attempts
                AND ((a.status='queued' AND a.available_at<=clock_timestamp())
                  OR (a.status='running' AND a.lease_expires_at<=clock_timestamp()))
                ORDER BY a.created_at,a.id LIMIT 1""").fetchone()
        return self.queue.claim(seconds=600,job_id=row['id']) if row else None

    def _publish(self,job):
        identifier=UUID(job['parameters']['campaign_id']);kind=job['parameters']['kind']
        with self.pool.connection() as c:
            self._active(c,identifier,allow_finished=(kind=='final'))
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s',(identifier,)).fetchone()
            day=(None if kind=='final' else c.execute('SELECT * FROM research_campaign_day WHERE campaign_id=%s AND day=%s',
                (identifier,job['parameters']['day'])).fetchone())
        if kind=='final':
            with self.pool.connection() as c:
                rows=c.execute('SELECT dataset_id FROM research_campaign_day WHERE campaign_id=%s ORDER BY dataset_id',(identifier,)).fetchall()
            ids=[r['dataset_id'] for r in rows]
            if not ids or any(i is None for i in ids):raise EvidenceConflict('Final publication incomplete')
            result=ReportStore(self.pool).publish_campaign('campaign-'+identifier.hex,campaign['asset'],ids,
                publication=dict(complete=True,revision=2*len(ids),reported_sections=len(ids),total_sections=len(ids)))
            with self.pool.connection() as c:
                self._active(c,identifier,lock=True,allow_finished=True);self.queue._owned(c,job['id'],job['lease_token'])
                c.execute('INSERT INTO research_campaign_result VALUES(%s,%s) ON CONFLICT DO NOTHING',(identifier,result))
                CategoryReports.enqueue(c,campaign['asset'],identifier,source_revision=result)
                self._finish(c,job)
            return
        if day is None or day['manifest'] is None:raise EvidenceConflict('Missing assembly manifest')
        plan=self._plan(campaign,day)
        attempts=self._attempts(campaign,day,'evidence')
        if kind in ('sample','prices'):
            plan=replace(plan,scopes=tuple(s for s in plan.scopes if s.resource=='candles'))
            attempts=[(j,p) for j,p in attempts if j['parameters']['scope']['resource']=='candles']
        elif kind!='enriched':raise EvidenceConflict('Unknown assembly kind')
        guard=self._work_guard(job)
        prepared=prepare_dataset(plan,attempts,self.archives,
            lambda jid:(self.queue.get(jid),self.queue.page_evidence(jid)),
            sampled_tickers=set(job['parameters']['tickers']) if kind=='sample' else None,cancelled=guard)
        if self.cancelled():raise CollectionInterrupted('Worker stopping')
        self.queue.heartbeat(job['id'],job['lease_token'],600)
        prefix={'sample':'campaign-sample-','prices':'campaign-candles-','enriched':'campaign-'}[kind]
        dataset=self.datasets.publish(prefix+identifier.hex,prepared)
        # Same lock order as pause/remove: campaign first, then child lease.
        # Merge into the latest parent progress; never overwrite collector changes.
        with self.pool.connection() as c:
            parent=self._active(c,identifier,lock=True)
            self.queue._owned(c,job['id'],job['lease_token'])
            progress=parent['progress'];key=day['day'].isoformat()
            if kind=='enriched':
                c.execute('UPDATE research_campaign_day SET dataset_id=%s WHERE campaign_id=%s AND day=%s',
                    (dataset,identifier,day['day']))
            else:
                if kind=='prices' and 'collection_limit' in campaign['config']:
                    c.execute('UPDATE research_campaign_day SET dataset_id=%s WHERE campaign_id=%s AND day=%s',(dataset,identifier,day['day']))
                field='sample_previews' if kind=='sample' else 'candle_previews'
                previous=progress.setdefault(field,{}).setdefault(key,dataset)
                if previous!=dataset:raise EvidenceConflict('Assembly dataset changed')
                if kind=='prices':progress['last_price_day_at']=datetime.now(timezone.utc).isoformat()
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(progress),parent['id']))
            if kind=='sample':SampleReports.enqueue(c,identifier,campaign['asset'])
            else:ProgressiveReports.enqueue(c,identifier,campaign['asset'])
            self._finish(c,job)
        print(json.dumps(dict(event='assembly_day_saved',asset=campaign['asset'],day=key,kind=kind)),flush=True)

    @staticmethod
    def _finish(c,job):
        c.execute("""UPDATE research_job SET status='succeeded',finished_at=clock_timestamp(),
            lease_token=NULL,lease_expires_at=NULL WHERE id=%s""",(job['id'],))

    def run_once(self,*,deadline):
        from .window_rebuild import WindowRebuild
        if not hasattr(self,"_window_upgrade"):self._window_upgrade=WindowRebuild(self.pool,self.cancelled)
        from .storage_compaction import ScopeCompaction
        if not hasattr(self,"_scope_compaction"):self._scope_compaction=ScopeCompaction(self.pool)
        self._scope_compaction.tick()
        worked=False
        try:
            worked=self._window_upgrade.run_once() or self._run_once(deadline=deadline)
            return worked
        finally:
            if worked:
                from .memory import release_report_memory
                release_report_memory()

    def _run_once(self,*,deadline):
        # Collection-side data assembly has priority over all idle analysis.
        # Paper replay is claimed ONLY by the dedicated paper service.
        from . import report_jobs
        job=self._claim_assembly(prices_only=True)
        if job is None:job=self._claim_assembly()
        if job is None:
            if report_jobs.primary_work_pending(self.pool):return False
            try:
                with report_jobs.background_guard(lambda:report_jobs.primary_work_pending(self.pool)):
                    if not self._bootstrapped:
                        ProgressiveReports(self.pool).bootstrap()
                        SampleReports(self.pool).bootstrap()
                        self._bootstrapped=True
                    if not self._category_recovered:
                        with self.pool.connection() as c:
                            assets=[r['asset'] for r in c.execute('SELECT DISTINCT asset FROM research_campaign ORDER BY asset LIMIT 12').fetchall()]
                        for asset in assets:
                            CategoryReports(self.pool).recover_latest(asset)
                            self._category_recovered.add(asset)
                    if ProgressiveReports(self.pool).run_once():return True
                    if SampleReports(self.pool).run_once():return True
                    if CategoryReports(self.pool).run_once():return True
                    job=self._claim_final_report()
                    if job is None:return False
                    return self._run_assembly(job)
            except CollectionInterrupted:
                # New work arrived between the idle check and job selection.
                return False
        return self._run_assembly(job)

    def _run_assembly(self,job):
        print(json.dumps(dict(event='assembly_started',asset=job['asset'],kind=job['parameters']['kind'],day=job['parameters']['day'])),flush=True)
        try:self._publish(job)
        except CollectionInterrupted:self.queue.yield_job(job['id'],job['lease_token'],1)
        except LeaseLost:
            # Parent state can change after preparation. Do not leave an owned
            # assembly falsely running until its ten-minute crash lease expires.
            try:self.queue.yield_job(job['id'],job['lease_token'],1)
            except LeaseLost:pass
            raise
        except (DatasetLimit,EvidenceConflict,CoverageIncomplete) as error:
            code=('assembly_size_limit' if isinstance(error,DatasetLimit) else
                'assembly_incomplete' if isinstance(error,CoverageIncomplete) else 'assembly_evidence_conflict')
            print(json.dumps(dict(event='assembly_blocked',asset=job['asset'],day=job['parameters']['day'],
                code=code,reason=str(error)[:200])),flush=True)
            self.queue.fail(job['id'],job['lease_token'],code,retry=False)
        except Exception:
            self.queue.fail(job['id'],job['lease_token'],'campaign_assembly_retry',delay_seconds=10)
            raise
        return True

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
from .campaigns import CampaignWorker,ACTIVE_DAYS
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
    def _active(c,identifier,*,lock=False):
        row=c.execute('''SELECT j.* FROM research_campaign r JOIN research_job j ON j.id=r.job_id
            WHERE r.id=%s'''+(' FOR UPDATE OF j' if lock else ''),(identifier,)).fetchone()
        if (row is None or row['status'] not in ('queued','running') or row['progress'].get('removed_from_queue')):
            raise LeaseLost('Campaign stopped')
        return row

    def _claim_assembly(self):
        with self.pool.connection() as c:
            row=c.execute("""SELECT a.id FROM research_job a JOIN research_campaign r
                ON r.id::text=a.parameters->>'campaign_id' JOIN research_job p ON p.id=r.job_id
                WHERE a.idempotency_key>='assembly/' AND a.idempotency_key<'assemblz'
                    AND a.parameters->>'collector'='campaign-assembly-v1'
                    AND r.id=(SELECT cr.id FROM research_campaign cr JOIN research_job cp ON cp.id=cr.job_id
                        WHERE (cp.status IN ('queued','running') OR
                            (cp.status='failed' AND cp.error_code IN ('attempts_exhausted','campaign_step_failed')))
                        AND NOT coalesce((cp.progress->>'removed_from_queue')::boolean,false)
                        ORDER BY cr.created_at,cr.id LIMIT 1)
                    AND a.attempts<a.max_attempts AND p.status IN ('queued','running')
                    AND NOT coalesce((p.progress->>'removed_from_queue')::boolean,false)
                    AND (a.parameters->>'kind'='final' OR a.parameters->>'day' IN (
                        SELECT day::text FROM research_campaign_day WHERE campaign_id=r.id AND dataset_id IS NULL
                        ORDER BY day DESC LIMIT %s))
                    AND ((a.status='queued' AND a.available_at<=clock_timestamp()) OR
                         (a.status='running' AND a.lease_expires_at<=clock_timestamp()))
                    AND (a.parameters->>'kind'<>'enriched' OR NOT EXISTS(
                        SELECT 1 FROM research_campaign cr JOIN research_job cp ON cp.id=cr.job_id
                        JOIN LATERAL (SELECT * FROM research_campaign_day WHERE campaign_id=cr.id
                            AND dataset_id IS NULL ORDER BY day DESC LIMIT %s) d ON true
                        WHERE cr.id=r.id AND cp.status IN ('queued','running')
                        AND NOT coalesce((cp.progress->>'removed_from_queue')::boolean,false)
                        AND d.dataset_id IS NULL AND NOT(coalesce(cp.progress->'candle_previews','{}'::jsonb) ? d.day::text)))
                ORDER BY CASE a.parameters->>'kind' WHEN 'prices' THEN 0 WHEN 'sample' THEN 1
                    WHEN 'final' THEN 2 ELSE 3 END,a.created_at,a.id LIMIT 1""",(ACTIVE_DAYS,ACTIVE_DAYS)).fetchone()
        return self.queue.claim(seconds=600,job_id=row['id']) if row else None

    def _publish(self,job):
        identifier=UUID(job['parameters']['campaign_id']);kind=job['parameters']['kind']
        with self.pool.connection() as c:
            self._active(c,identifier)
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
                self._active(c,identifier,lock=True);self.queue._owned(c,job['id'],job['lease_token'])
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
        # Publish ready full-cohort price reports ahead of sample/trade work.
        if not self._bootstrapped:
            ProgressiveReports(self.pool).bootstrap();SampleReports(self.pool).bootstrap();self._bootstrapped=True
        oldest=self.oldest_request()
        if oldest and oldest['asset'] not in self._category_recovered:
            CategoryReports(self.pool).recover_latest(oldest['asset'])
            self._category_recovered.add(oldest['asset'])
        scope=dict(campaign_id=oldest['id']) if oldest else {}
        if ProgressiveReports(self.pool).run_once(**scope):return True
        if SampleReports(self.pool).run_once(**scope):return True
        # A finished date must reach the category page before more assembly.
        if CategoryReports(self.pool).run_once(**(dict(asset=oldest['asset']) if oldest else {})):return True
        job=self._claim_assembly()
        if job is None:
            return False
        print(json.dumps(dict(event='assembly_started',asset=job['asset'],kind=job['parameters']['kind'],day=job['parameters']['day'])),flush=True)
        try:self._publish(job)
        except CollectionInterrupted:self.queue.yield_job(job['id'],job['lease_token'])
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

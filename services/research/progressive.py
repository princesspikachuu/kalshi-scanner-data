"""Immutable candle-complete report snapshots while full enrichment continues."""
from uuid import UUID,uuid4
import json
from psycopg.types.json import Jsonb
from .queue import ResearchQueue
from .reports import ReportStore
from . import report_jobs


class ProgressiveReports:
    def __init__(self,pool):self.pool=pool;self.queue=ResearchQueue(pool)

    @staticmethod
    def enqueue(c,identifier,asset):
        row=c.execute('''SELECT count(*) FILTER(WHERE d.dataset_id IS NOT NULL)*2+
            count(*) FILTER(WHERE d.dataset_id IS NULL AND j.progress->'candle_previews' ? d.day::text) AS revision
            FROM research_campaign r JOIN research_job j ON j.id=r.job_id
            JOIN research_campaign_day d ON d.campaign_id=r.id WHERE r.id=%s''',(identifier,)).fetchone()
        revision=row['revision']
        if not revision:return
        c.execute('''INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
            VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO UPDATE SET status='queued',attempts=0,error_code=NULL,
                finished_at=NULL,available_at=clock_timestamp(),progress=research_job.progress||jsonb_build_object('report_recovery_version','checkpoint-path-v1')
                WHERE research_job.status='failed' AND research_job.error_code='progress_report_blocked'
                AND research_job.progress->>'report_recovery_version' IS DISTINCT FROM 'checkpoint-path-v1'
            ''',
            (uuid4(),f'progress/{identifier}/{revision}',asset,Jsonb(dict(collector='campaign-preview-v1',campaign_id=str(identifier),revision=revision))))

    def bootstrap(self):
        with self.pool.connection() as c:
            rows=c.execute('''SELECT r.id,r.asset FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE j.status IN ('queued','running') ORDER BY r.created_at LIMIT 100''').fetchall()
            for row in rows:
                self.enqueue(c,row['id'],row['asset'])
                # A fresh immutable publication may run while a crashed old
                # builder's lease expires. Never steal that lease or overwrite
                # its frozen membership. The stream lock/revision fence seals
                # at most one identical result and prevents older regressions.
                c.execute("""INSERT INTO research_job(id,idempotency_key,asset,parameters,max_attempts)
                    SELECT %s,'checkpoint-repair-v1/'||idempotency_key,asset,parameters,5
                    FROM research_job WHERE idempotency_key LIKE %s
                    AND status IN ('running','failed')
                    AND parameters->>'revision'=(SELECT max((parameters->>'revision')::integer)::text
                        FROM research_job WHERE idempotency_key LIKE %s)
                    ORDER BY created_at DESC LIMIT 1 ON CONFLICT(idempotency_key) DO NOTHING""",
                    (uuid4(),f"progress/{row['id']}/%",f"progress/{row['id']}/%"))

    def step(self,job):
        identifier=UUID(job['parameters']['campaign_id'])
        if report_jobs.defer_unfrozen(self.queue,job,'campaign-'+identifier.hex,'snapshot'):return
        with self.pool.connection() as c:
            complete=c.execute('SELECT 1 FROM research_campaign_result WHERE campaign_id=%s',(identifier,)).fetchone()
        if complete:
            self.queue.finish(job['id'],job['lease_token']);return
        with self.pool.connection() as c:
            owned=self.queue._owned(c,job['id'],job['lease_token'])
            snapshot=owned['progress'].get('snapshot')
            if snapshot is None:
                rows=c.execute('''SELECT d.day,d.dataset_id,
                    (j.progress->'candle_previews'->>d.day::text)::bigint AS preview
                    FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                    JOIN research_campaign_day d ON d.campaign_id=r.id WHERE r.id=%s ORDER BY d.day''',(identifier,)).fetchall()
                ids=sorted({r['dataset_id'] or r['preview'] for r in rows if r['dataset_id'] or r['preview']})
                publication=dict(complete=False,revision=sum(2 if r['dataset_id'] else 1 if r['preview'] else 0 for r in rows),
                    reported_sections=sum(bool(r['dataset_id'] or r['preview']) for r in rows),total_sections=len(rows))
                snapshot=dict(ids=ids,publication=publication)
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(dict(snapshot=snapshot)),job['id']))
        result=ReportStore(self.pool).publish_campaign('campaign-'+identifier.hex,job['asset'],snapshot['ids'],publication=snapshot['publication'])
        with self.pool.connection() as c:
            self.queue._owned(c,job['id'],job['lease_token'])
            from .cumulative import CategoryReports
            CategoryReports.enqueue(c,job['asset'],'progress/'+str(result),source_revision=result,urgent=False)
            report_jobs.coalesce(c,job,snapshot['publication']['revision'],campaign=True)
        self.queue.finish(job['id'],job['lease_token'])

    def run_once(self):
        job=self.queue.claim(seconds=600,collector='campaign-preview-v1')
        if job is None:return False
        try:self.step(job)
        except ValueError as error:
            codes={'Report path limit exceeded; split the range':'progress_path_limit',
                   'Report entry limit exceeded; split the range':'progress_entry_limit',
                   'Research result too large; explicit partitions required':'progress_size_limit'}
            code=codes.get(str(error),'progress_report_blocked')
            print(json.dumps(dict(event='report_publication_blocked',asset=job['asset'],code=code)),flush=True)
            self.queue.fail(job['id'],job['lease_token'],code,retry=False)
        return True

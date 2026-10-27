"""Immutable candle-complete report snapshots while full enrichment continues."""
from uuid import UUID,uuid4
from psycopg.types.json import Jsonb
from .queue import ResearchQueue
from .reports import ReportStore


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
            VALUES(%s,%s,%s,%s,5) ON CONFLICT(idempotency_key) DO NOTHING''',
            (uuid4(),f'progress/{identifier}/{revision}',asset,Jsonb(dict(collector='campaign-preview-v1',campaign_id=str(identifier)))))

    def bootstrap(self):
        with self.pool.connection() as c:
            rows=c.execute('''SELECT r.id,r.asset FROM research_campaign r JOIN research_job j ON j.id=r.job_id
                WHERE j.status IN ('queued','running') ORDER BY r.created_at LIMIT 100''').fetchall()
            for row in rows:self.enqueue(c,row['id'],row['asset'])

    def step(self,job):
        identifier=UUID(job['parameters']['campaign_id'])
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
            CategoryReports.enqueue(c,job['asset'],'progress/'+str(result))
        self.queue.finish(job['id'],job['lease_token'])

    def run_once(self):
        job=self.queue.claim(seconds=600,collector='campaign-preview-v1')
        if job is None:return False
        try:self.step(job)
        except ValueError:self.queue.fail(job['id'],job['lease_token'],'progress_report_blocked',retry=False)
        return True

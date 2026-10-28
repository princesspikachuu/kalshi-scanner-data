"""Small mutable operational marker, using existing queue grants; no data history."""
from uuid import UUID
from psycopg.types.json import Jsonb

HEARTBEAT_ID=UUID('8c095e9e-5b14-5b74-8c9a-b647c3490001')
HEARTBEAT_KEY='worker/heartbeat/v1'
PARAMETERS={'collector':'worker-heartbeat-v1'}


class WorkerHeartbeat:
    def __init__(self,pool):self.pool=pool

    def beat(self):
        with self.pool.connection() as c:
            row=c.execute('''INSERT INTO research_job(id,idempotency_key,asset,parameters,status,finished_at)
                VALUES(%s,%s,'btc',%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO UPDATE SET finished_at=clock_timestamp()
                WHERE research_job.id=EXCLUDED.id AND research_job.parameters=EXCLUDED.parameters
                    AND research_job.status='succeeded'
                RETURNING id''',(HEARTBEAT_ID,HEARTBEAT_KEY,Jsonb(PARAMETERS))).fetchone()
            if row is None:raise ValueError('Operational heartbeat identity conflict')


class DayProgress:
    """Read small queue/report metadata once per minute, never market payloads."""
    def __init__(self,pool,sink,*,clock=None):
        import time
        self.pool,self.sink,self.clock=pool,sink,clock or time.monotonic
        self.last=float('-inf')

    def emit(self):
        now=self.clock()
        if now-self.last<60:return
        self.last=now
        try:
            with self.pool.connection() as c:
                rows=c.execute('''WITH chosen AS MATERIALIZED (
                    SELECT r.*,j.status,j.error_code,j.progress,j.lease_expires_at FROM research_campaign r
                    JOIN research_job j ON j.id=r.job_id WHERE j.status IN ('queued','running','failed')
                    AND NOT coalesce((j.progress->>'removed_from_queue')::boolean,false)
                    ORDER BY r.created_at,r.id LIMIT 20)
                    SELECT r.asset,r.start_at,r.end_at,r.status,r.error_code,
                        greatest(0,extract(epoch FROM(r.lease_expires_at-clock_timestamp())))::integer AS lease_seconds,
                        d.total_days,d.enriched_days,d.price_days_saved,
                        coalesce((SELECT (rr.report->'publication'->>'reported_sections')::integer
                            FROM research_result rr WHERE rr.stream_key='campaign-'||replace(r.id::text,'-','')
                            ORDER BY rr.id DESC LIMIT 1),0) AS report_days
                    FROM chosen r CROSS JOIN LATERAL (
                        SELECT count(*)::integer AS total_days,count(dataset_id)::integer AS enriched_days,
                            count(*) FILTER(WHERE dataset_id IS NOT NULL OR
                                coalesce(r.progress->'candle_previews','{}'::jsonb) ? day::text)::integer AS price_days_saved
                        FROM research_campaign_day WHERE campaign_id=r.id) d
                    ORDER BY r.created_at,r.id''').fetchall()
            self.sink(dict(event='collection_days_status_v1',collections=rows))
        except Exception:pass  # Diagnostics cannot stop or mutate collection.

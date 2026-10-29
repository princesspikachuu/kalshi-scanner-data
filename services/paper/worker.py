import time
from datetime import datetime,timezone
from services.research.queue import ResearchQueue,LeaseLost
from services.research.datasets import decoded_dataset,iter_dataset_records
from .engine import replay
from .portfolio import replay_portfolio
from psycopg.types.json import Jsonb


class PaperWorker:
    def __init__(self,pool,archives):self.pool,self.archives=pool,archives;self.queue=ResearchQueue(pool)
    def run_once(self):
        job=self.queue.claim(seconds=600,collector='paper-replay-v1')
        if job is None:return False
        activity={};last_update=0
        def update(data,force=False):
            nonlocal last_update
            previous=activity.get('phase');activity.update(data);now=time.monotonic()
            if not force and previous==activity.get('phase') and now-last_update<2:return
            activity['updated_at']=datetime.now(timezone.utc).isoformat()
            with self.pool.connection() as c:
                self.queue._owned(c,job['id'],job['lease_token'])
                c.execute("UPDATE research_job SET progress=progress||%s,lease_expires_at=clock_timestamp()+interval '600 seconds' WHERE id=%s",(Jsonb(dict(activity=activity)),job['id']))
            last_update=now
        try:
            update(dict(phase='loading saved evidence',provider_reads=0),force=True)
            if 'strategies' in job['parameters']:
                def sources():
                    for identifier in job['parameters']['dataset_ids']:
                        update(dict(dataset_id=identifier,phase='loading saved evidence'),force=True)
                        with self.pool.connection() as c:
                            source=c.execute("SELECT ds.id,ds.fingerprint,ds.payload,coalesce(r.asset,substring(ds.stream_key from 10)) AS asset FROM research_dataset ds LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','') WHERE ds.id=%s",(identifier,)).fetchone()
                        payload=decoded_dataset(source)['payload']
                        if 'trades' not in payload['summary']['resources']:raise ValueError('Detailed trade evidence required')
                        yield source['asset'],payload,iter_dataset_records(payload,self.archives)
                result=replay_portfolio(sources(),job['parameters']['strategies'],job['parameters']['starting_cash_cents'],job['parameters']['fill_model'],on_progress=update)
            else:
                with self.pool.connection() as c:
                    source=c.execute('SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s',(job['parameters']['dataset_id'],)).fetchone()
                payload=decoded_dataset(source)['payload']
                if 'trades' not in payload['summary']['resources']:raise ValueError('Detailed trade evidence required')
                result=replay(payload,job['parameters']['strategy'],iter_dataset_records(payload,self.archives))
            update(dict(phase='finished',open_orders=[],recent_activity=result.get('recent_activity',[])),force=True)
            with self.pool.connection() as c:
                self.queue._owned(c,job['id'],job['lease_token'])
                c.execute('UPDATE research_job SET progress=progress||%s WHERE id=%s',(Jsonb(dict(result=result)),job['id']))
            self.queue.finish(job['id'],job['lease_token'])
        except LeaseLost:
            # Cancellation revokes ownership; keep the processor alive and never
            # publish a result after the cancel response has succeeded.
            return True
        except Exception:
            self.queue.fail(job['id'],job['lease_token'],'paper_replay_blocked',retry=False)
            raise
        return True

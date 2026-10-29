import json
from services.research.queue import ResearchQueue
from services.research.datasets import decoded_dataset,iter_dataset_records
from services.research.backlog import AnalysisBacklog
from .engine import replay
from .portfolio import replay_portfolio
from psycopg.types.json import Jsonb


class PaperWorker:
    def __init__(self,pool,archives):self.pool,self.archives=pool,archives;self.queue=ResearchQueue(pool)
    def run_once(self):
        job=self.queue.claim(seconds=600,collector='paper-replay-v1')
        if job is None:return False
        try:
            if 'strategies' in job['parameters']:
                def sources():
                    for identifier in job['parameters']['dataset_ids']:
                        with self.pool.connection() as c:
                            source=c.execute("SELECT ds.id,ds.fingerprint,ds.payload,coalesce(r.asset,substring(ds.stream_key from 10)) AS asset FROM research_dataset ds LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','') WHERE ds.id=%s",(identifier,)).fetchone()
                        payload=decoded_dataset(source)['payload']
                        if 'trades' not in payload['summary']['resources']:raise ValueError('Detailed trade evidence required')
                        yield source['asset'],payload,iter_dataset_records(payload,self.archives)
                result=replay_portfolio(sources(),job['parameters']['strategies'],job['parameters']['starting_cash_cents'],job['parameters']['fill_model'])
            else:
                with self.pool.connection() as c:
                    source=c.execute('SELECT id,fingerprint,payload FROM research_dataset WHERE id=%s',(job['parameters']['dataset_id'],)).fetchone()
                payload=decoded_dataset(source)['payload']
                if 'trades' not in payload['summary']['resources']:raise ValueError('Detailed trade evidence required')
                result=replay(payload,job['parameters']['strategy'],iter_dataset_records(payload,self.archives))
            with self.pool.connection() as c:
                self.queue._owned(c,job['id'],job['lease_token'])
                c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(dict(result=result)),job['id']))
            self.queue.finish(job['id'],job['lease_token'])
        except Exception:
            self.queue.fail(job['id'],job['lease_token'],'paper_replay_blocked',retry=False)
            raise
        return True

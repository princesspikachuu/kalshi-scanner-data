import json
from services.research.queue import ResearchQueue
from services.research.datasets import decoded_dataset,iter_dataset_records
from services.research.backlog import AnalysisBacklog
from .engine import replay
from psycopg.types.json import Jsonb


class PaperWorker:
    def __init__(self,pool,archives):self.pool,self.archives=pool,archives;self.queue=ResearchQueue(pool)
    def run_once(self):
        job=self.queue.claim(seconds=600,collector='paper-replay-v1')
        if job is None:return False
        try:
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

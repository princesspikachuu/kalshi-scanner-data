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

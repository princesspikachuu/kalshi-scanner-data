"""Bounded, restart-safe compaction of mutable job metadata, never evidence/history."""
import json,time
from uuid import uuid4
from psycopg.types.json import Jsonb
from .scope_storage import encode_scope,decode_scope,enable_compact_writes

KEY='demo/compaction-health'
class ScopeCompaction:
    def __init__(self,pool,*,clock=time.monotonic):
        self.pool,self.clock=pool,clock;self.ready_at=clock()+180;self.next_at=self.ready_at;self.last_log=0
    def tick(self):
        now=self.clock()
        if now<self.next_at:return
        enable_compact_writes();self.next_at=now+5
        try:self.step(now)
        except Exception:
            self.next_at=now+300
            print(json.dumps(dict(event='storage_compaction_deferred',original_records_retained=True)),flush=True)
    def step(self,now):
        with self.pool.connection() as c:
            c.execute('SET LOCAL statement_timeout=5000')
            c.execute('SELECT pg_advisory_xact_lock(723741943)')
            prior=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',(KEY,)).fetchone()
            state=dict(prior['progress']) if prior else dict(cursor='00000000-0000-0000-0000-000000000000',rows=0,logical_bytes_saved=0)
            rows=c.execute("""SELECT id::text,parameters,pg_column_size(parameters) AS bytes FROM research_job
                WHERE id>%s::uuid AND status='succeeded' AND parameters->>'collector'='evidence-v1'
                AND parameters->'scope' ? 'manifest_key' ORDER BY id LIMIT 1000""",(state['cursor'],)).fetchall()
            changes=[]
            for row in rows:
                compact=dict(row['parameters'],scope=encode_scope(row['parameters']['scope']))
                if decode_scope(compact['scope'])!=row['parameters']['scope']:raise ValueError('Compaction changed evidence scope')
                if compact!=row['parameters']:changes.append(dict(id=row['id'],parameters=compact,prior=row['parameters'],prior_bytes=row['bytes']))
            saved=[]
            if changes:
                saved=c.execute("""UPDATE research_job j SET parameters=r.parameters
                    FROM jsonb_to_recordset(%s::jsonb) AS r(id uuid,parameters jsonb,prior jsonb,prior_bytes integer)
                    WHERE j.id=r.id AND j.status='succeeded' AND j.parameters=r.prior
                    RETURNING r.prior_bytes-pg_column_size(j.parameters) AS bytes""",(Jsonb(changes),)).fetchall()
            state.update(cursor=rows[-1]['id'] if rows else '00000000-0000-0000-0000-000000000000',
                rows=state['rows']+len(saved),logical_bytes_saved=state['logical_bytes_saved']+sum(r['bytes'] for r in saved),
                complete=not rows,at=time.time(),lossless=True)
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto','{}',%s,%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(state),KEY))
        if not rows:self.next_at=now+86400
        if now-self.last_log>=60 or not rows or self.last_log==0:
            print(json.dumps(dict(event='storage_metadata_compacted',**{k:state[k] for k in ('rows','logical_bytes_saved','complete')})),flush=True);self.last_log=now

"""Atomic hosted wallet/checkpoint and audit records under the existing trading fence."""
import asyncio,json,os,time,tempfile
from copy import deepcopy
from collections import Counter
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from .state import encode
from .checkpoint_codec import pack_checkpoint
from .checkpoint_segments import CheckpointSegments
from .audit_bulk import persist_audit_rows
from .diagnostic_batches import compact_diagnostic_rows, BATCH_PREFIX

KEY='demo/shadow/checkpoint'
# Byte-identical state is already durably committed. Elapsed time does not
# invalidate it. Every new process/changed state still writes a checkpoint;
# standalone startup/shutdown checkpoints remain explicit recovery boundaries.

def checkpoint_signature(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('data'),str):return None
    if not isinstance(payload.get('sha256'),str) or not isinstance(payload.get('bytes'),int):return None
    return (payload.get('checkpoint_encoding'),payload['bytes'],payload['sha256'])

UPSERT="""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
      VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
      ON CONFLICT(idempotency_key) DO UPDATE SET parameters=excluded.parameters,
      progress=excluded.progress,finished_at=clock_timestamp()"""

def entry(key,parameters,progress):return (uuid4(),Jsonb(parameters),Jsonb(progress),key)

def put(c,key,parameters,progress):c.execute(UPSERT,entry(key,parameters,progress))

class HostedAudit:
    def __init__(self,store,guard):
        self.store,self.guard=store,guard
        self.path=Path(tempfile.mkdtemp(prefix='moneytree-shadow-'))
        self.engine=self.fleet=None
        self.last_snapshot=0
        self.command_key=None
    def snapshot(self):
        data=encode(self.engine,self.fleet)
        if getattr(self,'experiments',None):data['experiments']=self.experiments.state()
        return json.loads(json.dumps(data,default=str))
    def checkpoint_snapshot(self):
        # Serialize the hot state once, without a full JSON decode/re-encode
        # before psycopg. Audit events and this payload still commit together.
        data=encode(self.engine,self.fleet)
        if getattr(self,'experiments',None):data['experiments']=self.experiments.state()
        if hasattr(self,'_frozen_discovery'):data['experiments']['_maker_discovery']=self._frozen_discovery
        if not hasattr(self,'checkpoint_segments'):self.checkpoint_segments=CheckpointSegments()
        payload=pack_checkpoint(data,binary=True,segments=self.checkpoint_segments)
        if payload.get('checkpoint_encoding') and time.monotonic()>=getattr(self,'codec_log_at',0):
            self.codec_log_at=time.monotonic()+30
            print(json.dumps(dict(event='shadow_checkpoint_size',encoding=payload['checkpoint_encoding'],
                decoded_bytes=payload['bytes'],stored_bytes=len(payload['data']),segment_cache=self.checkpoint_segments.metrics(),real_orders_enabled=False)),flush=True)
        return payload
    def begin(self):self.buffer=[]
    def abort(self):self.buffer=None
    def log(self,now,kind,wallet,**fields):
        if not self.engine or not self.fleet:return
        record=(now,kind,dict(fields,cash=str(wallet.cash)))
        if getattr(self,'buffer',None) is not None:
            self.buffer.append(record);return
        self.commit([record])
    def flush(self):
        records=self.buffer;self.buffer=None
        if records:self.commit(records)
    def prepare(self,records):
        started=time.monotonic();data=self.checkpoint_snapshot()
        batch=[entry(KEY,{},data)]+getattr(self,'extra_writes',[])
        self.extra_writes=[]
        commands=[];written_events=[]
        # Scalar comparisons share a source tick. Batch only their new
        # opportunity records; preserve every decision without six job rows
        # for the same two-sided quote. Existing strategy events are unchanged.
        grouped={};compact=[]
        for now,kind,fields in records:
            if kind=='EXPERIMENT' and fields.get('experiment_kind')=='SCALPER_OPPORTUNITY':
                key=(now,fields.get('ticker'))
                if key not in grouped:
                    merged=dict(ticker=fields.get('ticker'),decisions=[])
                    grouped[key]=merged;compact.append((now,'SCALPER_OBSERVATION_BATCH',merged))
                grouped[key]['decisions'].append(dict(folder_id=fields['folder_id'],side=fields.get('side'),
                    reason=fields.get('reason'),observation=json.loads(fields['details'])))
            else:compact.append((now,kind,fields))
        for now,kind,fields in compact:
            event=json.loads(json.dumps(dict(time=now,event=kind,**fields),default=str))
            event.setdefault('cash',str(self.engine.wallet.cash))
            if kind=='EXPERIMENT':event['event']=fields['experiment_kind']
            written_events.append(event)
            batch.append(entry('demo/shadow/event/'+str(uuid4()),dict(kind=kind,ticker=fields.get('ticker'),time=now),event))
            if kind in ('REFILL','SESSION_RESET','EXPERIMENT') and self.command_key:commands.append((Jsonb(dict(done=True,at=now)),self.command_key))
            if kind=='EXPERIMENT' and fields.get('experiment_kind')=='CYCLE_REPORT':
                report=json.loads(fields['details']);report['at']=now
                folder=fields['folder_id']
                batch.append(entry('demo/experiment/report/'+folder+'/'+report['ticker'],{},report))
            if kind=='CYCLE_REPORT':
                report=json.loads(fields['details']);report['at']=now
                report['bot_revision']=self.engine.markets[report['ticker']].get('bot_revision',1)
                batch.append(entry('demo/shadow/report/'+report['ticker'],dict(time=now,bot_id=report.get('bot_id')),report))
        # Store only high-volume, non-financial diagnostics as compact,
        # lossless rows. Every event UUID, original payload and time survives.
        # Fills, settlements, reports, safety events and commands stay raw.
        batch=compact_diagnostic_rows(batch,entry)
        self.snapshot_ms=(time.monotonic()-started)*1000
        return batch,commands,written_events
    def write(self,prepared):
        batch,commands,written_events=prepared
        started=time.monotonic();self.guard()
        # A SHA-256 digest of the *decoded* lossless state is computed by the
        # checkpoint codec. Skip only when it matches the LAST SUCCESSFULLY
        # COMMITTED checkpoint, and still persist every event/report/command in
        # the same transaction. A changed financial state always writes first.
        checkpoint=getattr(batch[0][2],'obj',{}) if batch else {}
        signature=checkpoint_signature(checkpoint)
        unchanged=(signature is not None and
            signature==getattr(self,'committed_checkpoint_signature',None))
        rows=batch[1:] if unchanged else batch
        with self.store.pool.connection() as c:
            acquired=time.monotonic()
            # Pipeline the event burst; wallet/checkpoint, all audit rows, reports
            # and refill completion markers still commit in one transaction.
            with c.cursor() as cur:
                # Keep the same transaction, idempotency keys, and row order;
                # group only consecutive append-only audit rows into bounded
                # multi-row UPSERT statements to reduce per-row SQL overhead.
                sql_batch=persist_audit_rows(cur,rows,UPSERT)
                upserted=time.monotonic()
                if commands:cur.executemany('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',commands)
                commands_written=time.monotonic()
        # This timestamp follows the pool context exit: transaction commit has
        # completed. No instrumentation can report a failed commit as successful.
        finished=time.monotonic()
        self.write_ms=(finished-started)*1000
        # On an exception above, this identity is NEVER advanced. Retrying
        # after a failed transaction must rewrite the checkpoint as needed.
        if not unchanged:
            self.committed_checkpoint_signature=signature
        self.commits=getattr(self,'commits',0)+1
        self.rows_written=getattr(self,'rows_written',0)+len(rows)+len(commands)
        profile=getattr(self,'durability_profile',None)
        if profile is None:profile=self.durability_profile=Counter()
        profile['commits']+=1
        profile['checkpoint_unchanged_skips']+=int(unchanged)
        profile['checkpoint_upserts']+=int(not unchanged)
        compressed=checkpoint.get('data') if isinstance(checkpoint,dict) else None
        if unchanged:profile['checkpoint_bytes_avoided']+=len(compressed)
        elif isinstance(compressed,str):profile['checkpoint_bytes']+=len(compressed)
        else:profile['inline_checkpoint_commits']+=1
        profile['audit_and_extra_rows']+=max(0,len(batch)-1)
        diagnostic_batches=[r[2].obj for r in rows
            if isinstance(r[3],str) and r[3].startswith(BATCH_PREFIX)]
        profile['diagnostic_batch_rows']+=len(diagnostic_batches)
        profile['diagnostic_events_packed']+=sum(p['count'] for p in diagnostic_batches)
        profile['diagnostic_rows_avoided']+=sum(p['count']-1 for p in diagnostic_batches)
        for field,value in sql_batch.items():profile[field]+=value
        profile['command_rows']+=len(commands)
        profile['prepare_ms']+=getattr(self,'snapshot_ms',0)
        profile['pool_wait_ms']+=(acquired-started)*1000
        profile['upsert_ms']+=(upserted-acquired)*1000
        profile['commands_ms']+=(commands_written-upserted)*1000
        profile['transaction_finalize_ms']+=(finished-commands_written)*1000
        profile['total_write_ms']+=(finished-started)*1000
        profile['worst_write_ms']=max(profile['worst_write_ms'],(finished-started)*1000)
        # Keep event-kind counts only, not any trade, account, or decision body.
        # This allows actual write costs to be attributed to high-volume audit
        # events without discarding or coalescing the underlying evidence.
        counts=Counter(e['event'] for e in written_events)
        kinds=getattr(self,'durability_kind_counts',None)
        if kinds is None:kinds=self.durability_kind_counts=Counter()
        kinds.update(counts)
        if finished>=getattr(self,'durability_log_at',0):
            self.durability_log_at=finished+30
            # Bound telemetry cardinality independently of future event types.
            top=kinds.most_common(16)
            other=sum(kinds.values())-sum(v for _,v in top)
            print(json.dumps(dict(event='shadow_durability_cost',
                **dict(profile),event_kinds=dict(top),event_kinds_other=other,
                real_orders_enabled=False)),flush=True)
            self.durability_profile=Counter()
            self.durability_kind_counts=Counter()
        if any(k in counts for k in ('ORDER_SUBMITTED','MAKER_RESTING','FILL','CANCELLED','SPOT_SAFETY_CANCEL','SAFETY_REENTRY_READY','IOC_COMPLETE','DATA_GAP')):
            print(json.dumps(dict(event='shadow_audit_committed',counts=dict(counts),
                fills=[e for e in written_events if e['event']=='FILL'],
                gaps=[e for e in written_events if e['event']=='DATA_GAP'],real_orders_enabled=False)),flush=True)
        self.last_snapshot=time.monotonic()
    def commit(self,records):self.write(self.prepare(records))
    async def durable_io(self,action,*args):
        # A cancelled coroutine must not leave an unknown database write running
        # after the state lock is released or shutdown writes another checkpoint.
        task=asyncio.create_task(asyncio.to_thread(action,*args))
        cancelled=False
        while True:
            try:
                result=await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():raise
                cancelled=True
        if cancelled:raise asyncio.CancelledError()
        return result
    async def flush_async(self):
        records=self.buffer;self.buffer=None
        # The caller holds the state mutex until this entire operation finishes.
        # Encoding/compression is CPU work too: leave the socket loop free while
        # freezing state, without permitting the next wallet mutation to race it.
        if records:
            self.freeze_discovery()
            try:await self.durable_io(self.commit,records)
            finally:self.__dict__.pop('_frozen_discovery',None)
    def freeze_discovery(self):
        # Discovery coroutines update their operational cursor/cache outside the
        # wallet mutex. Freeze that bounded cache on its owning event loop; all
        # financial/research state remains protected by the caller's mutex.
        experiments=getattr(self,'experiments',None)
        if experiments is not None:self._frozen_discovery=deepcopy(getattr(experiments,'maker_discovery',None))
    def write_checkpoint(self,data):
        self.guard()
        with self.store.pool.connection() as c:put(c,KEY,{},data)
        # Standalone/shutdown checkpoints also become the last durable state.
        # A failure above must leave the old signature unchanged.
        self.committed_checkpoint_signature=checkpoint_signature(data)
        self.last_snapshot=time.monotonic()
    async def checkpoint_async(self):
        self.freeze_discovery()
        try:await self.durable_io(self.checkpoint)
        finally:self.__dict__.pop('_frozen_discovery',None)
    def checkpoint(self):self.write_checkpoint(self.checkpoint_snapshot())
    def publish_status(self,data):
        # This is a derived view, separate from atomic wallet/audit persistence.
        # Reuse the lossless codec instead of asking PostgreSQL to parse and
        # rewrite megabytes of repeated research counters every five seconds.
        started=time.monotonic();sections={}
        if os.environ.get('MT_SHADOW_SPLIT_STATUS_ENABLED','false')=='true':
            from .status_sections import prepare
            payload,sections=prepare(data)
        else:payload=pack_checkpoint(data,binary=True)
        prepared=time.monotonic()
        section_writes=0;section_bytes=0;avoided=0
        if sections:
            with self.store.pool.connection() as c:
                with c.transaction():
                    # Serialize section publishers across worker overlap at
                    # deploy. Check live digests, not a process-local cache
                    # that another publisher could have invalidated.
                    c.execute('SELECT pg_advisory_xact_lock(723741950)')
                    current=c.execute("SELECT idempotency_key,parameters->>'sha256' AS sha256 FROM research_job WHERE idempotency_key=ANY(%s::text[])",
                                      (['demo/shadow/status-section/'+s for s in sections],)).fetchall()
                    committed={r['idempotency_key']:r['sha256'] for r in current}
                    for slot,section in sections.items():
                        key='demo/shadow/status-section/'+slot
                        size=len(section['payload'].get('data',''))
                        if committed.get(key)==section['sha256']:
                            avoided+=size;continue
                        # Stable slots, no immutable row per heartbeat/version.
                        # PostgreSQL digest comparison also suppresses a rewrite
                        # on worker restart; financial checkpoint is untouched.
                        c.execute(UPSERT+" WHERE research_job.parameters->>'sha256' IS DISTINCT FROM excluded.parameters->>'sha256'",
                                  entry(key,
                                        dict(sha256=section['sha256']),section['payload']))
                        section_writes+=1;section_bytes+=size
                    put(c,'demo/shadow/status',{},payload)
        else:
            self.store.put('shadow/status',payload)
        finished=time.monotonic()
        if time.monotonic()>=getattr(self,'status_log_at',0):
            # One startup reference gives a same-document wire-size comparison;
            # do not reserialize the large JSON view on every publication.
            reference=len(json.dumps(data,default=str).encode()) if not hasattr(self,'status_log_at') else None
            self.status_log_at=time.monotonic()+30
            print(json.dumps(dict(event='shadow_status_cost',encoding=payload.get('checkpoint_encoding','json'),
                decoded_bytes=payload.get('bytes'),stored_bytes=len(payload.get('data','')),
                reference_json_bytes=reference,prepare_ms=(prepared-started)*1000,write_ms=(finished-prepared)*1000,
                section_upserts=section_writes,section_transport_bytes=section_bytes,
                unchanged_section_bytes_avoided=avoided,
                real_orders_enabled=False)),flush=True)
    def close(self):pass

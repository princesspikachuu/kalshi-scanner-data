"""Atomic hosted wallet/checkpoint and audit records under the existing trading fence."""
import json,time,tempfile
from collections import Counter
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from .state import encode

KEY='demo/shadow/checkpoint'

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
    def commit(self,records):
        self.guard();data=self.snapshot()
        batch=[entry(KEY,{},data)]+getattr(self,'extra_writes',[])
        self.extra_writes=[]
        commands=[];written_events=[]
        for now,kind,fields in records:
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
        with self.store.pool.connection() as c:
            # Pipeline the event burst; wallet/checkpoint, all audit rows, reports
            # and refill completion markers still commit in one transaction.
            with c.cursor() as cur:
                cur.executemany(UPSERT,batch)
                if commands:cur.executemany('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',commands)
        counts=Counter(e['event'] for e in written_events)
        if any(k in counts for k in ('ORDER_SUBMITTED','MAKER_RESTING','FILL','CANCELLED','SPOT_SAFETY_CANCEL','SAFETY_REENTRY_READY','IOC_COMPLETE','DATA_GAP')):
            print(json.dumps(dict(event='shadow_audit_committed',counts=dict(counts),
                fills=[e for e in written_events if e['event']=='FILL'],
                gaps=[e for e in written_events if e['event']=='DATA_GAP'],real_orders_enabled=False)),flush=True)
        self.last_snapshot=time.monotonic()
    def checkpoint(self):
        self.guard()
        with self.store.pool.connection() as c:put(c,KEY,{},self.snapshot())
        self.last_snapshot=time.monotonic()
    def close(self):pass

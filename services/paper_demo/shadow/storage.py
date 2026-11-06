"""Atomic hosted wallet/checkpoint and audit records under the existing trading fence."""
import json,time,tempfile
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from .state import encode

KEY='demo/shadow/checkpoint'

def put(c,key,parameters,progress):
    c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
      VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
      ON CONFLICT(idempotency_key) DO UPDATE SET parameters=excluded.parameters,
      progress=excluded.progress,finished_at=clock_timestamp()""",
      (uuid4(),Jsonb(parameters),Jsonb(progress),key))

class HostedAudit:
    def __init__(self,store,guard):
        self.store,self.guard=store,guard
        self.path=Path(tempfile.mkdtemp(prefix='moneytree-shadow-'))
        self.engine=self.fleet=None
        self.last_snapshot=0
        self.command_key=None
    def snapshot(self):
        return json.loads(json.dumps(encode(self.engine,self.fleet),default=str))
    def begin(self):self.buffer=[]
    def abort(self):self.buffer=None
    def log(self,now,kind,wallet,**fields):
        if not self.engine or not self.fleet:return
        record=(now,kind,dict(fields))
        if getattr(self,'buffer',None) is not None:
            self.buffer.append(record);return
        self.commit([record])
    def flush(self):
        records=self.buffer;self.buffer=None
        if records:self.commit(records)
    def commit(self,records):
        self.guard();data=self.snapshot()
        with self.store.pool.connection() as c:
            put(c,KEY,{},data)
            for now,kind,fields in records:
                event=json.loads(json.dumps(dict(time=now,event=kind,cash=str(self.engine.wallet.cash),**fields),default=str))
                put(c,'demo/shadow/event/'+str(uuid4()),dict(kind=kind,ticker=fields.get('ticker'),time=now),event)
                if kind=='REFILL' and self.command_key:
                    c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(dict(done=True,at=now)),self.command_key))
                if kind=='CYCLE_REPORT':
                    report=json.loads(fields['details']);report['at']=now
                    report['bot_revision']=self.engine.markets[report['ticker']].get('bot_revision',1)
                    put(c,'demo/shadow/report/'+report['ticker'],dict(time=now,bot_id=report.get('bot_id')),report)
        self.last_snapshot=time.monotonic()
    def checkpoint(self):
        self.guard()
        with self.store.pool.connection() as c:put(c,KEY,{},self.snapshot())
        self.last_snapshot=time.monotonic()
    def close(self):pass

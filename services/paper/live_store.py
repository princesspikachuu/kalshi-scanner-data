"""Live paper checkpoints and audit events in the existing durable job store.

One active account, one fenced lease, short transactions. No migrations,
credentials, new database grants, exchange writes, or in-memory-only balance.
"""
from uuid import uuid4
import json
from psycopg.types.json import Jsonb
from services.research.queue import LeaseLost
from .live import Ledger,initial,public_state

PREFIX='paper-live/'


def save(c,row,ledger,now,*,token=None):
    state=ledger.s;state['updated_at']=now
    if token is not None and str(row['lease_token'])!=str(token):raise LeaseLost('Live paper lease changed')
    finished=state['stopping'] and not state['positions'] and not state['orders']
    c.execute("""UPDATE research_job SET progress=%s,status=%s,
        lease_expires_at=CASE WHEN %s THEN NULL ELSE clock_timestamp()+interval '30 seconds' END,
        lease_token=CASE WHEN %s THEN NULL ELSE lease_token END,
        finished_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END WHERE id=%s""",
        (Jsonb(dict(state={**state,'quotes':{}})),'succeeded' if finished else row['status'],finished,finished,finished,row['id']))
    for event in ledger.events:
        c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
            (uuid4(),Jsonb(dict(collector='paper-live-event-v1',session_id=str(row['id']),event=event)),
             f"paper-live-event/{row['id']}/{event['sequence']:012d}"))


class LiveStore:
    def __init__(self,pool):self.pool=pool;self.quote_key=None;self.quotes={}

    def claim(self):
        with self.pool.connection() as c:
            return c.execute("""WITH candidate AS (
                SELECT id FROM research_job WHERE idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz'
                AND status IN ('queued','running') AND (lease_expires_at IS NULL OR lease_expires_at<=clock_timestamp())
                ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                UPDATE research_job j SET status='running',lease_token=%s,
                lease_expires_at=clock_timestamp()+interval '30 seconds',started_at=coalesce(started_at,clock_timestamp())
                FROM candidate WHERE j.id=candidate.id RETURNING j.*""",(uuid4(),)).fetchone()

    def owned(self,c,identifier,token):
        row=c.execute("""SELECT * FROM research_job WHERE id=%s AND lease_token=%s
            AND status='running' AND lease_expires_at>clock_timestamp() FOR UPDATE""",(identifier,token)).fetchone()
        if row is None:raise LeaseLost('Live paper worker no longer owns session')
        return row

    def checkpoint(self,job,now,*,messages=(),metadata=(),feed=None,gap=None,diagnostics=None):
        with self.pool.connection() as c:
            row=self.owned(c,job['id'],job['lease_token'])
            state=row['progress'].get('state') or initial(row['parameters']['starting_cash_cents'])
            def core(value):return json.dumps({k:v for k,v in value.items() if k not in ('quotes','updated_at','last_message_at')},sort_keys=True)
            before=core(state)
            key=(str(job['id']),str(job['lease_token']))
            if key!=self.quote_key:self.quote_key=key;self.quotes={}
            state['quotes']=self.quotes
            ledger=Ledger(state,row['parameters']['strategies'],row['parameters']['fill_model'])
            if gap is not None:ledger.suspend(now,gap)
            if feed is not None:state['feed']=feed
            pinned={o['ticker'] for o in state['orders']}|{p['ticker'] for p in state['positions']}
            incoming={m['ticker']:m for m in metadata}
            # Prune old unheld markets before adding replacements, so a full
            # watchlist can rotate without losing new candidates.
            if metadata:
                for ticker in list(state['markets']):
                    if ticker not in incoming and ticker not in pinned:
                        state['markets'].pop(ticker);state['quotes'].pop(ticker,None);state['attempted'].pop(ticker,None)
            for ticker,m in incoming.items():
                if ticker in state['markets'] or len(state['markets'])<100:state['markets'][ticker]=m
                else:state['capacity_limited']=True
            if diagnostics:state.update(diagnostics)
            if messages:state['last_message_at']=now
            ledger.apply(messages,now)
            self.quotes=state['quotes']
            if not ledger.events and core(state)==before and now-state.get('updated_at',0)<10:
                # Cheap idle heartbeat; avoid rewriting a large JSON ledger on
                # every quiet tick. Price ticks stay in a bounded volatile cache.
                c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()+interval '30 seconds' WHERE id=%s",(job['id'],))
            else:save(c,row,ledger,now,token=job['lease_token'])
            return state

    def release(self,job,now):
        try:
            self.checkpoint(job,now,gap='worker restart; awaiting fresh feed')
            with self.pool.connection() as c:
                self.owned(c,job['id'],job['lease_token'])
                c.execute("UPDATE research_job SET status='queued',lease_token=NULL,lease_expires_at=NULL WHERE id=%s",(job['id'],))
        except LeaseLost:pass

    def health(self,now,status):
        with self.pool.connection() as c:
            c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at,progress)
                VALUES(%s,'crypto','{"collector":"paper-live-health-v1"}','paper-live-health','succeeded',clock_timestamp(),%s)
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress""",
                (uuid4(),Jsonb(dict(updated_at=now,status=status))))

"""Compact durable controls in the existing indexed job table; no history DDL."""
from uuid import uuid4
from psycopg.types.json import Jsonb

class DemoStore:
    namespace="demo"
    def __init__(self,pool):self.pool=pool
    def get(self,key):
        with self.pool.connection() as c:
            return c.execute('SELECT id::text,parameters,progress,created_at,finished_at FROM research_job WHERE idempotency_key=%s',(self.namespace+'/'+key,)).fetchone()
    def put(self,key,data,*,parameters=None):
        with self.pool.connection() as c:
            return c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,
                parameters=CASE WHEN %s THEN excluded.parameters ELSE research_job.parameters END,
                finished_at=clock_timestamp() RETURNING id::text""",
                (uuid4(),Jsonb(parameters or {}),Jsonb(data),self.namespace+'/'+key,parameters is not None)).fetchone()['id']
    def rows(self,prefix,limit=100,before=None):
        with self.pool.connection() as c:
            return c.execute("""SELECT id::text,idempotency_key,parameters,progress,created_at,finished_at
                FROM research_job WHERE idempotency_key >= %s AND idempotency_key < %s
                AND (%s::uuid IS NULL OR id < %s::uuid) ORDER BY id DESC LIMIT %s""",
                (self.namespace+'/'+prefix,self.namespace+'/'+prefix+'zzzz',before,before,limit)).fetchall()
    def event(self,kind,message,*,bot=None,ticker=None,details=None,event_id=None,critical=False):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat()
        return self.put('event/'+(event_id or str(uuid4())),
            dict(kind=kind,message=message,bot=bot,ticker=ticker,details=details or {},time=now,critical=critical),
            parameters=dict(kind=kind,bot=bot,ticker=ticker,summary=message[:200],time=now))
    def active_orders(self):
        with self.pool.connection() as c:
            rows=c.execute("""SELECT parameters,progress FROM research_job
                WHERE idempotency_key >= %s AND idempotency_key < %s
                AND progress->>'status' NOT IN ('closed','rejected') LIMIT 501""",(self.namespace+'/order/',self.namespace+'/order/zzzz')).fetchall()
        if len(rows)>500:raise RuntimeError('Order reconciliation capacity reached')
        return [dict(r['parameters'],**r['progress']) for r in rows]
    def filled_cycle_sides(self,tickers):
        """Closed entries still determine direction for the rest of their round."""
        if not tickers:return {}
        with self.pool.connection() as c:
            rows=c.execute("""SELECT parameters->>'ticker' AS ticker,
                array_agg(DISTINCT parameters->>'side') AS sides FROM research_job
                WHERE idempotency_key >= %s AND idempotency_key < %s
                AND parameters->>'ticker'=ANY(%s) AND parameters->>'kind'='entry'
                AND parameters->>'entry_strategy'='buy_low_sell_high'
                AND COALESCE((progress->>'filled')::numeric,0)>0 GROUP BY 1""",(self.namespace+'/order/',self.namespace+'/order/zzzz',sorted(tickers))).fetchall()
        return {r['ticker']:r['sides'][0] if len(r['sides'])==1 else 'both' for r in rows}
    def alert(self,key,message,critical=False):
        previous=self.get('alert/'+key)
        if previous and previous['progress'].get('active') and previous['progress'].get('message')==message:return
        self.put('alert/'+key,dict(active=True,message=message,critical=critical,email_sent=False))
        self.event('alert',message,critical=critical)
    def clear_alert(self,key):
        row=self.get('alert/'+key)
        if row and row['progress'].get('active'):self.put('alert/'+key,dict(row['progress'],active=False))

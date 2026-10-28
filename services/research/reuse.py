"""Durable exact-request reuse for ordinary completed-day backfills only.

Uses the existing indexed job registry, not new infrastructure or schema. Rolling,
explicit rechecks and partial/current-day requests always obtain fresh evidence.
"""
from dataclasses import asdict
from uuid import uuid4
from psycopg.types.json import Jsonb
from .inventory import ProviderPage,digest
from .queue import EvidenceConflict
from .telemetry import count
from .weather_calendar import snapshot as weather_snapshot


class VerifiedReads:
    def __init__(self,pool,archives):self.pool,self.archives=pool,archives

    def _key(self,job,scope,cursor):
        with self.pool.connection() as c:
            row=c.execute('''SELECT d.end_at FROM research_campaign_work w
                JOIN research_campaign r ON r.id=w.campaign_id
                JOIN research_campaign_day d ON d.campaign_id=w.campaign_id AND d.day=w.day
                WHERE w.job_id=%s AND r.mode='backfill'
                    AND NOT coalesce((r.request_spec->>'refresh_existing')::boolean,false)
                    AND d.start_at=date_trunc('day',d.start_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                    AND d.end_at=d.start_at+interval '1 day'
                    AND d.end_at<=date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                ORDER BY d.end_at DESC LIMIT 1''',(job['id'],)).fetchone()
        if not row:return None
        path,args=scope.request(cursor)
        calendar=weather_snapshot(scope)
        request=dict(version='verified-backfill-read-v1',path=path,args=args,day_end=row['end_at'].isoformat())
        if calendar is not None:
            # Only the exact verified request can be shared within this dated
            # snapshot. On the next UTC day, a fresh source read is required.
            request['weather_calendar']=calendar
        return ('weather-calendar/' if calendar is not None else 'verified-read/')+digest(request),request

    def lookup(self,job,scope,cursor):
        key=self._key(job,scope,cursor)
        if key is None:return None
        identifier,request=key
        with self.pool.connection() as c:
            row=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key=%s AND status='succeeded'",(identifier,)).fetchone()
        if row is None:return None
        if row['parameters']!=dict(collector='verified-read-v1',request=request):
            raise EvidenceConflict('Reusable request registry mismatch')
        receipt=row['progress']['receipt'];cp=row['progress']['checkpoint']
        if cp.get('projection',{}).get('format')=='candle-batch-projection-v1':
            from .projections import _entry
            payload,_,_=_entry(scope,receipt,self.archives)
            payload['batch_receipt']=receipt
        else:
            from .projections import reusable_payload
            payload,_,_=reusable_payload(scope,cursor,receipt,self.archives)
        count('read.reused',1)
        return ProviderPage(payload,'available',receipt)

    def remember(self,job,scope,checkpoint,receipt):
        if checkpoint['availability']!='available':return
        key=self._key(job,scope,checkpoint['cursor_in'])
        if key is None:return
        identifier,request=key
        with self.pool.connection() as c:
            # First completed verified snapshot wins. Explicit refresh never
            # reads or replaces this index, nor mutates the source raw object.
            c.execute('''INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at,progress)
                VALUES(%s,%s,%s,%s,'succeeded',clock_timestamp(),%s)
                ON CONFLICT(idempotency_key) DO NOTHING''',(uuid4(),job['asset'],
                Jsonb(dict(collector='verified-read-v1',request=request)),identifier,
                Jsonb(dict(receipt=receipt,checkpoint=checkpoint))))

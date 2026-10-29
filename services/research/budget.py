"""Cross-process conservative token budget; no sleeps while holding DB locks."""
import math
from .telemetry import timed,timing,count

from .queue import EvidenceConflict, text_key
from uuid import uuid4
from psycopg.types.json import Jsonb


class ReadBudget:
    def __init__(self, pool, name='kalshi-read'):
        text_key(name, 64)
        self.pool, self.name = pool, name

    def configure(self, refill_per_second, capacity, *, allow_update=False):
        if (type(refill_per_second) not in (int, float) or not math.isfinite(refill_per_second)
                or not 0 < refill_per_second <= 100000 or type(capacity) is not int or not 1 <= capacity <= 100000):
            raise ValueError('Invalid read budget')
        with self.pool.connection() as c:
            c.execute('''INSERT INTO research_read_budget(name,refill_per_second,capacity,tokens)
                VALUES(%s,%s,%s,%s) ON CONFLICT(name) DO NOTHING''',
                (self.name, refill_per_second, capacity, capacity))
            row = c.execute('SELECT * FROM research_read_budget WHERE name=%s FOR UPDATE', (self.name,)).fetchone()
            if (row['refill_per_second'], row['capacity']) != (refill_per_second, capacity):
                if not allow_update:raise EvidenceConflict('Read budget already configured differently')
                # Runtime configuration may change pacing, never reset cooldown or mint tokens.
                c.execute('''UPDATE research_read_budget SET refill_per_second=LEAST(refill_per_second,%s),capacity=%s,
                    tokens=LEAST(tokens,%s) WHERE name=%s''',(refill_per_second,capacity,capacity,self.name))

        with self.pool.connection() as c:
            c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at,progress)
                VALUES(%s,'btc',%s,%s,'succeeded',clock_timestamp(),
                    jsonb_build_object('ceiling',%s::double precision,'adjusted_at',clock_timestamp()))
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=research_job.progress||jsonb_build_object('ceiling',%s::double precision)""",
                (uuid4(),Jsonb({'collector':'pacing-v1'}),'pacing/'+self.name,refill_per_second,refill_per_second))

    @timed('budget.take')
    def take(self, cost):
        """Return 0 if reserved, otherwise seconds until caller may try again."""
        if type(cost) is not int or cost < 1:
            raise ValueError('Invalid endpoint token cost')
        with self.pool.connection() as c:
            # Lock before taking the timestamp, then refill/reserve atomically
            # in one database statement. Shared pacing and cooldown are intact.
            row=c.execute('''WITH locked AS MATERIALIZED (
                SELECT * FROM research_read_budget WHERE name=%s FOR UPDATE),
                clocked AS MATERIALIZED (
                    SELECT locked.*,clock_timestamp() AS now FROM locked WHERE capacity>=%s),
                refilled AS MATERIALIZED (
                    SELECT clocked.*,LEAST(capacity,tokens+
                        GREATEST(0,extract(epoch FROM(now-updated_at)))*refill_per_second) AS filled FROM clocked),
                ready AS MATERIALIZED (
                    SELECT refilled.*,GREATEST(0,extract(epoch FROM(blocked_until-now)),
                        (%s-filled)/refill_per_second) AS wait FROM refilled)
                UPDATE research_read_budget b SET
                    tokens=CASE WHEN ready.wait>0 THEN ready.filled ELSE ready.filled-%s END,
                    updated_at=ready.now FROM ready WHERE b.name=ready.name
                RETURNING ceil(ready.wait)::bigint AS seconds''',(self.name,cost,cost,cost)).fetchone()
            if row is None:raise ValueError('Read budget missing or endpoint cost exceeds capacity')
            return row['seconds']

    def defer(self, seconds):
        if type(seconds) is not int or not 1 <= seconds <= 2**40:
            raise ValueError('Invalid provider cooldown')
        with self.pool.connection() as c:
            row = c.execute('''UPDATE research_read_budget SET blocked_until=GREATEST(blocked_until,
                clock_timestamp()+%s*interval '1 second') WHERE name=%s RETURNING name''', (seconds, self.name)).fetchone()
            if row is None: raise ValueError('Read budget missing')

    def rate_limited(self,seconds):
        """Reduce the shared pace after a rejection; never accelerate on restart."""
        if type(seconds) is not int or not 1<=seconds<=2**40:raise ValueError('Invalid provider cooldown')
        with self.pool.connection() as c:
            row=c.execute('''UPDATE research_read_budget SET
                refill_per_second=LEAST(refill_per_second,GREATEST(0.1,refill_per_second/2)),
                tokens=0,updated_at=clock_timestamp(),
                blocked_until=GREATEST(blocked_until,clock_timestamp()+%s*interval '1 second')
                WHERE name=%s RETURNING refill_per_second''',(seconds,self.name)).fetchone()
            if row is None:raise ValueError('Read budget missing')
        with self.pool.connection() as c:
            c.execute("UPDATE research_job SET progress=progress||jsonb_build_object('adjusted_at',clock_timestamp()) WHERE idempotency_key=%s",('pacing/'+self.name,))
        count('provider.pacing_reduced',1)

    def successful(self):
        """Probe upward slowly after a clean minute; a 429 still cuts pace immediately."""
        with self.pool.connection() as c:
            row=c.execute("SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE",('pacing/'+self.name,)).fetchone()
            if row is None:return
            p=row['progress']
            if c.execute("SELECT clock_timestamp() >= %s::timestamptz+interval '60 seconds' AS ready",(p['adjusted_at'],)).fetchone()['ready']:
                c.execute('''UPDATE research_read_budget SET refill_per_second=LEAST(%s,refill_per_second*1.1)
                    WHERE name=%s AND blocked_until<=clock_timestamp()''',(p['ceiling'],self.name))
                c.execute("UPDATE research_job SET progress=progress||jsonb_build_object('adjusted_at',clock_timestamp()) WHERE idempotency_key=%s",('pacing/'+self.name,))

    def authenticated(self,ceiling,key_id):
        """Apply a newly verified account allowance once; retain later backoff."""
        import hashlib
        identity=hashlib.sha256(key_id.encode()).hexdigest()
        with self.pool.connection() as c:
            row=c.execute("SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE",('pacing/'+self.name,)).fetchone()
            previous=row['progress']
            if previous.get('authenticated_key')!=identity or previous.get('authenticated_ceiling')!=ceiling:
                c.execute('UPDATE research_read_budget SET refill_per_second=%s WHERE name=%s',(ceiling,self.name))
                c.execute("UPDATE research_job SET progress=progress||%s WHERE idempotency_key=%s",(Jsonb(dict(authenticated_key=identity,authenticated_ceiling=ceiling)),'pacing/'+self.name))

"""Cross-process conservative token budget; no sleeps while holding DB locks."""
import math
from .telemetry import timed,timing,count

from .queue import EvidenceConflict, text_key


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
                c.execute('''UPDATE research_read_budget SET refill_per_second=%s,capacity=%s,
                    tokens=LEAST(tokens,%s) WHERE name=%s''',(refill_per_second,capacity,capacity,self.name))

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

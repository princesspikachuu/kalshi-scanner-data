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
            row = c.execute('SELECT * FROM research_read_budget WHERE name=%s FOR UPDATE', (self.name,)).fetchone()
            if row is None or cost > row['capacity']:
                raise ValueError('Read budget missing or endpoint cost exceeds capacity')
            now = c.execute('SELECT clock_timestamp() AS t').fetchone()['t']
            tokens = min(row['capacity'], row['tokens'] + max(0, (now-row['updated_at']).total_seconds()) * row['refill_per_second'])
            wait = max(0, (row['blocked_until']-now).total_seconds(), (cost-tokens)/row['refill_per_second'])
            c.execute('UPDATE research_read_budget SET tokens=%s,updated_at=%s WHERE name=%s',
                      (tokens if wait > 0 else tokens-cost, now, self.name))
            return math.ceil(wait)

    def defer(self, seconds):
        if type(seconds) is not int or not 1 <= seconds <= 2**40:
            raise ValueError('Invalid provider cooldown')
        with self.pool.connection() as c:
            row = c.execute('''UPDATE research_read_budget SET blocked_until=GREATEST(blocked_until,
                clock_timestamp()+%s*interval '1 second') WHERE name=%s RETURNING name''', (seconds, self.name)).fetchone()
            if row is None: raise ValueError('Read budget missing')

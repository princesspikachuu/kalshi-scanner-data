"""Durable rolling paper-worker restart counter, independent of dashboard snapshots.

The first observed worker start establishes a baseline. Subsequent starts
(including deliberate Render deployments and same-process router recoveries)
are counted. This does not claim to count failures before database startup.
"""
import math
import time

KEY = 'shadow/worker-starts'
WINDOW_SECONDS = 24 * 60 * 60
MAX_EVENTS = 4096


def _timestamp(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def summarize(record, now=None):
    """A bounded, accurate 24h count, or an explicit unavailable state."""
    now = float(time.time() if now is None else now)
    if not isinstance(record, dict):
        return dict(contract='demo-v1', tracked=False, restarts_24h=None,
                    window_hours=24, full_window=False, lower_bound=False,
                    tracking_since=None, last_started_at=None)
    since = _timestamp(record.get('tracking_since'))
    if since is None:
        return summarize(None, now)
    recent = [_timestamp(t) for t in record.get('recent_restarts', ())
              if _timestamp(t) is not None]
    recent = [t for t in recent if now - WINDOW_SECONDS < t <= now]
    capped_until = _timestamp(record.get('capped_until')) or 0
    limited = now < capped_until
    return dict(contract='demo-v1', tracked=True, restarts_24h=len(recent),
                window_hours=24, full_window=(now - since >= WINDOW_SECONDS and not limited),
                lower_bound=limited, tracking_since=since,
                last_started_at=_timestamp(record.get('last_started_at')))


def record_worker_start(store, now=None):
    """Record once per acquired paper-worker fence; never touch trade state."""
    now = float(time.time() if now is None else now)
    if not math.isfinite(now) or now <= 0:
        raise ValueError('Invalid restart timestamp')
    previous = store.get(KEY)
    old = previous.get('progress', {}) if previous else {}
    if not isinstance(old, dict):
        old = {}
    last = _timestamp(old.get('last_started_at'))
    since = _timestamp(old.get('tracking_since')) or now
    recent = [_timestamp(t) for t in old.get('recent_restarts', ())
              if _timestamp(t) is not None]
    recent = [t for t in recent if now - WINDOW_SECONDS < t <= now]
    if last is not None:
        recent.append(now)
    # Never let an extreme crash loop create an unbounded JSONB control row.
    capped_until = _timestamp(old.get('capped_until')) or 0
    if len(recent) > MAX_EVENTS:
        dropped = recent[:-MAX_EVENTS]
        recent = recent[-MAX_EVENTS:]
        capped_until = max(capped_until, max(dropped) + WINDOW_SECONDS)
    store.put(KEY, dict(tracking_since=since, last_started_at=now,
                        recent_restarts=recent, capped_until=capped_until))
    return summarize(dict(tracking_since=since, last_started_at=now,
                          recent_restarts=recent, capped_until=capped_until), now)

"""Durable report pacing; frozen retry membership is never replaced or discarded."""
import math
from .queue import ResearchQueue
INTERVAL_SECONDS=30


def delay(pool,stream):
    if INTERVAL_SECONDS==0:return 0
    with pool.connection() as c:
        row=c.execute('''SELECT greatest(0,extract(epoch FROM(max(published_at)+%s*interval '1 second'-clock_timestamp()))) AS seconds
            FROM research_result WHERE stream_key=%s''',(INTERVAL_SECONDS,stream)).fetchone()
    return min(INTERVAL_SECONDS,math.ceil(float(row['seconds'] or 0)))


def defer_unfrozen(queue,job,stream,snapshot_key,*,urgent=False):
    if urgent or snapshot_key in job['progress']:return False
    seconds=delay(queue.pool,stream)
    if seconds:
        queue.yield_job(job['id'],job['lease_token'],seconds);return True
    return False


def coalesce(c,job,revision,*,campaign=False):
    # Only queued, unfrozen jobs explicitly requiring a covered revision may be
    # retired. A new revision committed while we built remains independently due.
    key='snapshot' if campaign else 'category_snapshot'
    version='revision' if campaign else 'source_revision'
    identity="AND parameters->>'campaign_id'=%s" if campaign else 'AND asset=%s'
    value=job['parameters']['campaign_id'] if campaign else job['asset']
    c.execute(f'''UPDATE research_job SET status='succeeded',finished_at=clock_timestamp(),
        progress=jsonb_build_object('coalesced_by',%s::text)
        WHERE id<>%s AND status='queued' AND parameters->>'collector'=%s {identity}
            AND NOT (progress ? %s) AND parameters ? %s
            AND (parameters->>%s)::bigint<=%s''',
        (str(job['id']),job['id'],job['parameters']['collector'],value,key,version,version,revision))
    c.execute(f'''UPDATE research_job SET available_at=greatest(available_at,clock_timestamp()+%s*interval '1 second')
        WHERE status='queued' AND parameters->>'collector'=%s {identity}
            AND NOT (progress ? %s) AND NOT coalesce((parameters->>'urgent')::boolean,false)''',
        (INTERVAL_SECONDS,job['parameters']['collector'],value,key))

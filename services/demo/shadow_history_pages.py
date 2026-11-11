"""Index-keyset pagination of owner shadow raw and packed histories.

Provides a bounded way to page beyond the 100 most recent events without
materializing every historic research_job row. It explicitly does NOT include
old R2 reclaimed manifests; those remain available via separately gated
/demo/shadow/archives. All access is read-only.
"""
import re

from services.paper_demo.shadow.diagnostic_batches import decode_diagnostic_batch
from services.demo.shadow_pointer_history import rehydrate_event_rows

RAW_PREFIX = 'demo/shadow/event/'
PACKED_PREFIX = 'demo/shadow/event-batch/'
MAX_RAW_ROWS = 4  # One read-only R2 object per event in the worst case.
MAX_PACKED_ROWS = 1  # A batch can represent up to 64 original events.

RAW_SQL = """SELECT id::text,idempotency_key,parameters,progress,created_at
    FROM research_job WHERE idempotency_key>%s AND idempotency_key<%s
    ORDER BY idempotency_key LIMIT %s"""
PACKED_SQL = """SELECT id::text,idempotency_key,parameters,progress,created_at
    FROM research_job WHERE idempotency_key>%s AND idempotency_key<%s
    ORDER BY idempotency_key LIMIT %s"""


def validate_cursor(source, cursor):
    if source not in ('raw', 'packed'):
        raise ValueError('Unknown diagnostic history source')
    prefix = RAW_PREFIX if source == 'raw' else PACKED_PREFIX
    if cursor is None:
        return prefix
    if (not isinstance(cursor, str) or len(cursor) > 150
            or re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_.-]{1,100}',
                            cursor) is None):
        raise ValueError('Invalid history cursor')
    return cursor


def page_history(pool, source, *, cursor=None):
    """Return one bounded SQL keyset page and its original event identities.

    Key order is deliberately NOT represented as event timestamp order; the
    client must use each event's time for temporal analysis. Cursor pages are
    not a transactional snapshot if other writers append during pagination.
    """
    after = validate_cursor(source, cursor)
    raw = source == 'raw'
    limit = MAX_RAW_ROWS if raw else MAX_PACKED_ROWS
    prefix = RAW_PREFIX if raw else PACKED_PREFIX
    sql = RAW_SQL if raw else PACKED_SQL
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute('SET LOCAL statement_timeout=5000')
            rows = connection.execute(sql, (after, prefix + 'zzzz',
                                            limit + 1)).fetchall()
    page = rows[:limit]
    cold_rows = cold_objects = 0
    if raw:
        page, cold_rows, cold_objects = rehydrate_event_rows(page)
        events = [
            dict(id=row['id'], key=row['idempotency_key'],
                 parameters=row['parameters'], progress=row['progress'],
                 recorded_at=row['created_at'].isoformat(),
                 event_time=row['progress'].get('time'))
            for row in page
        ]
    else:
        events = []
        for batch in page:
            originals = decode_diagnostic_batch(batch['progress'])
            for event in originals:
                events.append(dict(id=event['id'], key=event['key'],
                                   parameters=event['parameters'],
                                   progress=event['progress'],
                                   recorded_at=None,
                                   event_time=event['progress'].get('time'),
                                   packed_batch_key=batch['idempotency_key']))
    more = len(rows) > limit
    return dict(contract='demo-v1', source=source,
                order='idempotency_key_ascending', items=events,
                source_rows=len(page), original_events=len(events),
                next_cursor=page[-1]['idempotency_key'] if more else None,
                more=more, max_source_rows=limit,
                archived_rows_rehydrated=cold_rows,
                archive_objects_verified=cold_objects,
                reclaimed_manifests_included=False,
                all_time_coverage_complete=False,
                real_orders_enabled=False)

"""One read-only REPEATABLE READ snapshot of bounded shadow key namespaces.

This is for offline/owner diagnostics only, not an API or background scanner.
The snapshot covers PostgreSQL source *index keys*, not verified R2 objects
or authoritative historical Favorites outcomes.
"""
import hashlib
import json

from services.demo.shadow_history_pages import (
    RAW_PREFIX, PACKED_PREFIX, validate_cursor,
)
from services.demo.shadow_archive_reader import (
    PREFIX as MANIFEST_PREFIX, validate_page as validate_manifest_page,
)

MAX_WINDOW_KEYS=32
SOURCE_PREFIXES={'raw':RAW_PREFIX,'packed':PACKED_PREFIX,'manifests':MANIFEST_PREFIX}
KEY_SQL="""SELECT idempotency_key FROM research_job
    WHERE idempotency_key>%s AND idempotency_key<%s
    ORDER BY idempotency_key LIMIT %s"""
MANIFEST_KEYS_SQL="""SELECT idempotency_key FROM research_job
    WHERE idempotency_key>%s AND idempotency_key<%s
    AND status='succeeded'
    AND parameters->>'kind' IN
       ('shadow_event_r2_manifest','diagnostic_batch_r2_manifest')
    AND progress->>'format' IN
       ('shadow-r2-event-batch-v1','shadow-diagnostic-r2-manifest-v1')
    ORDER BY idempotency_key LIMIT %s"""


def read_postgres_snapshot_window(pool, *, page_size=16, cursors=None):
    """Read 3 bounded index windows in the exact SAME PostgreSQL snapshot.

    Connection/pool is caller-supplied; the function will not open a network
    connection except borrowing this one. It never calls R2 or changes rows.
    """
    if type(page_size) is not int or not 1<=page_size<=MAX_WINDOW_KEYS:
        raise ValueError('Invalid snapshot window size')
    if cursors is None:cursors={}
    if not isinstance(cursors,dict) or set(cursors)-set(SOURCE_PREFIXES):
        raise ValueError('Unknown snapshot namespace cursor')
    cursors=dict(cursors)
    for source,cursor in cursors.items():
        if source=='manifests':
            validate_manifest_page(1,cursor)
        else:
            validate_cursor(source,cursor)
    windows={}
    with pool.connection() as connection:
        with connection.transaction():
            # Must precede the first SELECT. If this cannot be applied, abort
            # instead of claiming a stable/consistent snapshot.
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            connection.execute('SET LOCAL statement_timeout=5000')
            marker=connection.execute(
                'SELECT txid_current_snapshot()::text AS snapshot').fetchone()['snapshot']
            for source,prefix in SOURCE_PREFIXES.items():
                after=cursors.get(source) or prefix
                query=MANIFEST_KEYS_SQL if source=='manifests' else KEY_SQL
                rows=connection.execute(query,(after,prefix+'zzzz',page_size+1)).fetchall()
                keys=[row['idempotency_key'] for row in rows[:page_size]]
                if any(not isinstance(k,str) or not prefix<k<prefix+'zzzz'
                       or k<=after for k in keys):
                    raise ValueError('Invalid scanned index key')
                if keys!=sorted(keys) or len(set(keys))!=len(keys):
                    raise ValueError('Unsorted or repeated snapshot index keys')
                for key in keys:
                    if source=='manifests':
                        validate_manifest_page(1,key)
                    else:
                        validate_cursor(source,key)
                more=len(rows)>page_size
                digest=hashlib.sha256(
                    json.dumps(keys,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
                windows[source]=dict(source=source,
                    request_cursor=cursors.get(source),
                    rows_in_window=len(keys),
                    key_fingerprint=digest,
                    first_index_key=keys[0] if keys else None,
                    last_index_key=keys[-1] if keys else None,
                    more=more,
                    next_cursor=keys[-1] if more else None)
    first_window=all(cursors.get(source) is None for source in SOURCE_PREFIXES)
    all_end=all(not value['more'] for value in windows.values())
    return dict(contract='mt019-postgres-index-snapshot-window-v1',
                transaction_snapshot=str(marker),
                isolation='repeatable_read_read_only',
                postgres_source_window_consistent=True,
                indexed_namespaces_fully_scanned_in_this_snapshot=first_window and all_end,
                windows=windows,
                source_exhaustion_verified=False,
                r2_object_readback_verified=False,
                r2_manifest_catalog_complete=False,
                all_time_coverage_complete=False,
                authoritative_financial_outcomes=0,
                safe_to_train=False,
                safe_to_restart_writers=False)

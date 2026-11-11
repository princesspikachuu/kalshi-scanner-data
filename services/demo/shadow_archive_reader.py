"""Owner-only, bounded cold-history inspection of verified shadow R2 archives.

Listing uses the existing PostgreSQL manifest index and no R2 call. Reading
one manifest requires separate R2 *read-only* credentials and full verification.
Never returns R2 object paths, signed URLs or database credentials.
"""
import os
import re
from uuid import UUID

from services.demo.shadow_archive_recovery import verify_archived_manifest
from services.demo.shadow_batch_archive_recovery import verify_batch_manifest
from services.paper_demo.shadow.diagnostic_batches import decode_diagnostic_batch
from services.research.r2 import R2Objects

PREFIX = 'demo/shadow/archive-manifest/'
MAX_PAGE = 25
MAX_EVENTS = 50
MANIFEST_SCAN = """SELECT id::text,idempotency_key,parameters,progress,created_at
    FROM research_job WHERE idempotency_key>=%s
    AND idempotency_key<%s AND (%s::text IS NULL OR idempotency_key>%s)
    AND status='succeeded'
    AND parameters->>'kind' IN
        ('shadow_event_r2_manifest','diagnostic_batch_r2_manifest')
    AND progress->>'format' IN
        ('shadow-r2-event-batch-v1','shadow-diagnostic-r2-manifest-v1')
    ORDER BY idempotency_key LIMIT %s"""
MANIFEST_BY_ID = """SELECT id::text,idempotency_key,parameters,progress,created_at
    FROM research_job WHERE id=%s::uuid
    AND idempotency_key>=%s AND idempotency_key<%s
    AND status='succeeded'"""


class ArchiveReaderUnavailable(RuntimeError):
    pass


def validate_page(limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ValueError('Archive page limit invalid')
    if cursor is not None and (
        not isinstance(cursor, str) or len(cursor) > 128
        or not re.fullmatch(r'demo/shadow/archive-manifest/(?:batch/)?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', cursor)
    ):
        raise ValueError('Invalid archive cursor')
    return limit, cursor


def summary(row):
    manifest = row['progress']
    kind = row['parameters'].get('kind')
    count = manifest.get('count')
    if (kind not in ('shadow_event_r2_manifest','diagnostic_batch_r2_manifest')
            or type(count) is not int or count < 1):
        raise ValueError('Invalid durable archive manifest')
    original_events = count if kind == 'shadow_event_r2_manifest' else manifest.get('original_events')
    if type(original_events) is not int or original_events < count:
        raise ValueError('Invalid durable archive event count')
    return dict(manifest_id=row['id'], manifest_key=row['idempotency_key'],
                kind='raw' if kind == 'shadow_event_r2_manifest' else 'packed',
                archived_rows=count, original_events=original_events,
                earliest=manifest.get('earliest'), latest=manifest.get('latest'),
                manifest_created_at=row['created_at'].isoformat() if row.get('created_at') else None,
                verification='verify-on-read')


def list_manifests(pool, *, limit=10, cursor=None):
    limit,cursor=validate_page(limit,cursor)
    with pool.connection() as connection:
        rows=connection.execute(MANIFEST_SCAN, (PREFIX, PREFIX+'zzzz',
            cursor,cursor,limit+1)).fetchall()
    page=rows[:limit]
    return dict(contract='demo-v1', items=[summary(row) for row in page],
                next_cursor=page[-1]['idempotency_key'] if len(rows)>limit else None,
                more=len(rows)>limit, order='manifest_key', no_r2_reads=True)


def find_manifest(pool, identifier):
    try:
        ident=str(UUID(identifier))
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Invalid archive manifest identifier') from None
    with pool.connection() as connection:
        row=connection.execute(MANIFEST_BY_ID,(ident,PREFIX,PREFIX+'zzzz')).fetchone()
    if not row:
        return None
    # Fail closed if another type of research_job row occupies the archive namespace.
    summary(row)
    kind=row['parameters'].get('kind')
    expected='shadow-r2-event-batch-v1' if kind=='shadow_event_r2_manifest' else 'shadow-diagnostic-r2-manifest-v1'
    if row['progress'].get('format')!=expected:
        raise ValueError('Archive kind/format mismatch')
    return row


def read_store(env=None):
    env=os.environ if env is None else env
    if env.get('MT_ARCHIVE_READ_ENABLED','false')!='true':
        raise ArchiveReaderUnavailable('Cold-history reader is disabled')
    required=('R2_ACCOUNT_ID','R2_BUCKET','R2_READ_ACCESS_KEY_ID','R2_READ_SECRET_ACCESS_KEY')
    if not all(isinstance(env.get(k),str) and env[k] for k in required):
        raise ArchiveReaderUnavailable('Separate R2 read-only credentials required')
    return R2Objects.connect(account_id=env['R2_ACCOUNT_ID'],bucket=env['R2_BUCKET'],
        access_key_id=env['R2_READ_ACCESS_KEY_ID'],
        secret_access_key=env['R2_READ_SECRET_ACCESS_KEY'])


def read_manifest_events(pool, identifier, *, offset=0, limit=25, env=None,
                         store_factory=read_store):
    if type(offset) is not int or not 0 <= offset <= 10000:
        raise ValueError('Invalid archive offset')
    if type(limit) is not int or not 1 <= limit <= MAX_EVENTS:
        raise ValueError('Invalid archive event page size')
    manifest_row=find_manifest(pool,identifier)
    if manifest_row is None:
        return None
    kind=manifest_row['parameters']['kind']
    objects=None
    try:
        objects=store_factory(env)
        manifest=manifest_row['progress']
        if kind=='shadow_event_r2_manifest':
            records=verify_archived_manifest(objects,manifest)
            events=[dict(id=row['id'],key=row['idempotency_key'],parameters=row['parameters'],
                         progress=row['progress'],created_at=row['created_at'])
                    for row in records]
        else:
            records=verify_batch_manifest(objects,manifest)
            events=[dict(id=item['id'],key=item['key'],parameters=item['parameters'],
                         progress=item['progress'],created_at=row['created_at'])
                    for row in records for item in decode_diagnostic_batch(row['progress'])]
            if len(events)!=manifest['original_events']:
                raise ValueError('Expanded archive event count mismatch')
        page=events[offset:offset+limit]
        return dict(contract='demo-v1',manifest=summary(manifest_row),
                    total_events=len(events),items=page,
                    next_offset=offset+len(page) if offset+len(page)<len(events) else None,
                    verified=True,source='cloudflare-r2',real_orders_enabled=False)
    finally:
        if objects is not None:objects.client.close()

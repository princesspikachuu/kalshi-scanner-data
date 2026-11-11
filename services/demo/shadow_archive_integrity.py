"""Verify archived shadow diagnostic history against actual R2 objects and PostgreSQL.

One shot, SELECT-only, exclusively on a disabled recovery-held collector.
Reports aggregate verified counts. Never prints row data, object paths or secrets.
"""
import json
import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.demo.maintenance import object_store
from services.demo.shadow_archive_recovery import verify_archived_manifest
from services.demo.shadow_batch_archive_recovery import verify_batch_manifest

CONNECTION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=5000'
MANIFEST_QUERY = """SELECT id::text,idempotency_key,parameters,progress
    FROM research_job WHERE
    idempotency_key >= 'demo/shadow/archive-manifest/'
    AND idempotency_key < 'demo/shadow/archive-manifest/zzzz'
    AND status='succeeded'
    AND parameters->>'kind' IN
        ('shadow_event_r2_manifest','diagnostic_batch_r2_manifest')
    ORDER BY created_at DESC,id DESC LIMIT 3"""
SOURCE_QUERY = """SELECT id::text FROM research_job
    WHERE id=ANY(%s::uuid[]) LIMIT 1"""


def is_authorized(env, settings):
    if env.get('MT_ARCHIVE_VERIFY_ONCE', 'false') != 'true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD') == 'true'
            and settings.role == 'collector'
            and settings.enabled is False
            and settings.acceptance == 'off'
            and settings.operator_action == 'off'
            and env.get('MT_ARCHIVE_RECOVERY_LOOP', 'false') != 'true'):
        raise ValueError('R2 verification requires an idle recovery-held collector')
    return True


def inspect(pool, objects):
    """Validate up to three durable manifests and each referenced R2 object."""
    with pool.connection() as connection:
        candidates = connection.execute(MANIFEST_QUERY).fetchall()
    summary = dict(manifests_scanned=len(candidates), verified_manifests=0,
                   original_rows_verified=0, original_events_verified=0,
                   compressed_bytes_verified=0, deleted_rows_absent=0)
    for candidate in candidates:
        manifest = candidate['progress']
        kind = candidate['parameters']['kind']
        if kind == 'shadow_event_r2_manifest':
            records = verify_archived_manifest(objects, manifest)
            row_ids = manifest['ids']
            original_events = len(records)
        elif kind == 'diagnostic_batch_r2_manifest':
            records = verify_batch_manifest(objects, manifest)
            row_ids = manifest['row_ids']
            original_events = manifest['original_events']
        else:
            raise ValueError('Unexpected archival manifest kind')
        if any(not isinstance(r.get('id'), str) for r in records):
            raise ValueError('Archive rows are missing canonical identities')
        if set(r['id'] for r in records) != set(row_ids):
            raise ValueError('Manifest/source identities disagree')
        with pool.connection() as connection:
            still_live = connection.execute(SOURCE_QUERY, (row_ids,)).fetchone()
        if still_live is not None:
            raise ValueError('Archived source row is still present in PostgreSQL')
        summary['verified_manifests'] += 1
        summary['original_rows_verified'] += len(records)
        summary['original_events_verified'] += original_events
        summary['compressed_bytes_verified'] += manifest['reference']['size']
        summary['deleted_rows_absent'] += len(row_ids)
    return summary


def audit_once(database_url, env=None, *, pool_factory=ConnectionPool,
               store_factory=object_store, emit=print):
    """Does not alter the database, including when verification fails."""
    env = os.environ if env is None else env
    report = dict(event='shadow_archive_r2_integrity', mode='read_only',
                  verified=False, no_deletion=True)
    store = None
    try:
        with pool_factory(database_url, min_size=1, max_size=1, open=True,
                          timeout=6, kwargs=dict(row_factory=dict_row,
                            connect_timeout=5, options=CONNECTION_OPTIONS)) as pool:
            store = store_factory(env)
            report.update(inspect(pool, store))
            report['verified'] = report['verified_manifests'] > 0
            if not report['verified']:
                report['reason'] = 'no_archive_manifests_found'
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        if store is not None:
            store.client.close()
    emit(json.dumps(report, sort_keys=True), flush=True)
    return report

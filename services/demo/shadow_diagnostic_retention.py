"""Bounded online retention for unchanged, 24h+ nonfinancial diagnostics.

Separate maintenance process, never imported by trading/startup. Preview is
read-only. Execution is explicitly enabled after recovery, using the existing
scoped SQL fence; no stopped-writer assertion or broad DELETE grant is used.
"""
import argparse
import json
import os
import signal
import sys
import time
from threading import Event
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from services.demo.maintenance import object_store
from services.demo.shadow_archive_automatic import database_bytes, verify_scoped_role
from services.demo.shadow_archive_recovery import (
    PREFIX, SAFE_EVENT_KINDS, SCOPED_RECLAIM_SQL, _prepare_verified_archive,
    _check_reclaimed,
)
from services.demo.shadow_batch_archive_recovery import (
    BATCH_PREFIX, _prepare_verified_batch, _check_batch_reclaim,
)
from services.demo.shadow_prefix_boundary_guard import assert_no_hidden_prefix_keys

FIELDS = """id::text,idempotency_key,asset,status,parameters,progress,
    created_at,started_at,finished_at,lease_expires_at,attempts,error_code,
    available_at,max_attempts,lease_token"""
# First bound the keys examined, THEN inspect eligibility. LIMIT on a query
# filtering event JSON alone can scan millions of protected/fresh rows.
KEY_PAGE = """SELECT idempotency_key FROM research_job
    WHERE idempotency_key>%s AND idempotency_key<%s
    ORDER BY idempotency_key LIMIT %s"""
SOURCE_PAGE = f"""SELECT {FIELDS} FROM research_job
    WHERE idempotency_key=ANY(%s::text[])
      AND asset='crypto' AND status='succeeded'
      AND created_at<to_timestamp(%s) AND NOT(progress ? 'archive')
      AND (CASE WHEN %s THEN progress->>'event'=ANY(%s::text[])
           ELSE progress->>'format'='shadow-diagnostic-batch-v1' END)
    ORDER BY idempotency_key"""


def settings(env, execute):
    url = env.get('RECOVERY_DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://')):
        raise ValueError('Separate private RECOVERY_DATABASE_URL required')
    if url == env.get('DATABASE_URL'):
        raise ValueError('Normal application credential cannot run retention')
    if execute:
        for flag in ('MT_DIAGNOSTIC_RETENTION_ENABLED',
                     'MT_DIAGNOSTIC_RETENTION_READ_PATH_VERIFIED',
                     'MT_DIAGNOSTIC_RETENTION_HEADROOM_VERIFIED'):
            if env.get(flag) != 'true':
                raise ValueError('Online retention requires explicit readiness flags')
        if env.get('MT_STORAGE_RECOVERY_HOLD') != 'false':
            raise ValueError('Online retention cannot bypass the recovery hold')
        if env.get('MT_ARCHIVE_RECOVERY_LOOP', 'false') != 'false':
            raise ValueError('Recovery archival and online retention cannot overlap')
    capacity = env.get('DATABASE_CAPACITY_GB', '')
    if not capacity.isascii() or not capacity.isdecimal() or not 1 <= int(capacity) <= 16000:
        raise ValueError('Verified database capacity required')
    return url, int(capacity)


def select_page(pool, prefix, after, *, now, age_hours=24, page_size=100):
    max_page = 100 if prefix == PREFIX else 8
    if prefix not in (PREFIX, BATCH_PREFIX) or type(page_size) is not int or not 1 <= page_size <= max_page:
        raise ValueError('Invalid bounded retention page')
    if type(age_hours) is not int or not 24 <= age_hours <= 8760:
        raise ValueError('Retention must preserve at least 24 hours')
    if not isinstance(after, str) or not prefix <= after < prefix+'zzzz':
        raise ValueError('Invalid namespace cursor')
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            c.execute('SET LOCAL statement_timeout=5000')
            c.execute('SET LOCAL lock_timeout=1000')
            keys = [r['idempotency_key'] for r in c.execute(
                KEY_PAGE, (after, prefix+'zzzz', page_size)).fetchall()]
            rows = c.execute(SOURCE_PAGE, (
                keys, now-age_hours*3600, prefix == PREFIX,
                list(SAFE_EVENT_KINDS))).fetchall() if keys else []
            complete = len(keys) < page_size
            if complete:
                assert_no_hidden_prefix_keys(c, [prefix])
    return rows, (prefix if complete else keys[-1]), len(keys), complete


def reclaim_page(pool, objects, rows, prefix, now):
    """No SQL transaction is open during R2 upload/readback.

    Existing SECURITY DEFINER fence locks/rechecks ALL original columns and
    creates the manifest + deletes exact IDs atomically. Concurrent mutation
    aborts the entire page. Finances, controls, current-day and unknown events
    are ineligible; packed rows are fully decoded before uploading.
    """
    if not rows:
        return dict(deleted_rows=0, original_events=0, archived_compressed_bytes=0,
                    source_json_bytes=0)
    if prefix == PREFIX:
        records, ids, manifest, receipt = _prepare_verified_archive(rows, objects, now)
        kind = 'shadow_event_r2_manifest'
        originals = len(ids)
    elif prefix == BATCH_PREFIX:
        records, ids, receipt, manifest = _prepare_verified_batch(rows, objects, now)
        kind = 'diagnostic_batch_r2_manifest'
        originals = len(ids)
    else:
        raise ValueError('Unrelated retention namespace')
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET LOCAL statement_timeout=10000')
            c.execute('SET LOCAL lock_timeout=1000')
            deleted = c.execute(SCOPED_RECLAIM_SQL, (
                uuid4(), kind, Jsonb(manifest), Jsonb(records))).fetchall()
            if prefix == PREFIX:
                _check_reclaimed(deleted, ids)
            else:
                _check_batch_reclaim(deleted, manifest, len(rows))
    # These are source JSON serialization bytes, NOT physical disk reclaimed.
    source_bytes = sum(len(json.dumps(dict(parameters=r['parameters'], progress=r['progress']),
                                     separators=(',', ':')).encode()) for r in records)
    return dict(deleted_rows=len(rows), original_events=originals,
                archived_compressed_bytes=receipt['size'], source_json_bytes=source_bytes)


def cycle(pool, objects, cursors, *, now, capacity_gb, execute=False,
          pages=10, age_hours=24, raw_page_size=100, packed_page_size=2,
          stopped=lambda: False):
    if type(pages) is not int or not 1 <= pages <= 100:
        raise ValueError('Invalid cycle page budget')
    if (type(raw_page_size) is not int or not 1 <= raw_page_size <= 100
            or type(packed_page_size) is not int or not 1 <= packed_page_size <= 8):
        raise ValueError('Invalid namespace page budget')
    before = database_bytes(pool)
    if execute:
        # Additional logical guard; readiness acknowledgment is still needed
        # for actual physical/WAL capacity. Neither is inferred from this size.
        if before > capacity_gb*1_000_000_000*0.80:
            raise RuntimeError('Logical capacity guard exceeded')
        verify_scoped_role(pool)
    report = dict(event='shadow_diagnostic_retention', mode='execute' if execute else 'preview',
                  scanned_rows=0, eligible_rows=0, deleted_rows=0, original_events=0,
                  source_json_bytes=0, archived_compressed_bytes=0, completed_passes=0,
                  database_bytes_before=before, physical_bytes_freed=None)
    # Alternate raw/packed pages so one namespace cannot starve the other.
    completed = set()
    for _ in range(pages):
        for prefix in (PREFIX, BATCH_PREFIX):
            if prefix in completed:
                continue
            if stopped():
                return report
            rows, after, scanned, complete = select_page(
                pool, prefix, cursors.get(prefix, prefix), now=now,
                age_hours=age_hours, page_size=raw_page_size if prefix == PREFIX else packed_page_size)
            if execute:
                result = reclaim_page(pool, objects, rows, prefix, now)
                for key, value in result.items():
                    report[key] += value
            # Never advance on archive failure, bad readback or SQL conflict.
            cursors[prefix] = after
            report['scanned_rows'] += scanned
            report['eligible_rows'] += len(rows)
            report['completed_passes'] += int(complete)
            if complete:
                completed.add(prefix)
        if len(completed) == 2:
            break
    report['database_bytes_after'] = database_bytes(pool)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--continuous', action='store_true')
    parser.add_argument('--pages', type=int, default=10)
    parser.add_argument('--interval-seconds', type=int, default=60)
    parser.add_argument('--age-hours', type=int, default=24)
    parser.add_argument('--raw-page-size', type=int, default=100)
    parser.add_argument('--packed-page-size', type=int, default=2)
    opts = parser.parse_args(argv)
    if not 1 <= opts.pages <= 100 or not 10 <= opts.interval_seconds <= 3600 or not 24 <= opts.age_hours <= 8760:
        parser.error('Invalid bounded retention limits')
    if not 1 <= opts.raw_page_size <= 100 or not 1 <= opts.packed_page_size <= 8:
        parser.error('Invalid namespace page sizes')
    if opts.continuous and not opts.execute:
        parser.error('Preview is one bounded cycle, never continuous')
    objects = None
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        url, capacity = settings(os.environ, opts.execute)
        with ConnectionPool(url, min_size=1, max_size=1, timeout=6,
                            kwargs=dict(row_factory=dict_row, connect_timeout=5)) as pool:
            if opts.execute:
                verify_scoped_role(pool)
                objects = object_store(os.environ)
            cursors = {}
            while not stop.is_set():
                report = cycle(pool, objects, cursors, now=time.time(), capacity_gb=capacity,
                               execute=opts.execute, pages=opts.pages,
                               age_hours=opts.age_hours, raw_page_size=opts.raw_page_size,
                               packed_page_size=opts.packed_page_size, stopped=stop.is_set)
                print(json.dumps(report, sort_keys=True), flush=True)
                if not opts.continuous:
                    break
                stop.wait(opts.interval_seconds)
    except Exception as exc:
        print(json.dumps(dict(event='shadow_diagnostic_retention_stopped',
                              error_type=type(exc).__name__, operator_review_required=True)),
              file=sys.stderr, flush=True)
        return 1
    finally:
        if objects is not None:
            objects.client.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Opt-in, recovery-hold-only archival loop for old non-financial paper diagnostics.

This never runs by default. It requires a separate, non-owner maintenance role,
a halted paper writer, and an explicit multi-flag operator acknowledgment.
No schedule is activated when this file is deployed.
"""
import json
import os
import re
import sys
import time
from dataclasses import dataclass

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.demo.maintenance import object_store
from services.demo.shadow_archive_recovery import archive_and_reclaim_one
from services.demo.shadow_batch_archive_recovery import archive_one


@dataclass(frozen=True)
class Limits:
    database_url: str
    capacity_gb: int
    interval_seconds: int
    raw_batch_size: int
    raw_batches: int
    packed_batch_size: int
    packed_batches: int
    run_id: str = ""


def configuration(env):
    """Require recovery hold, stopped writers, and a separate DB credential."""
    required = {
        'MT_ARCHIVE_RECOVERY_LOOP': 'true',
        'MT_ARCHIVE_WRITERS_STOPPED': 'true',
        'MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED': 'true',
        'MT_ARCHIVE_PHYSICAL_HEADROOM_ACKNOWLEDGED': 'true',
        'MT_STORAGE_RECOVERY_HOLD': 'true',
        'WORKER_ROLE': 'collector',
        'COLLECTION_ENABLED': 'false',
        'STAGING_ACCEPTANCE': 'off',
        'STAGING_OPERATOR_ACTION': 'off',
    }
    for name, expected in required.items():
        if env.get(name) != expected:
            raise ValueError('Recovery archival requires explicit disabled-worker safety flags')
    if env.get('MT_STORAGE_RECOVERY_AUDIT', 'false') == 'true':
        raise ValueError('Storage audit and archival must not execute together')
    url = env.get('RECOVERY_DATABASE_URL', '')
    if not isinstance(url, str) or not url.startswith(('postgres://', 'postgresql://')):
        raise ValueError('A private separate RECOVERY_DATABASE_URL is required')
    if url == env.get('DATABASE_URL'):
        raise ValueError('Archival must not use the ordinary application database role')

    def number(key, default, low, high):
        raw = env.get(key, str(default))
        if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
            raise ValueError('Invalid bounded archival setting: '+key)
        value = int(raw)
        if not low <= value <= high:
            raise ValueError('Out-of-range archival setting: '+key)
        return value

    run_id = env.get('MT_ARCHIVE_RUN_ID', '')
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('A fresh 32-character lowercase hex MT_ARCHIVE_RUN_ID is required')

    return Limits(
        url,
        number('DATABASE_CAPACITY_GB', 0, 1, 16000),
        number('MT_ARCHIVE_INTERVAL_SECONDS', 60, 60, 3600),
        number('MT_ARCHIVE_RAW_BATCH_SIZE', 50, 1, 100),
        number('MT_ARCHIVE_RAW_BATCHES', 3, 1, 250),
        number('MT_ARCHIVE_PACKED_BATCH_SIZE', 2, 1, 8),
        number('MT_ARCHIVE_PACKED_BATCHES', 2, 0, 8),
        run_id,
    )


ROLE_QUERY = """SELECT current_user AS principal, current_database() AS database,
    (SELECT tableowner FROM pg_tables
      WHERE schemaname='public' AND tablename='research_job') AS owner,
    (SELECT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication
             OR rolbypassrls OR rolinherit) FROM pg_roles
      WHERE rolname=current_user) AS elevated,
    EXISTS (SELECT 1 FROM pg_auth_members AS m
      JOIN pg_roles AS r ON r.oid=m.member
      WHERE r.rolname=current_user) AS has_memberships,
    has_table_privilege(current_user,'public.research_job','SELECT') AS can_select,
    has_table_privilege(current_user,'public.research_job','INSERT') AS can_insert,
    has_table_privilege(current_user,'public.research_job','DELETE') AS can_delete,
    has_table_privilege(current_user,'public.research_job','UPDATE') AS can_update,
    has_table_privilege(current_user,'public.research_job','TRUNCATE') AS can_truncate,
    has_schema_privilege(current_user,'public','CREATE') AS can_schema_create,
    has_function_privilege(current_user,
      'public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)','EXECUTE') AS can_scoped_reclaim"""


def verify_scoped_role(pool):
    """Refuse owner/admin, inherited/member privileges or broad table writes."""
    with pool.connection() as connection:
        row = connection.execute(ROLE_QUERY).fetchone()
    if (not row or row['principal'] != 'pocket_archive_maintenance'
            or row['database'] != 'pocket_staging'
            or row['owner'] is None or row['principal'] == row['owner']
            or row['elevated'] is not False
            or row['has_memberships'] is not False
            or row['can_insert'] is not False
            or row['can_delete'] is not False or row['can_update'] is not False
            or row['can_truncate'] is not False
            or row['can_schema_create'] is not False
            or not all(row[k] is True for k in
                       ('can_select','can_scoped_reclaim'))):
        raise ValueError('Dedicated non-owner archive role with scoped SQL reclaim only is required')


def database_bytes(pool):
    with pool.connection() as connection:
        return int(connection.execute(
            'SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes'])


def verify_archive_index(pool):
    """Never begin archive cleanup without its verified selective index."""
    with pool.connection() as connection:
        index = connection.execute(
            """SELECT indisvalid, indisready
               FROM pg_index
               WHERE indexrelid = to_regclass(
                   'public.research_job_shadow_archive_events_v2')"""
        ).fetchone()
    if not index or index['indisvalid'] is not True or index['indisready'] is not True:
        raise RuntimeError('Optimized shadow archive index is missing or invalid')


@dataclass(frozen=True)
class RunBudget:
    database_bytes: int
    started: float
    initial_lsn: str


def start_run_budget(pool):
    before = database_bytes(pool)
    started = time.monotonic()
    with pool.connection() as connection:
        initial_lsn = connection.execute(
            'SELECT pg_current_wal_lsn()::text AS lsn').fetchone()['lsn']
    return RunBudget(before, started, initial_lsn)


def claim_run(objects, run_id):
    """Consume a run ID once, before any SQL deletion; never remove its marker.

    A crash after PUT but before read-back intentionally consumes the ID too.
    A restart or a second worker must not reset an already-used WAL budget.
    """
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('Invalid archive run ID')
    payload = json.dumps(dict(format='shadow-recovery-run-v1', run_id=run_id),
                         sort_keys=True, separators=(',', ':')).encode()
    key = 'demo/recovery-runs/' + run_id + '.json'
    objects.client.put_object(Bucket=objects.bucket, Key=key, Body=payload,
                              ContentType='application/json', IfNoneMatch='*')
    response = objects.client.get_object(Bucket=objects.bucket, Key=key)
    stream = response['Body']
    try:
        if (response['ContentLength'] != len(payload)
                or stream.read(len(payload) + 1) != payload):
            raise RuntimeError('Archive run claim verification failed')
    finally:
        stream.close()


def park_until_stopped(stop):
    """Keep the held worker idle instead of triggering a platform crash loop."""
    while not stop.is_set():
        stop.wait(30)


def archive_cycle(pool, objects, limits, *, now=None, stopped=lambda: False,
                  safety_check=lambda: None, budget=None):
    """Bounded, fail-closed work. No financial rows or current-day data eligible."""
    current = time.time() if now is None else now
    safety_check()
    before = database_bytes(pool)
    if budget is None:
        started = time.monotonic()
        with pool.connection() as connection:
            initial_lsn = connection.execute(
                'SELECT pg_current_wal_lsn()::text AS lsn').fetchone()['lsn']
        budget = RunBudget(before, started, initial_lsn)
    started, initial_lsn = budget.started, budget.initial_lsn

    def budget_reason(reading, elapsed):
        if elapsed >= 600:
            return 'time_budget_reached'
        if reading['wal_bytes'] >= 128 * 1024 ** 2:
            return 'wal_budget_reached'
        if (reading['db_bytes'] >= 12_000_000_000
                or reading['db_bytes'] > limits.capacity_gb * 1_000_000_000 * 0.80
                or reading['db_bytes'] > budget.database_bytes + 256 * 1024 ** 2):
            return 'database_growth_guard_reached'
        return None

    def check_budget():
        # Bounds are checked between atomic, R2-verified batches. A batch may
        # exceed a limit slightly; never interrupt an in-flight SQL fence.
        safety_check()
        elapsed = time.monotonic() - started
        if elapsed >= 600:
            return 'time_budget_reached'
        with pool.connection() as connection:
            reading = connection.execute(
                """SELECT pg_database_size(current_database()) AS db_bytes,
                   pg_wal_lsn_diff(pg_current_wal_lsn(), %s::pg_lsn)
                   AS wal_bytes""", (initial_lsn,)).fetchone()
        return budget_reason(reading, elapsed)
    # Logical DB size is not physical volume usage; this is a conservative
    # additional gate, not a substitute for Render's physical disk metrics.
    if before > limits.capacity_gb * 1_000_000_000 * 0.80:
        raise RuntimeError('Database logical capacity guard exceeded; no archival attempted')
    result = dict(event='recovery_archival_cycle', stop_reason=None, raw_rows=0,
                  packed_rows=0, original_packed_events=0,
                  compressed_bytes=0, database_bytes_before=before)
    for _ in range(limits.raw_batches):
        if stopped():
            result['stop_reason'] = 'shutdown_requested'
            break
        reason = check_budget()
        if reason:
            result['stop_reason'] = reason
            break
        receipt = archive_and_reclaim_one(
            pool, objects, now=current, age_hours=24, batch_size=limits.raw_batch_size,
            scoped=True)
        if (receipt.get('archived', 0) != receipt.get('deleted', 0)
                or (receipt.get('archived', 0) and
                    (receipt.get('verified') is not True or receipt.get('manifest_stored') is not True))):
            raise RuntimeError('Raw event archival verification mismatch')
        result['raw_rows'] += receipt.get('archived', 0)
        result['compressed_bytes'] += receipt.get('compressed_bytes', 0)
        if not receipt.get('archived'):
            break
    for _ in range(limits.packed_batches):
        if stopped():
            result['stop_reason'] = 'shutdown_requested'
            break
        if result['stop_reason']:
            break
        reason = check_budget()
        if reason:
            result['stop_reason'] = reason
            break
        receipt = archive_one(
            pool, objects, now=current, age_hours=24, batch_size=limits.packed_batch_size,
            scoped=True)
        if (receipt.get('archived_rows', 0) != receipt.get('deleted_rows', 0)
                or (receipt.get('archived_rows', 0) and receipt.get('verified') is not True)):
            raise RuntimeError('Packed diagnostic archival verification mismatch')
        result['packed_rows'] += receipt.get('archived_rows', 0)
        result['original_packed_events'] += receipt.get('original_events', 0)
        result['compressed_bytes'] += receipt.get('compressed_bytes', 0)
        if not receipt.get('archived_rows'):
            break
    with pool.connection() as connection:
        final = connection.execute(
            """SELECT pg_database_size(current_database()) AS db_bytes,
               pg_wal_lsn_diff(pg_current_wal_lsn(), %s::pg_lsn)
               AS wal_bytes""", (initial_lsn,)).fetchone()
    result['database_bytes_after'] = int(final['db_bytes'])
    result['wal_bytes'] = int(final['wal_bytes'])
    elapsed = time.monotonic() - started
    # The last allowed batch can cross a budget too. Report it before run()
    # can reset the WAL baseline and start another cycle.
    if result['stop_reason'] is None:
        result['stop_reason'] = budget_reason(final, elapsed)
    result['elapsed_seconds'] = round(elapsed, 3)
    return result


def run(stop, env=None):
    """Run one durably claimed recovery session, then park until shutdown."""
    env = os.environ if env is None else env
    limits = configuration(env)
    objects = None
    try:
        with ConnectionPool(limits.database_url, min_size=1, max_size=1, open=True,
                            timeout=6, kwargs=dict(row_factory=dict_row,
                            connect_timeout=5)) as pool:
            verify_scoped_role(pool)
            verify_archive_index(pool)
            objects = object_store(env)
            if stop.is_set():
                return
            claim_run(objects, limits.run_id)
            budget = start_run_budget(pool)
            while not stop.is_set():
                # Flags may be changed while the process is running; fail closed
                # before each atomic archival batch, not just at startup.
                def safety_check():
                    current_limits = configuration(env)
                    if current_limits != limits:
                        raise RuntimeError('Archival configuration changed during run')

                report = archive_cycle(pool, objects, limits,
                                       stopped=stop.is_set,
                                       safety_check=safety_check, budget=budget)
                print(json.dumps(report, sort_keys=True), flush=True)
                if report['stop_reason'] not in (None, 'shutdown_requested'):
                    raise RuntimeError('Archive safety budget reached; operator review required')
                if report['stop_reason'] == 'shutdown_requested':
                    break
                if report['raw_rows'] == 0 and report['packed_rows'] == 0:
                    print(json.dumps(dict(event='recovery_archival_complete',
                                          action='operator_review_required')), flush=True)
                    break
                stop.wait(limits.interval_seconds)
    except Exception as error:
        # Never print PostgreSQL URLs, provider responses or secret-bearing errors.
        print(json.dumps(dict(event='recovery_archival_stopped',
                              error_type=type(error).__name__,
                              action='operator_review_required')),
              file=sys.stderr, flush=True)
    finally:
        if objects is not None:
            try:
                objects.client.close()
            except Exception as error:
                print(json.dumps(dict(event='recovery_archival_close_failed',
                                      error_type=type(error).__name__,
                                      action='operator_review_required')),
                      file=sys.stderr, flush=True)

    # A budget stop, exhausted backlog, failed claim or failed verification
    # stays stopped. A fresh reviewed run ID is required after a restart.
    park_until_stopped(stop)

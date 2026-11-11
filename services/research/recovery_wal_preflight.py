"""MT-019 opt-in one-shot PostgreSQL WAL and role census on a held worker.

This cannot measure Render's physical available filesystem blocks, prove that
all external writers are stopped, or authorize deletion. All SQL is aggregate
SELECT-only, with a read-only connection and short per-statement timeouts.
Never emit URLs, SQL parameters, session queries, user names or credentials.
"""
import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

CONNECTION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=3000'
INCOMPATIBLE_FLAGS = (
    'MT_ARCHIVE_RECOVERY_LOOP', 'MT_STORAGE_RECOVERY_AUDIT',
    'MT_ARCHIVE_VERIFY_ONCE', 'MT_CONTROL_BACKUP_AUDIT',
    'MT_CONTROL_BACKUP_V2_ONCE', 'MT_CONTROL_BACKUP_V2_ENABLED',
)

# Use only statically authored, bounded aggregate queries. The WAL-directory
# query can be denied by a managed-PostgreSQL role; report its error type only.
QUERIES = (
    ('logical_database', """
        SELECT pg_database_size(current_database())::bigint AS database_bytes
    """),
    ('wal_counters', """
        SELECT wal_records::bigint AS records,
               wal_fpi::bigint AS full_page_images,
               wal_bytes::numeric AS generated_bytes_since_reset,
               stats_reset FROM pg_stat_wal
    """),
    ('wal_directory', """
        SELECT count(*)::bigint AS segment_count,
               coalesce(sum(size),0)::bigint AS directory_bytes
        FROM pg_ls_waldir()
    """),
    ('connections', """
        SELECT count(*)::bigint AS total,
               count(*) FILTER (WHERE state='active')::bigint AS active,
               count(*) FILTER (WHERE state='idle in transaction')::bigint
                   AS idle_in_transaction
        FROM pg_stat_activity WHERE datname=current_database()
    """),
    ('archive_role_presence', """
        SELECT EXISTS (SELECT 1 FROM pg_roles
                       WHERE rolname='pocket_archive_maintenance')
                   AS role_exists,
               EXISTS (SELECT 1 FROM pg_roles
                       WHERE rolname='pocket_archive_maintenance'
                         AND rolcanlogin) AS login_enabled,
               to_regprocedure(
                  'public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)'
               ) IS NOT NULL AS scoped_function_exists
    """),
)


def is_authorized(env, settings):
    if env.get('MT_WAL_PREFLIGHT_ONCE', 'false') != 'true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD') == 'true'
            and settings.role == 'collector'
            and settings.enabled is False
            and settings.acceptance == 'off'
            and settings.operator_action == 'off'):
        raise ValueError('WAL preflight requires an idle held collector')
    if any(env.get(key, 'false') == 'true' for key in INCOMPATIBLE_FLAGS):
        raise ValueError('WAL preflight cannot overlap with another recovery job')
    return True


def audit_once(database_url, *, pool_factory=ConnectionPool, emit=print):
    """One bounded SELECT-only scan; every unavailable statistic stays unknown."""
    report = dict(
        event='mt019_wal_preflight', mode='read_only',
        verified_physical_free_disk=False,
        verified_all_writers_stopped=False,
        authorizes_archive_reclaim=False,
    )
    try:
        with pool_factory(
            database_url, min_size=1, max_size=1, open=True, timeout=6,
            kwargs=dict(row_factory=dict_row, connect_timeout=5,
                        options=CONNECTION_OPTIONS),
        ) as pool:
            for label, sql in QUERIES:
                try:
                    with pool.connection() as connection:
                        with connection.transaction():
                            connection.execute('SET LOCAL statement_timeout=3000')
                            row = connection.execute(sql).fetchone()
                    if not isinstance(row, dict):
                        raise ValueError('Missing aggregate result')
                    report[label] = dict(row)
                except Exception as error:
                    # Exclude exception text; drivers may embed connection data.
                    report[label + '_error_type'] = type(error).__name__
    except Exception as error:
        report['connection_error_type'] = type(error).__name__
    emit(json.dumps(report, default=str, sort_keys=True), flush=True)
    return report

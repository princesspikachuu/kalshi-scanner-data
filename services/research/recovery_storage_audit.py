"""One-shot, SELECT-only emergency size audit while all collection is held.

The connection is forced read-only by PostgreSQL session settings. No market
SDK, R2 client, archive job, table mutation, or trading engine is initialized.
The diagnostic only emits aggregate counts and sizes, never data values.
"""
import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .storage_audit import inspect_storage


EVENT_SAMPLE_SQL = """SELECT COALESCE(progress->>'event','(missing)') AS event_kind,
    count(*)::bigint AS sampled_rows,
    COALESCE(sum(pg_column_size(parameters)+pg_column_size(progress)),0)::bigint
      AS sampled_payload_bytes
    FROM research_job TABLESAMPLE SYSTEM(0.25) REPEATABLE(47)
    WHERE idempotency_key >= 'demo/shadow/event/'
      AND idempotency_key < 'demo/shadow/event/zzzz'
    GROUP BY 1 ORDER BY sampled_payload_bytes DESC LIMIT 24"""

CONNECTION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=3500'


def is_authorized(env, settings):
    if env.get('MT_STORAGE_RECOVERY_AUDIT','false')!='true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD')=='true'
            and settings.role=='collector'
            and settings.enabled is False
            and settings.acceptance=='off'
            and settings.operator_action=='off'):
        raise ValueError('Storage audit requires idle recovery-held collector')
    return True


def audit_once(database_url, *, pool_factory=ConnectionPool, inspect=inspect_storage, emit=print):
    """Run a bounded read-only diagnostic once; suppress secret-bearing errors."""
    report=dict(event='storage_recovery_diagnostic',mode='read_only',
                diagnostic_sample_percent=0.25)
    try:
        with pool_factory(database_url,min_size=1,max_size=1,open=True,timeout=6,
            kwargs=dict(row_factory=dict_row,connect_timeout=5,
                        options=CONNECTION_OPTIONS)) as pool:
            try:
                summary=inspect(pool)
                report.update(database_bytes=summary['database_bytes'],
                    relations=summary['relations'],
                    sampled_job_families=summary['job_families'],
                    family_sample_percent=summary['job_sample_percent'])
            except Exception as exc:
                report['storage_summary_error_type']=type(exc).__name__
            try:
                with pool.connection() as c:
                    c.execute('SET LOCAL statement_timeout=3500')
                    report['sampled_shadow_event_kinds']=c.execute(
                        EVENT_SAMPLE_SQL).fetchall()
            except Exception as exc:
                report['event_sample_error_type']=type(exc).__name__
    except Exception as exc:
        report['connection_error_type']=type(exc).__name__
    emit(json.dumps(report,default=str,sort_keys=True),flush=True)
    return report

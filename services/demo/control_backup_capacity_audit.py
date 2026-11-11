"""One-shot read-only inventory of demo and live control backup scope.

The existing backup uses one OR-heavy query and aborts at 2001 records. This
measures each indexed prefix independently, without returning control values or
any wallet/order contents. All counts >=2001 are explicitly *lower bounds*.
"""
import json
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MAX_PER_SCOPE=2001
CONNECTION_OPTIONS='-c default_transaction_read_only=on -c statement_timeout=4000'

# Match the scopes from services.demo.maintenance.backup. Preserve source
# selection semantics; do not alter financial backup content during an audit.
PREFIX_SCOPES=(
    ('demo_bots','demo/bot/',None),
    ('demo_open_orders','demo/order/',"progress->>'status' NOT IN ('closed','rejected')"),
    ('shadow_folders','demo/shadow/folder/',None),
    ('shadow_bots','demo/shadow/bot/',None),
    ('paper_resting','demo/paper/resting/',"progress->>'status'='resting'"),
    ('paper_positions','demo/paper/position/',"(progress->>'quantity')::numeric<>0"),
    ('paper_open_orders','demo/paper/order/',"""(
        progress->>'status'='resting' OR EXISTS (
        SELECT 1 FROM research_job AS local
        WHERE local.idempotency_key='demo/order/'||(research_job.progress->>'client_id')
        AND local.progress->>'status' NOT IN ('closed','rejected')))"""),
    ('live_bots','live/bot/',None),
    ('live_orders','live/order/',None),
    ('live_writes','live/write/',None),
    ('live_onboarding_ops','live/onboarding-op/',None),
)
SINGLETONS=(
    'demo/shadow/checkpoint','demo/shadow/installed',
    'demo/shadow/strategy-layout','demo/shadow/weather-layout',
    'demo/shadow/sports-layout','demo/shadow/scope-hourly-v1',
    'demo/paper/cash','demo/engine','live/onboarding','demo/policy',
    'demo/account','demo/funding','demo/reset','trading/mode',
    'live/budget','live/trial','live/risk','live/account',
)

def is_authorized(env,settings):
    if env.get('MT_CONTROL_BACKUP_AUDIT','false')!='true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD')=='true'
            and settings.role=='collector' and settings.enabled is False
            and settings.acceptance=='off' and settings.operator_action=='off'
            and env.get('MT_ARCHIVE_RECOVERY_LOOP','false')!='true'
            and env.get('MT_ARCHIVE_VERIFY_ONCE','false')!='true'):
        raise ValueError('Backup inventory must run on a disabled recovery-held collector')
    return True

def prefix_query(predicate):
    if predicate and predicate not in [scope[2] for scope in PREFIX_SCOPES]:
        raise ValueError('Unrecognized backup scope predicate')
    where=' AND '+predicate if predicate else ''
    return ("""SELECT pg_column_size(parameters)::bigint AS parameter_bytes,
       pg_column_size(progress)::bigint AS progress_bytes
       FROM research_job WHERE idempotency_key >= %s AND idempotency_key < %s"""
       +where+""" ORDER BY idempotency_key LIMIT %s""")

SINGLETON_QUERY="""SELECT pg_column_size(parameters)::bigint AS parameter_bytes,
       pg_column_size(progress)::bigint AS progress_bytes
       FROM research_job WHERE idempotency_key=ANY(%s::text[]) LIMIT %s"""

def sample_rows(pool,sql,params):
    with pool.connection() as c:
        rows=c.execute(sql,params).fetchall()
    payload=sum(int(r['parameter_bytes'])+int(r['progress_bytes']) for r in rows)
    return dict(rows_seen=min(len(rows),MAX_PER_SCOPE), truncated=len(rows)>=MAX_PER_SCOPE,
                payload_bytes_lower_bound=payload)

def inspect_control_backup(pool):
    scopes=[];failed=[]
    for name,prefix,predicate in PREFIX_SCOPES:
        try:
            metrics=sample_rows(pool,prefix_query(predicate),
                (prefix,prefix+'zzzz',MAX_PER_SCOPE))
            scopes.append(dict(scope=name,**metrics))
        except Exception as error:
            failed.append(dict(scope=name,error_type=type(error).__name__))
    try:
        scopes.append(dict(scope='singleton_controls',**sample_rows(
            pool,SINGLETON_QUERY,(list(SINGLETONS),MAX_PER_SCOPE))))
    except Exception as error:
        failed.append(dict(scope='singleton_controls',error_type=type(error).__name__))
    complete=not failed and not any(s['truncated'] for s in scopes)
    lower_bound=sum(s['rows_seen'] for s in scopes)
    return dict(event='control_backup_capacity_audit',mode='read_only',
        scope_count=len(scopes),scopes=scopes,failed_scopes=failed,
        total_rows_lower_bound=lower_bound,
        payload_bytes_lower_bound=sum(s['payload_bytes_lower_bound'] for s in scopes),
        candidate_count_exact=complete,
        exceeds_legacy_2000_record_cap=lower_bound>2000,
        legacy_query_would_fail_on_count=lower_bound>2000,
        note='Capped scope counts are lower bounds; SQL row bytes exclude serialization and R2 overhead')

def audit_once(database_url,*,pool_factory=ConnectionPool,emit=print):
    report=dict(event='control_backup_capacity_audit',mode='read_only',
                verified=False)
    try:
        with pool_factory(database_url,min_size=1,max_size=1,open=True,
            timeout=6,kwargs=dict(row_factory=dict_row,connect_timeout=5,
                options=CONNECTION_OPTIONS)) as pool:
            report.update(inspect_control_backup(pool))
            report['verified']=not report['failed_scopes']
    except Exception as error:
        report['error_type']=type(error).__name__
    emit(json.dumps(report,sort_keys=True),flush=True)
    return report

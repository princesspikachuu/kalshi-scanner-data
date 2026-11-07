"""Small, read-only storage diagnostics; no data values or credentials are logged."""
import json

def inspect_storage(pool):
    with pool.connection() as c:
        c.execute('SET LOCAL statement_timeout=3000')
        size=c.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes']
        relations=c.execute("""SELECT relname,pg_total_relation_size(relid) AS total_bytes,
            pg_table_size(relid) AS table_bytes,pg_indexes_size(relid) AS index_bytes,
            n_live_tup,n_dead_tup,last_autovacuum,last_autoanalyze
            FROM pg_stat_user_tables WHERE schemaname='public'
            ORDER BY pg_total_relation_size(relid) DESC LIMIT 12""").fetchall()
    with pool.connection() as c:
        c.execute('SET LOCAL statement_timeout=3000')
        families=c.execute("""SELECT CASE WHEN idempotency_key LIKE 'demo/%%'
            THEN 'demo/'||split_part(idempotency_key,'/',2)
            ELSE split_part(idempotency_key,'/',1) END AS family,
            count(*) AS sampled_rows,sum(pg_column_size(parameters)+pg_column_size(progress)) AS sampled_bytes
            FROM research_job TABLESAMPLE SYSTEM(1) REPEATABLE(31)
            GROUP BY 1 ORDER BY sampled_bytes DESC LIMIT 12""").fetchall()
    return dict(event='database_storage_audit',database_bytes=size,relations=relations,
                job_sample_percent=1,job_families=families)

def log_storage(pool):
    try:print(json.dumps(inspect_storage(pool),default=str),flush=True)
    except Exception:print(json.dumps(dict(event='database_storage_audit_unavailable')),flush=True)

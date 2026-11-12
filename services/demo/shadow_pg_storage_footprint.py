"""MT-019: bounded, read-only PostgreSQL logical-storage footprint.

This is an operator-only diagnostic building block, not a worker task, API,
migration, archive/reclaim operation, or disk-capacity authorization.

PostgreSQL's pg_database_size() and relation sizes are NOT physical free-disk
or pg_wal occupancy. Render's host filesystem metrics must be checked
separately before any write-capable operation is considered.
"""
MAX_RELATIONS = 12

DATABASE_SQL = """SELECT current_database() AS database_name,
    pg_database_size(current_database()) AS database_bytes"""
RELATIONS_SQL = """SELECT c.relname AS relation_name,
    pg_total_relation_size(c.oid) AS total_bytes,
    pg_relation_size(c.oid) AS heap_bytes,
    pg_indexes_size(c.oid) AS index_bytes,
    COALESCE(s.n_live_tup, 0) AS estimated_live_tuples,
    COALESCE(s.n_dead_tup, 0) AS estimated_dead_tuples
    FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid
    WHERE n.nspname='public' AND c.relkind='r'
    ORDER BY pg_total_relation_size(c.oid) DESC, c.relname ASC
    LIMIT %s"""


def _nonnegative_int(value, description):
    if type(value) is not int or value < 0:
        raise ValueError('Invalid PostgreSQL ' + description)
    return value


def inspect_readonly_pg_footprint(pool, *, top_relations=10):
    """Inspect at most 12 public ordinary tables and one database-size value.

    One READ ONLY transaction with short query and lock timeouts, no table
    scans (pg_class/pg_stat metadata), no R2 I/O or user payload reads.
    No historical original count, bloat estimate or free-disk claim is made.
    """
    if type(top_relations) is not int or not 1 <= top_relations <= MAX_RELATIONS:
        raise ValueError('Invalid bounded table inspection limit')

    with pool.connection() as connection:
        with connection.transaction():
            connection.execute(
                'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            connection.execute('SET LOCAL statement_timeout=5000')
            connection.execute('SET LOCAL lock_timeout=1000')
            info = connection.execute(DATABASE_SQL).fetchone()
            if (not isinstance(info, dict)
                    or not isinstance(info.get('database_name'), str)
                    or not info['database_name']):
                raise ValueError('Invalid PostgreSQL database metadata')
            database_bytes = _nonnegative_int(
                info.get('database_bytes'), 'database size')
            rows = connection.execute(
                RELATIONS_SQL, (top_relations,)
            ).fetchall()
            if not isinstance(rows, list) or len(rows) > top_relations:
                raise ValueError('Invalid bounded relation metrics')
            relations = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Invalid relation metadata')
                name = row.get('relation_name')
                if (not isinstance(name, str) or not name or len(name) > 128):
                    raise ValueError('Invalid relation name')
                relations.append(dict(
                    relation_name=name,
                    total_bytes=_nonnegative_int(
                        row.get('total_bytes'), 'total relation size'),
                    heap_bytes=_nonnegative_int(
                        row.get('heap_bytes'), 'heap size'),
                    index_bytes=_nonnegative_int(
                        row.get('index_bytes'), 'index size'),
                    estimated_live_tuples=_nonnegative_int(
                        row.get('estimated_live_tuples'), 'live tuple estimate'),
                    estimated_dead_tuples=_nonnegative_int(
                        row.get('estimated_dead_tuples'), 'dead tuple estimate'),
                ))
            if relations != sorted(
                    relations, key=lambda r: (-r['total_bytes'],
                                              r['relation_name'])):
                raise ValueError('Unordered relation metrics')

    return dict(
        contract='mt019-readonly-pg-logical-footprint-v1',
        database_name=info['database_name'],
        database_bytes=database_bytes,
        top_public_relations=relations,
        relations_reported=len(relations),
        sampling_scope='public_ordinary_table_catalog_statistics',
        transaction_read_only=True,
        statement_timeout_ms=5000,
        lock_timeout_ms=1000,
        # These catalog/stats metrics are not hard disk or WAL free space.
        render_physical_disk_used_bytes=None,
        render_physical_disk_free_bytes=None,
        wal_directory_bytes=None,
        wal_free_headroom_bytes=None,
        actual_physical_disk_headroom_verified=False,
        actual_wal_headroom_verified=False,
        # Tuple stats are estimates, not deletable rows or reclaimable bytes.
        reclaimable_bytes_estimated=False,
        source_exhaustion_verified=False,
        r2_original_readbacks_verified=False,
        all_time_coverage_complete=False,
        authoritative_financial_outcomes_verified=False,
        safe_to_archive_or_delete=False,
        safe_to_restart_writers=False,
        safe_to_train=False,
        real_orders_enabled=False,
    )


def main(argv=None):
    """One explicit operator command, never invoked by services or migrations."""
    import argparse
    import json
    import os
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-readonly',action='store_true',
                        help='Run bounded read-only metadata queries')
    parser.add_argument('--top-relations',type=int,default=10)
    args = parser.parse_args(argv)
    if not args.execute_readonly:
        print('No query run. Pass --execute-readonly on an authorized Render shell.')
        return 0
    url = os.environ.get('RECOVERY_DATABASE_URL')
    if not url:
        print('RECOVERY_DATABASE_URL missing; no query run.',file=sys.stderr)
        return 2
    # Never print the URL, exceptions with connection detail, or raw row data.
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        with ConnectionPool(conninfo=url,min_size=1,max_size=1,
                            timeout=5.0,kwargs={'row_factory':dict_row}) as pool:
            output=inspect_readonly_pg_footprint(
                pool,top_relations=args.top_relations)
        print(json.dumps(output,sort_keys=True))
        return 0
    except Exception as exc:
        print('Read-only storage footprint unavailable: '
              +type(exc).__name__,file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())

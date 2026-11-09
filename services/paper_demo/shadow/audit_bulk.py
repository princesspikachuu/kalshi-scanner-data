"""Lossless SQL batching for newly generated paper audit events.

The checkpoint, commands and every audit event stay in the caller's single
PostgreSQL transaction. Multi-row UPSERTs preserve the existing conflict policy
and never combine or discard event identities or details.
"""

EVENT_PREFIX='demo/shadow/event/'
ROW_SQL="(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())"
INSERT_SQL="INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES "
CONFLICT_SQL=(" ON CONFLICT(idempotency_key) DO UPDATE SET "
              "parameters=excluded.parameters, progress=excluded.progress, "
              "finished_at=clock_timestamp()")


def persist_audit_rows(cursor, rows, upsert_sql, *, min_bulk=8, max_bulk=64):
    """Preserve original row order and let the caller own transaction boundaries.

    Only consecutive audit-event rows can be grouped. Everything else, including
    the hot checkpoint, commands, reports and any future row types, uses the
    original UPSERT. Each multi-row statement is capped at 64 rows (256 binds).
    """
    if not 1<=min_bulk<=max_bulk<=64:
        raise ValueError('Invalid paper audit group size')
    stats=dict(bulk_event_rows=0,bulk_event_groups=0,ordinary_upsert_rows=0)
    pending=[]
    event_run=None

    def flush():
        nonlocal pending
        if not pending:
            return
        if event_run:
            # Each block retains its original relative ordering; a short final
            # block uses the original statement rather than a padded VALUES.
            for offset in range(0,len(pending),max_bulk):
                group=pending[offset:offset+max_bulk]
                # A repeated idempotency key is unexpected for UUID audit
                # events, but sequential UPSERTs historically let the later
                # row win. Preserve that behavior rather than letting one
                # multi-row ON CONFLICT attempt fail on duplicate targets.
                keys=[record[3] for record in group]
                if len(group)>=min_bulk and len(set(keys))==len(keys):
                    placeholders=','.join([ROW_SQL]*len(group))
                    params=tuple(value for record in group for value in record)
                    cursor.execute(INSERT_SQL+placeholders+CONFLICT_SQL,params)
                    stats['bulk_event_rows']+=len(group)
                    stats['bulk_event_groups']+=1
                else:
                    cursor.executemany(upsert_sql,group)
                    stats['ordinary_upsert_rows']+=len(group)
        else:
            cursor.executemany(upsert_sql,pending)
            stats['ordinary_upsert_rows']+=len(pending)
        pending=[]

    for record in rows:
        audit_event=isinstance(record[3],str) and record[3].startswith(EVENT_PREFIX)
        if event_run is not None and audit_event!=event_run:
            flush()
        pending.append(record)
        event_run=audit_event
    flush()
    return stats

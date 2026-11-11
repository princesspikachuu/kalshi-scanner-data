"""Lossless, diagnostic-only legacy Demo archival with a short compare-and-swap.

Do not archive financial/order/settlement/control events. The original R2 v1
progress-only payload remains readable for previously archived entries.
"""
import json
import time

from psycopg.types.json import Jsonb

from services.demo.shadow_archive_recovery import (
    PREFIX, SAFE_EVENT_KINDS, archive_payload,
)

FORMAT = 'demo-shadow-diagnostic-full-row-v2'
PAGE_SIZE = 25
CURSOR_KEY = 'archive-scan-v2'
FIELDS = """id::text,idempotency_key,asset,status,parameters,progress,created_at,
    started_at,finished_at,lease_expires_at,attempts,error_code,available_at,
    max_attempts,lease_token"""
CANDIDATES = f"""SELECT {FIELDS} FROM research_job
    WHERE idempotency_key > %s AND idempotency_key < %s
      AND status='succeeded' AND created_at < to_timestamp(%s)
      AND NOT (progress ? 'archive')
      AND progress->>'event'=ANY(%s::text[])
    ORDER BY idempotency_key LIMIT %s"""
LOCKED_ROWS = f"""SELECT {FIELDS} FROM research_job
    WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE"""
LOCKED_ONE = f"""SELECT {FIELDS} FROM research_job
    WHERE id=%s::uuid FOR UPDATE"""
POINTER_UPDATE = """UPDATE research_job SET progress=%s::jsonb
    WHERE id=%s::uuid AND progress=%s::jsonb AND NOT(progress ? 'archive')
    RETURNING id::text"""
RESTORE_UPDATE = """UPDATE research_job SET progress=%s::jsonb
    WHERE id=%s::uuid AND progress=%s::jsonb RETURNING id::text"""
PENDING_RESTORE_SQL = """SELECT idempotency_key,progress FROM research_job
    WHERE idempotency_key >= 'demo/restore/'
      AND idempotency_key < 'demo/restore/zzzz'
      AND progress->>'done' IS DISTINCT FROM 'true'
    ORDER BY idempotency_key LIMIT %s"""
# Metadata comparison is performed under FOR UPDATE before the pointer
# update; no window exists for another writer to modify the locked row.
FULL_ROW_FIELDS = (
    'id','idempotency_key','asset','status','parameters','created_at',
    'started_at','finished_at','lease_expires_at','attempts','error_code',
    'available_at','max_attempts','lease_token',
)


def verified_records(payload):
    """Support old v1 list and validate the full-row v2 R2 payload."""
    if isinstance(payload, list):
        if not payload or any(
            not isinstance(row,dict)
            or not isinstance(row.get('id'),str)
            or not isinstance(row.get('progress'),dict) for row in payload
        ):
            raise ValueError('Invalid legacy archived events')
        ids=[row['id'] for row in payload]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate legacy archive identities')
        return payload,False
    if not isinstance(payload,dict) or payload.get('format')!=FORMAT:
        raise ValueError('Unrecognized archived event format')
    if payload.get('source_prefix')!=PREFIX:
        raise ValueError('Archive provenance does not match diagnostics')
    rows=payload.get('records')
    ids=payload.get('ids')
    if (not isinstance(rows,list) or not 1<=len(rows)<=PAGE_SIZE
            or type(payload.get('count')) is not int
            or len(rows)!=payload['count'] or not isinstance(ids,list)
            or len(ids)!=len(rows) or any(not isinstance(x,str) for x in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('Invalid full-row archive manifest')
    for row,ident in zip(rows,ids):
        if (not isinstance(row,dict) or row.get('id')!=ident
                or any(k not in row for k in (*FULL_ROW_FIELDS,'progress'))
                or not isinstance(row.get('progress'),dict)
                or not isinstance(row.get('parameters'),dict)
                or not str(row.get('idempotency_key','')).startswith(PREFIX)
                or row.get('status')!='succeeded' or row.get('asset')!='crypto'
                or row['progress'].get('event') not in SAFE_EVENT_KINDS):
            raise ValueError('Invalid full-row diagnostic evidence')
    return rows,True


def archive_events_v2(store,objects,policy,pressure):
    """Archive only old allowlisted diagnostics, never losing a concurrent edit.

    The read transaction ends before R2 I/O. R2 is fully verified before a
    short SQL transaction locks and compares *all* original research_job fields.
    Source rows are never deleted; an unchanged progress becomes an R2 pointer.
    """
    from services.demo.maintenance import put_verified

    state=store.get(CURSOR_KEY)
    cursor=(state or {}).get('progress',{}).get('after',PREFIX)
    if not isinstance(cursor,str) or not cursor.startswith(PREFIX):
        cursor=PREFIX
    now=time.time()
    cutoff=now-(7 if pressure else policy['archive_days'])*86400
    with store.pool.connection() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            conn.execute('SET LOCAL statement_timeout=5000')
            page=conn.execute(CANDIDATES,(cursor,PREFIX+'zzzz',cutoff,
                                         list(SAFE_EVENT_KINDS),PAGE_SIZE)).fetchall()
    rows=[]
    for r in page:
        progress=r['progress']
        try:
            restored_at=float(progress.get('restored_at') or 0)
        except (TypeError,ValueError):
            raise ValueError('Invalid original restoration timestamp') from None
        if restored_at<now-86400:
            rows.append(r)
    if rows:
        originals=archive_payload(rows)
        ids=[r['id'] for r in originals]
        verified_records(dict(format=FORMAT,count=len(ids),ids=ids,
                              source_prefix=PREFIX,records=originals))
        payload=dict(format=FORMAT,count=len(ids),ids=ids,
                     source_prefix=PREFIX,records=originals,created_at=now)
        receipt=put_verified(objects,'events',payload)
        expected={r['id']:r for r in originals}
        with store.pool.connection() as conn:
            with conn.transaction():
                conn.execute('SET LOCAL statement_timeout=10000')
                locked=conn.execute(LOCKED_ROWS,(ids,)).fetchall()
                if len(locked)!=len(ids) or set(r['id'] for r in locked)!=set(ids):
                    raise RuntimeError('Archive candidates disappeared; source retained')
                if any(archive_payload([r])[0]!=expected[r['id']]
                       for r in locked):
                    raise RuntimeError('Archive source changed; source retained')
                for row in originals:
                    pointer=dict(archive=receipt,archived=True,
                                 archive_format=FORMAT)
                    changed=conn.execute(POINTER_UPDATE,(
                        Jsonb(pointer),row['id'],Jsonb(row['progress']))).fetchone()
                    if not changed or changed['id']!=row['id']:
                        raise RuntimeError('Archive pointer conflict; transaction rolled back')
        store.put('archive-health',dict(at=time.time(),last_count=len(rows),
                                        verified=True,format=FORMAT))
    after=page[-1]['idempotency_key'] if len(page)==PAGE_SIZE else PREFIX
    store.put(CURSOR_KEY,dict(after=after,format=FORMAT))
    print(json.dumps(dict(event='demo_archive_scan_v2',scanned=len(page),
                          archived=len(rows),diagnostics_only=True,
                          full_row=True,bounded=True)),flush=True)


def restore_requests_v2(store,objects):
    """Restore old v1 and new v2 references using a locked pointer CAS."""
    from services.demo.maintenance import read_verified

    with store.pool.connection() as c:
        requests=c.execute(PENDING_RESTORE_SQL,(5,)).fetchall()
    for request in requests:
        ident=request['progress']['event_id']
        with store.pool.connection() as conn:
            row=conn.execute('SELECT progress FROM research_job WHERE id=%s::uuid',
                             (ident,)).fetchone()
        ref=(row or {}).get('progress',{}).get('archive')
        if not isinstance(ref,dict):
            raise ValueError('Archive reference absent; refusing unverified restore')
        payload=read_verified(objects,ref)
        records,full_row=verified_records(payload)
        record=next((r for r in records if r['id']==ident),None)
        if not record:
            raise ValueError('Archive member not found')
        with store.pool.connection() as conn:
            with conn.transaction():
                conn.execute('SET LOCAL statement_timeout=10000')
                locked=conn.execute(LOCKED_ONE,(ident,)).fetchone()
                if not locked or locked['progress'].get('archive')!=ref:
                    raise RuntimeError('Archive pointer changed; restore aborted')
                if full_row:
                    snapshot=archive_payload([locked])[0]
                    if any(snapshot.get(k)!=record.get(k) for k in FULL_ROW_FIELDS):
                        raise RuntimeError('Archive metadata changed; restore aborted')
                updated=dict(record['progress'],restored_at=time.time())
                changed=conn.execute(RESTORE_UPDATE,(
                    Jsonb(updated),ident,Jsonb(locked['progress']))).fetchone()
                if not changed or changed['id']!=ident:
                    raise RuntimeError('Archive restore changed; transaction rolled back')
        store.put(request['idempotency_key'][5:],
                  dict(request['progress'],done=True))

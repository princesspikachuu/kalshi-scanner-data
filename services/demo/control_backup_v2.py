"""Lossless, bounded, multi-object control backup for paper and live pilot state.

No history is deleted. A consistent read-only database snapshot is collected
using the existing idempotency-key index; R2 chunks and a root receipt are
independently read back before backup-health is advanced.
"""
import hashlib
import json
import os
import time
import tempfile
import shutil

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.demo.control_backup_capacity_audit import PREFIX_SCOPES, SINGLETONS
from services.demo.maintenance import object_store, put_verified, read_verified
from services.demo.store import DemoStore

PAGE_SIZE=200
MAX_ROWS=50000
MAX_CAPTURE_BYTES=64*1024*1024
MAX_SINGLE_ROW_BYTES=12*1024*1024
MAX_CHUNK_BYTES=2*1024*1024
MAX_CHUNK_ROWS=200
MAX_STAGED_ROWS=100000
MAX_STAGED_BYTES=512*1024*1024
MIN_FREE_DISK_RESERVE=256*1024*1024
FORMAT='control-snapshot-multipart-v2'
PART_FORMAT='control-snapshot-part-v2'
SELECT_FIELDS='id::text,idempotency_key,parameters,progress'
SINGLETON_QUERY=f"""SELECT {SELECT_FIELDS} FROM research_job
    WHERE idempotency_key=ANY(%s::text[]) ORDER BY idempotency_key"""
SELECT_PREFIX=f"""SELECT {SELECT_FIELDS} FROM research_job
    WHERE idempotency_key>=%s AND idempotency_key<%s
    AND (%s::text IS NULL OR idempotency_key>%s)"""


def canonical(row):
    return json.dumps(row,sort_keys=True,separators=(',',':'),
                      ensure_ascii=False,allow_nan=False).encode('utf-8')


def select_prefix_query(predicate):
    if predicate is not None and predicate not in [scope[2] for scope in PREFIX_SCOPES]:
        raise ValueError('Unrecognized control backup predicate')
    suffix=' AND '+predicate if predicate else ''
    return SELECT_PREFIX+suffix+' ORDER BY idempotency_key LIMIT %s'


def collect_snapshot(pool):
    """Capture the *whole* eligible set from one REPEATABLE READ transaction.

    Refuse to publish any partial backup if size/row/resource caps are exceeded.
    This transaction is closed before R2 upload, avoiding prolonged MVCC pins.
    """
    records=[];seen=set();captured_bytes=0
    def append(row):
        nonlocal captured_bytes
        if not isinstance(row,dict):
            raise ValueError('Invalid control record')
        key=row.get('idempotency_key')
        if not isinstance(key,str) or key in seen:
            raise ValueError('Invalid or duplicate control record')
        if not isinstance(row.get('parameters'),dict) or not isinstance(row.get('progress'),dict):
            raise ValueError('Incomplete control backup record')
        raw=canonical(row)
        if len(raw)>MAX_SINGLE_ROW_BYTES:
            raise ValueError('Single control record exceeds safe archive size')
        captured_bytes+=len(raw)+1
        if len(records)>=MAX_ROWS or captured_bytes>MAX_CAPTURE_BYTES:
            raise ValueError('Control backup snapshot capacity exceeded')
        seen.add(key);records.append(row)

    with pool.connection() as connection:
        with connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            connection.execute('SET LOCAL statement_timeout=5000')
            for _,prefix,predicate in PREFIX_SCOPES:
                cursor=None
                query=select_prefix_query(predicate)
                while True:
                    page=connection.execute(query,(
                        prefix,prefix+'zzzz',cursor,cursor,PAGE_SIZE)).fetchall()
                    if not page:break
                    for record in page:append(record)
                    cursor=page[-1]['idempotency_key']
                    if len(page)<PAGE_SIZE:break
            singletons=connection.execute(SINGLETON_QUERY,(list(SINGLETONS),)).fetchall()
            for record in singletons:append(record)
    return records


def collect_snapshot_spooled(pool):
    """Stage a whole consistent snapshot into one unlinked local temporary file.

    Only one <=2MiB chunk is held in Python memory. PostgreSQL's repeatable
    read transaction ends before any network upload. The spool is always closed
    by the caller, and on any source/cap failure it is closed immediately.
    """
    # The local staging file is unlinked, but still consumes physical space.
    # Reserve headroom for the running worker and PostgreSQL-free application
    # operations; do not assume the configured 512 MiB spool cap is available.
    available=shutil.disk_usage(tempfile.gettempdir()).free
    if available<=MIN_FREE_DISK_RESERVE:
        raise ValueError('Insufficient temporary disk headroom for control backup')
    disk_budget=min(MAX_STAGED_BYTES,available-MIN_FREE_DISK_RESERVE)
    file=tempfile.TemporaryFile(mode='w+b')
    seen=set();current=[];chunk_bytes=0;total_bytes=0;count=0;parts=0
    aggregate=hashlib.sha256()

    def flush():
        nonlocal current,chunk_bytes,parts
        if not current:return
        blob=canonical(dict(format=PART_FORMAT,count=len(current),records=current))
        if len(blob)>16*1024*1024:
            raise ValueError('Oversized staged backup part')
        if file.tell()+len(blob)+4>disk_budget or (shutil.disk_usage(tempfile.gettempdir()).free
                <MIN_FREE_DISK_RESERVE+len(blob)+4):
            raise ValueError('Insufficient temporary disk headroom for control backup')
        file.write(len(blob).to_bytes(4,'big'));file.write(blob)
        current=[];chunk_bytes=0;parts+=1

    def add(row):
        nonlocal total_bytes,count,chunk_bytes
        if not isinstance(row,dict):
            raise ValueError('Invalid control record')
        key=row.get('idempotency_key')
        if (not isinstance(key,str) or key in seen
                or not isinstance(row.get('id'),str)
                or not isinstance(row.get('parameters'),dict)
                or not isinstance(row.get('progress'),dict)):
            raise ValueError('Invalid or duplicate control record')
        raw=canonical(row);size=len(raw)+1
        if size>MAX_SINGLE_ROW_BYTES:
            raise ValueError('Single control record exceeds safe archive size')
        if count>=MAX_STAGED_ROWS or total_bytes+size>disk_budget:
            raise ValueError('Spool size budget exceeded; no partial backup published')
        if current and (len(current)>=MAX_CHUNK_ROWS or chunk_bytes+size>MAX_CHUNK_BYTES):
            flush()
        current.append(row);chunk_bytes+=size;count+=1;total_bytes+=size
        aggregate.update(raw);aggregate.update(b'\n')
        seen.add(key)

    try:
        with pool.connection() as connection:
            with connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                connection.execute('SET LOCAL statement_timeout=5000')
                for _,prefix,predicate in PREFIX_SCOPES:
                    cursor=None;query=select_prefix_query(predicate)
                    while True:
                        page=connection.execute(query,(
                            prefix,prefix+'zzzz',cursor,cursor,PAGE_SIZE)).fetchall()
                        if not page:break
                        for record in page:add(record)
                        cursor=page[-1]['idempotency_key']
                        if len(page)<PAGE_SIZE:break
                for record in connection.execute(
                        SINGLETON_QUERY,(list(SINGLETONS),)).fetchall():
                    add(record)
        if count==0:
            raise ValueError('No controls found; refusing empty recovery backup')
        flush();file.seek(0)
        return dict(file=file,records=count,parts=parts,sha256=aggregate.hexdigest(),
                    staged_bytes=total_bytes)
    except Exception:
        file.close()
        raise


def verify_staged_archive(objects,reference,*,max_records=MAX_STAGED_ROWS):
    """Full R2 read-back with bounded working memory, no bulk records list."""
    root=read_verified(objects,reference)
    if (not isinstance(root,dict) or root.get('format')!=FORMAT
            or type(root.get('records')) is not int
            or not 1<=root['records']<=max_records
            or not isinstance(root.get('chunks'),list)
            or not 1<=len(root['chunks'])<=max_records):
        raise ValueError('Invalid control backup root')
    seen=set();count=0;digest=hashlib.sha256()
    for section in root['chunks']:
        if not isinstance(section,dict) or not isinstance(section.get('reference'),dict):
            raise ValueError('Invalid control backup chunk reference')
        part=read_verified(objects,section['reference'])
        if (not isinstance(part,dict) or part.get('format')!=PART_FORMAT
                or type(part.get('count')) is not int
                or not isinstance(part.get('records'),list)
                or not 1<=part['count']<=MAX_CHUNK_ROWS
                or part['count']!=len(part['records'])
                or part['count']!=section.get('count')):
            raise ValueError('Invalid control backup chunk')
        for row in part['records']:
            key=row.get('idempotency_key') if isinstance(row,dict) else None
            if (not isinstance(key,str) or key in seen
                    or not isinstance(row.get('id'),str)
                    or not isinstance(row.get('parameters'),dict)
                    or not isinstance(row.get('progress'),dict)):
                raise ValueError('Duplicate or incomplete control record')
            canonical_row=canonical(row)
            digest.update(canonical_row);digest.update(b'\n')
            seen.add(key);count+=1
            if count>max_records:raise ValueError('Control backup exceeds row cap')
    if count!=root['records'] or digest.hexdigest()!=root.get('sha256'):
        raise ValueError('Control backup root digest or count mismatch')
    return dict(records=count,sha256=digest.hexdigest(),chunks=len(root['chunks']))


def split_snapshot(records):
    """Chunk serializable rows so no R2 object approaches restore size limits."""
    parts=[];current=[];current_bytes=0
    for row in records:
        size=len(canonical(row))+1
        if size>MAX_SINGLE_ROW_BYTES:
            raise ValueError('Oversize control backup row')
        if current and (len(current)>=MAX_CHUNK_ROWS or current_bytes+size>MAX_CHUNK_BYTES):
            parts.append(current);current=[];current_bytes=0
        current.append(row);current_bytes+=size
    if current:parts.append(current)
    return parts


def digest_records(records):
    h=hashlib.sha256()
    for record in records:
        h.update(canonical(record));h.update(b'\n')
    return h.hexdigest()


def restore_verified_snapshot(objects, reference, *, max_records=MAX_STAGED_ROWS):
    root=read_verified(objects,reference)
    if (not isinstance(root,dict) or root.get('format')!=FORMAT
            or type(root.get('records')) is not int
            or not 0<=root['records']<=max_records
            or not isinstance(root.get('chunks'),list)
            or len(root['chunks'])>MAX_STAGED_ROWS):
        raise ValueError('Invalid complete control backup manifest')
    records=[];seen=set()
    for section in root['chunks']:
        if not isinstance(section,dict) or not isinstance(section.get('reference'),dict):
            raise ValueError('Invalid multipart control reference')
        obj=read_verified(objects,section['reference'])
        if (not isinstance(obj,dict) or obj.get('format')!=PART_FORMAT
                or not isinstance(obj.get('records'),list)
                or type(obj.get('count')) is not int
                or obj['count']!=len(obj['records'])
                or not 1<=obj['count']<=MAX_CHUNK_ROWS):
            raise ValueError('Invalid control snapshot part')
        if section.get('count')!=obj['count']:
            raise ValueError('Control backup chunk count mismatch')
        for row in obj['records']:
            key=row.get('idempotency_key') if isinstance(row,dict) else None
            if (not isinstance(key,str) or key in seen
                    or not isinstance(row.get('parameters'),dict)
                    or not isinstance(row.get('progress'),dict)):
                raise ValueError('Duplicate or incomplete control backup record')
            records.append(row);seen.add(key)
            if len(records)>max_records:raise ValueError('Control backup row limit exceeded')
    if len(records)!=root['records'] or digest_records(records)!=root.get('sha256'):
        raise ValueError('Control backup aggregate integrity mismatch')
    return records


def backup_controls(store,objects,*,now=None):
    now=time.time() if now is None else now
    staging=collect_snapshot_spooled(store.pool)
    try:
        chunks=[];total_compressed=0
        for _ in range(staging['parts']):
            length_bytes=staging['file'].read(4)
            if len(length_bytes)!=4:
                raise ValueError('Incomplete local control backup spool')
            size=int.from_bytes(length_bytes,'big')
            if not 1<=size<=16*1024*1024:
                raise ValueError('Invalid local control backup spool length')
            blob=staging['file'].read(size)
            if len(blob)!=size:
                raise ValueError('Truncated local control backup spool')
            part=json.loads(blob)
            receipt=put_verified(objects,'backups',part)
            chunks.append(dict(reference=receipt,count=part['count']))
            total_compressed+=receipt['size']
        if staging['file'].read(1):
            raise ValueError('Unexpected local control backup spool trailer')
        root=dict(format=FORMAT,records=staging['records'],
                  sha256=staging['sha256'],created_at=now,chunks=chunks,
                  scope='Demo and live controls and open orders; credentials excluded')
        root_ref=put_verified(objects,'backups',root)
        verified=verify_staged_archive(objects,root_ref)
        if (verified['records']!=staging['records']
                or verified['sha256']!=staging['sha256']
                or verified['chunks']!=len(chunks)):
            raise ValueError('R2 backup restore verification mismatch')
        store.put('backup-health',dict(at=now,verified=True,reference=root_ref,
            records=staging['records'],format=FORMAT,chunks=len(chunks),
            scope='Demo and live controls, current positions and full live pilot write history; credentials excluded'))
        result=dict(event='demo_control_backup_v2_verified',
            records=staging['records'],chunks=len(chunks),
            staged_bytes=staging['staged_bytes'],
            compressed_bytes=total_compressed+root_ref['size'],verified=True)
        print(json.dumps(result,sort_keys=True),flush=True)
        return result
    finally:
        staging['file'].close()


def is_authorized(env,settings):
    if env.get('MT_CONTROL_BACKUP_V2_ONCE','false')!='true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD')=='true'
            and settings.role=='collector' and settings.enabled is False
            and settings.acceptance=='off' and settings.operator_action=='off'
            and env.get('MT_ARCHIVE_RECOVERY_LOOP','false')!='true'
            and env.get('MT_CONTROL_BACKUP_AUDIT','false')!='true'
            and env.get('MT_ARCHIVE_VERIFY_ONCE','false')!='true'):
        raise ValueError('Control backup V2 requires a disabled recovery-held collector')
    return True


def backup_once(database_url,env=None,*,pool_factory=ConnectionPool,
                store_factory=DemoStore,object_factory=object_store,emit=print):
    env=os.environ if env is None else env
    objects=None
    report=dict(event='demo_control_backup_v2_once',verified=False)
    try:
        with pool_factory(database_url,min_size=1,max_size=1,open=True,timeout=6,
            kwargs=dict(row_factory=dict_row,connect_timeout=5)) as pool:
            objects=object_factory(env)
            store=store_factory(pool)
            result=backup_controls(store,objects)
            report.update(result)
    except Exception as error:
        report['error_type']=type(error).__name__
        report['verified']=False
    finally:
        if objects is not None:objects.client.close()
    emit(json.dumps(report,sort_keys=True),flush=True)
    return report

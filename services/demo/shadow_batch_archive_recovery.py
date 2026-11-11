"""Operator-only, lossless R2 offload for compressed shadow diagnostic rows.

This complements shadow_archive_recovery.py (which handles older uncompressed
rows). It is not scheduled by the paper worker. Execution requires a separate
recovery-role connection and explicit proof that paper writers are stopped.
"""
import argparse
import json
import os
import sys
import time
from datetime import timezone
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from services.demo.maintenance import object_store, put_verified, read_verified
from services.paper_demo.shadow.diagnostic_batches import (
    BATCH_PREFIX, DIAGNOSTIC_EVENTS, decode_diagnostic_batch
)

MANIFEST_PREFIX='demo/shadow/archive-manifest/batch/'
FORMAT='shadow-diagnostic-r2-manifest-v1'
MAX_BATCH=8
MIN_AGE_HOURS=6

CANDIDATES="""SELECT id::text,idempotency_key,asset,status,parameters,progress,
    created_at,started_at,finished_at,lease_expires_at,attempts,error_code,
    available_at,max_attempts,lease_token
    FROM research_job WHERE status='succeeded'
    AND created_at<to_timestamp(%s)
    AND idempotency_key>=%s AND idempotency_key<%s
    AND progress->>'format'='shadow-diagnostic-batch-v1'
    ORDER BY idempotency_key LIMIT %s"""
LOCKED_CANDIDATES=CANDIDATES+' FOR UPDATE SKIP LOCKED'
SCOPED_RECLAIM_SQL='SELECT id FROM public.mt_reclaim_shadow_diagnostics(%s::uuid,%s::jsonb)'
MANIFEST_SQL="""INSERT INTO research_job
    (id,asset,parameters,progress,idempotency_key,status,finished_at)
    VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())"""
DELETE_SQL="""DELETE FROM research_job WHERE id=ANY(%s::uuid[])
    AND status='succeeded' AND created_at<to_timestamp(%s)
    AND idempotency_key>=%s AND idempotency_key<%s
    AND progress->>'format'='shadow-diagnostic-batch-v1'
    RETURNING id::text"""

def cutoff_at(now,age_hours,batch_size):
    if type(age_hours) is not int or age_hours<MIN_AGE_HOURS:
        raise ValueError('A six-hour minimum hot-history window is required')
    if type(batch_size) is not int or not 1<=batch_size<=MAX_BATCH:
        raise ValueError('Invalid bounded batch count')
    return now-age_hours*3600

def original_row(row):
    """Retain every original research_job column, including NULL timestamps."""
    timestamps=('created_at','started_at','finished_at','lease_expires_at','available_at')
    return dict(id=row['id'],idempotency_key=row['idempotency_key'],
        asset=row['asset'],status=row['status'],parameters=row['parameters'],
        progress=row['progress'],attempts=row['attempts'],error_code=row['error_code'],
        max_attempts=row['max_attempts'],lease_token=str(row['lease_token']) if row['lease_token'] is not None else None,
        **{k:row[k].isoformat() if row[k] is not None else None for k in timestamps})

def validated_records(rows):
    records=[];event_ids=[]
    for row in rows:
        if row['asset']!='crypto' or row['status']!='succeeded':
            raise ValueError('Invalid shadow archive source row')
        if not row['idempotency_key'].startswith(BATCH_PREFIX):
            raise ValueError('Unrelated shadow archive source')
        original=decode_diagnostic_batch(row['progress'])
        records.append(original_row(row))
        event_ids.extend(item['id'] for item in original)
    if len(event_ids)!=len(set(event_ids)):
        raise ValueError('Duplicate evidence identities across packed rows')
    return records,event_ids

def verify_batch_manifest(objects,manifest):
    """Restore/validate every source row and original diagnostic event UUID."""
    if not isinstance(manifest,dict) or manifest.get('format')!=FORMAT:
        raise ValueError('Invalid batch archive manifest')
    if manifest.get('source_prefix')!=BATCH_PREFIX or not isinstance(manifest.get('reference'),dict):
        raise ValueError('Invalid archive provenance')
    if type(manifest.get('count')) is not int or not 1<=manifest['count']<=MAX_BATCH:
        raise ValueError('Invalid batch archive count')
    records=read_verified(objects,manifest['reference'])
    if not isinstance(records,list) or len(records)!=manifest['count']:
        raise ValueError('R2 batch archive count mismatch')
    restored_ids=[];events=[]
    for row in records:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str):
            raise ValueError('Invalid archived row ID')
        if not str(row.get('idempotency_key','')).startswith(BATCH_PREFIX):
            raise ValueError('Unrelated archived row')
        if row.get('status')!='succeeded' or row.get('asset')!='crypto':
            raise ValueError('Invalid archived row status')
        for field in ('parameters','progress','created_at','started_at',
                      'finished_at','lease_expires_at','attempts','error_code'):
            if field not in row:raise ValueError('Incomplete archived row')
        if not isinstance(row['parameters'],dict):
            raise ValueError('Invalid archived parameters')
        unpacked=decode_diagnostic_batch(row['progress'])
        events.extend(item['id'] for item in unpacked)
        restored_ids.append(row['id'])
    if len(restored_ids)!=len(set(restored_ids)):
        raise ValueError('Duplicate archived batch IDs')
    if restored_ids!=manifest.get('row_ids') or events!=manifest.get('event_ids'):
        raise ValueError('R2 archive event identity mismatch')
    if len(events)!=len(set(events)) or len(events)!=manifest.get('original_events'):
        raise ValueError('R2 original event count mismatch')
    return records

def preview(pool,*,now,age_hours=24,batch_size=1):
    cutoff=cutoff_at(now,age_hours,batch_size)
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET LOCAL statement_timeout=5000')
            rows=c.execute(CANDIDATES,(cutoff,BATCH_PREFIX,BATCH_PREFIX+'zzzz',batch_size)).fetchall()
    records,event_ids=validated_records(rows)
    return dict(mode='preview',batch_rows=len(records),original_events=len(event_ids),
        eligible_sample_only=True,hot_hours=age_hours,no_writes=True)

def archive_one(pool,objects,*,now,age_hours=24,batch_size=1):
    """Commit manifest + exact DELETE only after verified R2 readback.

    A failed R2 upload or manifest validation leaves the original PG rows.
    The operator must budget WAL and physical disk headroom before execution.
    """
    cutoff=cutoff_at(now,age_hours,batch_size)
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET LOCAL statement_timeout=10000')
            rows=c.execute(LOCKED_CANDIDATES,(cutoff,BATCH_PREFIX,BATCH_PREFIX+'zzzz',batch_size)).fetchall()
            if not rows:
                return dict(mode='executed',archived_rows=0,original_events=0,deleted_rows=0)
            records,event_ids=validated_records(rows)
            receipt=put_verified(objects,'events',records)
            manifest=dict(format=FORMAT,source_prefix=BATCH_PREFIX,reference=receipt,
                count=len(rows),row_ids=[r['id'] for r in rows],
                event_ids=event_ids,original_events=len(event_ids),
                earliest=min(r['created_at'] for r in rows).astimezone(timezone.utc).isoformat(),
                latest=max(r['created_at'] for r in rows).astimezone(timezone.utc).isoformat(),
                created_at=now,restorable=True)
            # Integrity-check the actual durable object, not just the in-memory
            # source record, before committing any deletion.
            restored=verify_batch_manifest(objects,manifest)
            if restored!=records:raise ValueError('Archived batch rows did not round-trip exactly')
            c.execute(MANIFEST_SQL,(uuid4(),Jsonb(dict(kind='diagnostic_batch_r2_manifest')),
                Jsonb(manifest),MANIFEST_PREFIX+str(uuid4())))
            deleted=c.execute(DELETE_SQL,(manifest['row_ids'],cutoff,BATCH_PREFIX,BATCH_PREFIX+'zzzz')).fetchall()
            if len(deleted)!=len(rows) or {r['id'] for r in deleted}!=set(manifest['row_ids']):
                raise RuntimeError('Incomplete batch reclaim; transaction rolled back')
    return dict(mode='executed',archived_rows=len(rows),original_events=len(event_ids),
        deleted_rows=len(rows),verified=True,compressed_bytes=receipt['size'])

def main(argv=None):
    parser=argparse.ArgumentParser(description='Operator-only R2 recovery of compressed paper diagnostics')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--writers-stopped',action='store_true')
    parser.add_argument('--age-hours',type=int,default=24)
    parser.add_argument('--batch-size',type=int,default=1)
    parser.add_argument('--max-batches',type=int,default=1)
    opts=parser.parse_args(argv)
    if not 1<=opts.max_batches<=1000:parser.error('max-batches must be 1..1000')
    cutoff_at(time.time(),opts.age_hours,opts.batch_size)
    if opts.execute and not opts.writers_stopped:
        parser.error('--execute requires --writers-stopped')
    url=os.environ.get('RECOVERY_DATABASE_URL')
    if not isinstance(url,str) or not url.startswith(('postgres://','postgresql://')):
        parser.error('Separate RECOVERY_DATABASE_URL required')
    objects=None
    try:
        with ConnectionPool(url,min_size=1,max_size=1,open=True,timeout=6,
                            kwargs=dict(row_factory=dict_row,connect_timeout=5)) as pool:
            if opts.execute:objects=object_store(os.environ)
            for _ in range(opts.max_batches):
                now=time.time()
                result=(archive_one(pool,objects,now=now,age_hours=opts.age_hours,batch_size=opts.batch_size)
                        if opts.execute else preview(pool,now=now,age_hours=opts.age_hours,batch_size=opts.batch_size))
                print(json.dumps(result,sort_keys=True),flush=True)
                if not opts.execute or not result.get('archived_rows'):break
    except Exception as error:
        # Do not log exception bodies: DB/SDK errors can expose secrets.
        print(json.dumps(dict(event='batch_archive_recovery_failed',
            error_type=type(error).__name__,recovery_incomplete=True)),file=sys.stderr,flush=True)
        return 1
    finally:
        if objects is not None:objects.client.close()
    return 0

if __name__=='__main__':raise SystemExit(main())

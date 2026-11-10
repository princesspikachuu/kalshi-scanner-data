"""Operator-only lossless R2 offload and reclaim of aged shadow audit rows.

This module is deliberately NOT imported or scheduled by a trading worker.
It never touches orders, wallets, checkpoints, settlement ledgers, research
datasets, or other research_job namespaces.

Use only with the paper-trading writers stopped and a separately authorized
recovery connection that can DELETE research_job rows. The default is preview.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import timezone
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from services.demo.maintenance import object_store, put_verified

PREFIX = 'demo/shadow/event/'
MANIFEST_PREFIX = 'demo/shadow/archive-manifest/'
MAX_BATCH = 150
MIN_AGE_HOURS = 6

# research_job_queue(status, created_at) already supports a bounded age scan.
# Do not ORDER BY an unindexed JSON field, scan entire payload histories, or
# target the 'demo/event/' namespace (legacy finance queries depend on it).
CANDIDATES = """SELECT id::text,idempotency_key,parameters,progress,created_at
    FROM research_job WHERE status='succeeded'
    AND created_at<to_timestamp(%s)
    AND NOT (progress ? 'archive')
    AND idempotency_key>=%s AND idempotency_key<%s
    ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED"""

MANIFEST_SQL = """INSERT INTO research_job
    (id,asset,parameters,progress,idempotency_key,status,finished_at)
    VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())"""

DELETE_SQL = """DELETE FROM research_job WHERE id=ANY(%s::uuid[])
    AND status='succeeded'
    AND idempotency_key>=%s AND idempotency_key<%s
    AND created_at<to_timestamp(%s)
    AND NOT (progress ? 'archive') RETURNING id::text"""


def validate_window(now, age_hours, batch_size):
    if type(age_hours) is not int or age_hours < MIN_AGE_HOURS:
        raise ValueError('At least six hours of hot shadow history is required')
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH:
        raise ValueError('Invalid bounded archive batch size')
    return now - age_hours * 3600


def archive_payload(rows):
    """Every original field is retained in the checksum-verified R2 object."""
    return [dict(id=r['id'], idempotency_key=r['idempotency_key'],
                 parameters=r['parameters'], progress=r['progress'],
                 created_at=r['created_at'].isoformat()) for r in rows]


def plan_only(pool, *, now, age_hours=24, batch_size=100):
    cutoff = validate_window(now, age_hours, batch_size)
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET LOCAL statement_timeout=5000')
            rows = c.execute(CANDIDATES, (cutoff, PREFIX, PREFIX+'zzzz', batch_size)).fetchall()
    kinds = Counter(str(r['progress'].get('event','unknown')) for r in rows)
    return dict(mode='preview', eligible_in_sample=len(rows),
                batch_limit=batch_size, hot_hours=age_hours,
                event_types=dict(kinds.most_common(16)),
                note='One bounded candidate page; not a count of all old history')


def archive_and_reclaim_one(pool, objects, *, now, age_hours=24, batch_size=100):
    """Verified upload, immutable manifest and exact-row DELETE in one DB transaction.

    Failure to upload, verify, persist the manifest, or delete ALL selected
    IDs aborts the database transaction. R2 objects uploaded before a later
    database failure are safe, content-addressed orphans (never data loss).
    """
    cutoff=validate_window(now,age_hours,batch_size)
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET LOCAL statement_timeout=10000')
            rows=c.execute(CANDIDATES,(cutoff,PREFIX,PREFIX+'zzzz',batch_size)).fetchall()
            if not rows:
                return dict(mode='executed', archived=0, deleted=0, hot_hours=age_hours)
            records=archive_payload(rows)
            # put_verified performs a full read-after-write SHA-256 and JSON
            # round-trip check before returning its receipt.
            receipt=put_verified(objects,'events',records)
            ids=[r['id'] for r in rows]
            first=min(r['created_at'] for r in rows).astimezone(timezone.utc).isoformat()
            last=max(r['created_at'] for r in rows).astimezone(timezone.utc).isoformat()
            manifest=dict(format='shadow-r2-event-batch-v1',reference=receipt,
                count=len(ids),earliest=first,latest=last,
                source_prefix=PREFIX,created_at=now,restorable=True)
            c.execute(MANIFEST_SQL,(uuid4(),Jsonb(dict(kind='shadow_event_r2_manifest')),
                Jsonb(manifest),MANIFEST_PREFIX+str(uuid4())))
            deleted=c.execute(DELETE_SQL,(ids,PREFIX,PREFIX+'zzzz',cutoff)).fetchall()
            if {r['id'] for r in deleted}!=set(ids) or len(deleted)!=len(ids):
                raise RuntimeError('Archive/delete identity mismatch; transaction rolled back')
    return dict(mode='executed',archived=len(rows),deleted=len(rows),
                compressed_bytes=receipt['size'],hot_hours=age_hours,
                verified=True,manifest_stored=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Operator-only R2 archive and reclaim of aged shadow events')
    parser.add_argument('--execute',action='store_true',help='Actually archive and delete after verified read-back')
    parser.add_argument('--writers-stopped',action='store_true',help='Explicit confirmation all paper writers are stopped')
    parser.add_argument('--age-hours',type=int,default=24)
    parser.add_argument('--batch-size',type=int,default=100)
    parser.add_argument('--max-batches',type=int,default=1)
    args=parser.parse_args(argv)
    if not 1<=args.max_batches<=1000:parser.error('max-batches must be 1..1000')
    validate_window(time.time(),args.age_hours,args.batch_size)
    if args.execute and not args.writers_stopped:
        parser.error('--execute requires --writers-stopped')
    # Intentionally separate from the normal app DATABASE_URL; no routine
    # worker or API principal receives expanded DELETE privileges.
    url=os.environ.get('RECOVERY_DATABASE_URL')
    if not url or not url.startswith(('postgres://','postgresql://')):
        parser.error('RECOVERY_DATABASE_URL must be configured privately')
    objects=None
    try:
        with ConnectionPool(url,min_size=1,max_size=1,open=True,timeout=6,
                            kwargs=dict(row_factory=dict_row,connect_timeout=5)) as pool:
            if args.execute:objects=object_store(os.environ)
            for _ in range(args.max_batches):
                now=time.time()
                result=(archive_and_reclaim_one(pool,objects,now=now,age_hours=args.age_hours,batch_size=args.batch_size)
                        if args.execute else plan_only(pool,now=now,age_hours=args.age_hours,batch_size=args.batch_size))
                print(json.dumps(result,sort_keys=True),flush=True)
                if not args.execute or not result.get('archived'):break
    except Exception as error:
        # Database/SDK error strings can include credentials; report only the
        # failure class and never claim a partially failed batch succeeded.
        print(json.dumps(dict(event='shadow_archive_recovery_failed',
            error_type=type(error).__name__,recovery_incomplete=True)),
            file=sys.stderr,flush=True)
        return 1
    finally:
        if objects is not None:objects.client.close()
    return 0


if __name__=='__main__':raise SystemExit(main())

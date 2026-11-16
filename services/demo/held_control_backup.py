"""Explicit backup-only supervision while paper trading and collection stay held."""
import json
import math
import os
import re
import sys
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.demo.control_backup_v2 import FORMAT, MAX_STAGED_ROWS, backup_controls
from services.demo.maintenance import MAX_OBJECT, object_store
from services.demo.store import DemoStore
from services.demo.shadow_archive_automatic import park_until_stopped

BACKUP_LEASE_KEY = 723741934
INTERVAL_SECONDS = 60
BACKUP_HOURS = 24


def valid_reference(value,prefix):
    if not isinstance(value,dict):return False
    digest=value.get('sha256');size=value.get('size')
    return (isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest) is not None
            and value.get('key')==prefix+digest+'.json.gz'
            and type(size) is int and 0<size<=MAX_OBJECT)


def validate_environment(env):
    required = dict(MT_CONTROL_BACKUP_HELD_WORKER='true',
                    MT_CONTROL_BACKUP_V2_ENABLED='true',
                    MT_STORAGE_RECOVERY_HOLD='true', COLLECTION_ENABLED='false',
                    WORKER_ROLE='collector', RUNTIME_DB_PROFILE='research',
                    STAGING_ACCEPTANCE='off', STAGING_OPERATOR_ACTION='off')
    if any(env.get(key) != value for key,value in required.items()):
        raise ValueError('Backup-only mode requires the explicitly held collector')
    from services.research.recovery_one_shot_guard import check_recovery_jobs_exclusive
    check_recovery_jobs_exclusive(env)
    url=env.get('DATABASE_URL','')
    if not url.startswith(('postgres://','postgresql://')):
        raise ValueError('Private application database connection required')
    return url


def backup_due(health, now):
    """Only a verified, discoverable multipart snapshot can defer a backup."""
    if not isinstance(health,dict):return True
    at=health.get('at')
    if (type(at) not in (int,float) or not math.isfinite(at) or at>now
            or health.get('verified') is not True or health.get('format')!=FORMAT
            or type(health.get('records')) is not int or not 0<health['records']<=MAX_STAGED_ROWS
            or type(health.get('chunks')) is not int or not 0<health['chunks']<=health['records']
            or not valid_reference(health.get('reference'),'demo/backups/')
            or not valid_reference(health.get('catalog_reference'),'demo/backups/roots/')):
        return True
    return now-at>=BACKUP_HOURS*3600


def cycle(store, objects, now, safety_check):
    safety_check()
    row=store.get('backup-health')
    due=backup_due(row.get('progress') if row else None,now)
    if due:
        safety_check()
        result=backup_controls(store,objects,now=now)
        if result.get('verified') is not True:
            raise ValueError('Control backup did not verify')
    return dict(event='held_control_backup_checked',backup_due=due,
                backup_performed=due,backup_hours=BACKUP_HOURS,
                interval_seconds=INTERVAL_SECONDS,collection_enabled=False,
                trading_enabled=False)


def run_held_worker(stop,env=None):
    env=os.environ if env is None else env
    objects=None
    try:
        url=validate_environment(env)
        with ConnectionPool(url,min_size=1,max_size=1,timeout=6,
                            kwargs=dict(row_factory=dict_row,connect_timeout=5)) as pool:
            with pool.connection() as c:
                if c.execute('SELECT current_user AS principal').fetchone()['principal']!='pocket_research_runtime':
                    raise ValueError('Backup worker requires its existing non-owner runtime role')
            with psycopg.connect(url,autocommit=True,row_factory=dict_row,connect_timeout=5,
                                 options='-c statement_timeout=5000 -c lock_timeout=1000') as lease:
                while not stop.is_set():
                    if lease.execute('SELECT pg_try_advisory_lock(%s) AS acquired',
                                     (BACKUP_LEASE_KEY,)).fetchone()['acquired']:
                        break
                    print(json.dumps(dict(event='held_control_backup_standby',
                                          reason='previous_instance_holds_lease')),flush=True)
                    stop.wait(5)
                if stop.is_set():return
                objects=object_store(env)
                store=DemoStore(pool)
                def safety_check():
                    if validate_environment(env)!=url:
                        raise ValueError('Backup configuration changed')
                    if stop.is_set():raise RuntimeError('Backup worker stopping')
                    lease.execute('SELECT 1 AS lease_alive').fetchone()
                while not stop.is_set():
                    report=cycle(store,objects,time.time(),safety_check)
                    print(json.dumps(report,sort_keys=True),flush=True)
                    stop.wait(INTERVAL_SECONDS)
    except Exception as error:
        print(json.dumps(dict(event='held_control_backup_stopped',
                              error_type=type(error).__name__,
                              action='operator_review_required')),file=sys.stderr,flush=True)
    finally:
        if objects is not None:
            try:objects.client.close()
            except Exception as error:
                print(json.dumps(dict(event='held_control_backup_close_failed',
                                      error_type=type(error).__name__)),file=sys.stderr,flush=True)
    park_until_stopped(stop)

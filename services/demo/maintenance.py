"""Bounded verified archiving and control backups. Historical evidence stays intact."""
import gzip,hashlib,json,os,smtplib,time
from datetime import datetime,timezone
from email.message import EmailMessage
from tempfile import TemporaryFile
from uuid import uuid4
from psycopg.types.json import Jsonb
from services.api.demo_models import Policy

MAX_OBJECT=4*1024*1024

def failure_details(error,stage):
    # SDK/SQL exception text may contain credentials or connection strings.
    # Publish only fixed classifications and bounded protocol status fields.
    known={'Backup chunk capacity reached':'backup_capacity',
           'Archive chunk too large':'object_capacity',
           'Archive verification failed':'checksum_mismatch',
           'Archive restore validation failed':'roundtrip_mismatch',
           'Restored object too large':'restore_capacity'}
    result=dict(stage=stage,error_type=type(error).__name__,
                reason_code=known.get(str(error),'operation_failed') if type(error) is ValueError else 'operation_failed')
    response=getattr(error,'response',{})
    status=response.get('ResponseMetadata',{}).get('HTTPStatusCode') if isinstance(response,dict) else None
    if isinstance(status,int) and 100<=status<=599:result['http_status']=status
    code=response.get('Error',{}).get('Code') if isinstance(response,dict) else None
    if code in ('AccessDenied','NoSuchBucket','InvalidAccessKeyId','SignatureDoesNotMatch',
                'PreconditionFailed','RequestTimeout','InternalError'):result['provider_code']=code
    state=getattr(error,'sqlstate',None)
    if isinstance(state,str) and len(state)==5 and state.isalnum():result['sqlstate']=state
    return result

def storage_measurement(size,policy,env,now,previous=None):
    # Render capacity is supplied as non-secret deployment configuration after
    # checking the provisioned database. The UI's editable value is a fallback.
    configured=policy['storage_limit_gb'];capacity=configured;source='configured'
    value=env.get('DATABASE_CAPACITY_GB')
    if value is not None:
        try:
            supplied=int(value)
            if str(supplied)!=str(value) or not 1<=supplied<=16000:raise ValueError()
            capacity=supplied;source='deployment'
        except (TypeError,ValueError):source='configured_invalid_deployment'
    result=dict(at=now,database_bytes=size,provisioned_gb=capacity,configured_limit_gb=configured,
        capacity_source=source,measurement='logical_database',percent=100*size/(capacity*1024**3))
    if previous and 60<=now-previous.get('at',now)<=7200:
        result.update(change_bytes=size-previous['database_bytes'],change_seconds=now-previous['at'])
    return result

def object_store(env):
    from services.research.r2 import R2Objects
    return R2Objects.connect(account_id=env['R2_ACCOUNT_ID'],bucket=env['R2_BUCKET'],access_key_id=env['R2_ACCESS_KEY_ID'],secret_access_key=env['R2_SECRET_ACCESS_KEY'])

def put_verified(objects,kind,payload):
    body=gzip.compress(json.dumps(payload,separators=(',',':'),default=str).encode(),mtime=0)
    if len(body)>MAX_OBJECT:raise ValueError('Archive chunk too large')
    digest=hashlib.sha256(body).hexdigest();key=f'demo/{kind}/{digest}.json.gz'
    try:objects.client.put_object(Bucket=objects.bucket,Key=key,Body=body,ContentType='application/gzip',IfNoneMatch='*')
    except Exception as error:
        if getattr(error,'response',{}).get('ResponseMetadata',{}).get('HTTPStatusCode')!=412:raise
    loaded=read_verified(objects,dict(key=key,sha256=digest,size=len(body)))
    if loaded!=json.loads(json.dumps(payload,default=str)):raise ValueError('Archive restore validation failed')
    return dict(key=key,sha256=digest,size=len(body),at=time.time())

def read_verified(objects,reference):
    key=reference['key']
    if not key.startswith(('demo/events/','demo/backups/')) or not key.endswith('.json.gz'):raise ValueError('Invalid archive reference')
    result=objects.client.get_object(Bucket=objects.bucket,Key=key);stream=result['Body']
    try:
        if result['ContentLength']>MAX_OBJECT:raise ValueError('Archive object too large')
        body=stream.read(MAX_OBJECT+1)
        if len(body)!=reference['size'] or hashlib.sha256(body).hexdigest()!=reference['sha256']:raise ValueError('Archive verification failed')
        with gzip.GzipFile(fileobj=__import__('io').BytesIO(body)) as source:
            unpacked=source.read(16*1024*1024+1)
            if len(unpacked)>16*1024*1024:raise ValueError('Restored object too large')
        return json.loads(unpacked)
    finally:stream.close()

def archive_events(store,objects,policy,pressure):
    # P0 #196: only lossless allowlisted diagnostics; short locked CAS
    # protects rows against modification during R2 upload.
    from services.demo.legacy_event_archive import archive_events_v2
    return archive_events_v2(store,objects,policy,pressure)


def restore_requests(store,objects):
    # Preserve v1 progress-only restore compatibility while validating v2
    # full-row metadata and refusing concurrent pointer changes.
    from services.demo.legacy_event_archive import restore_requests_v2
    return restore_requests_v2(store,objects)

def backup(store,objects):
    # Back up mutable controls/open positions, not duplicate immutable historical
    # datasets already in R2. Never export credentials into audit archives.
    with store.pool.connection() as c:
        rows=c.execute("""SELECT id::text,idempotency_key,parameters,progress FROM research_job
            WHERE (idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz')
            OR (idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND progress->>'status' NOT IN ('closed','rejected'))
            OR idempotency_key IN ('demo/shadow/checkpoint','demo/shadow/installed','demo/shadow/strategy-layout','demo/shadow/weather-layout','demo/shadow/sports-layout','demo/shadow/scope-hourly-v1')
            OR (idempotency_key>='demo/shadow/folder/' AND idempotency_key<'demo/shadow/folder/zzzz')
            OR (idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz')
            OR idempotency_key='demo/paper/cash'
            OR (idempotency_key>='demo/paper/resting/' AND idempotency_key<'demo/paper/resting/zzzz' AND progress->>'status'='resting')
            OR (idempotency_key>='demo/paper/position/' AND idempotency_key<'demo/paper/position/zzzz' AND (progress->>'quantity')::numeric<>0)
            OR (idempotency_key>='demo/paper/order/' AND idempotency_key<'demo/paper/order/zzzz' AND (progress->>'status'='resting' OR EXISTS(SELECT 1 FROM research_job AS local WHERE local.idempotency_key='demo/order/'||(research_job.progress->>'client_id') AND local.progress->>'status' NOT IN ('closed','rejected'))))
            OR (idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz')
            OR (idempotency_key>='live/order/' AND idempotency_key<'live/order/zzzz')
            OR (idempotency_key>='live/write/' AND idempotency_key<'live/write/zzzz')
            OR (idempotency_key>='live/onboarding-op/' AND idempotency_key<'live/onboarding-op/zzzz')
            OR idempotency_key IN ('demo/engine','live/onboarding','demo/policy','demo/account','demo/funding','demo/reset','trading/mode','live/budget','live/trial','live/risk','live/account') LIMIT 2001""").fetchall()
    if len(rows)>2000:raise ValueError('Backup chunk capacity reached')
    reference=put_verified(objects,'backups',dict(version=1,created_at=time.time(),records=rows))
    # Reading and parsing the written object is a bounded restore validation.
    # put_verified already read, parsed and compared every record.
    store.put('backup-health',dict(at=time.time(),verified=True,reference=reference,records=len(rows),scope='Demo controls and open orders, LIVE pilot controls and complete execution ledger; credentials excluded'))
    print(json.dumps(dict(event='demo_control_backup_verified',records=len(rows),compressed_bytes=reference['size'])),flush=True)

def emails(store,env,enabled):
    pending=[r for r in store.rows('alert/',30) if r['progress'].get('active') and r['progress'].get('critical') and not r['progress'].get('email_sent')]
    if not pending or not enabled:return
    required=('ALERT_SMTP_HOST','ALERT_EMAIL_TO','ALERT_EMAIL_FROM')
    if not all(env.get(k) for k in required):
        store.put('email-health',dict(ready=False,message='Critical email delivery needs an email connection; in-app alerts remain available'))
        return
    message=EmailMessage();message['Subject']='Money Tree: critical Demo trading alert';message['From']=env['ALERT_EMAIL_FROM'];message['To']=env['ALERT_EMAIL_TO']
    message.set_content('\n\n'.join(r['progress']['message'] for r in pending))
    with smtplib.SMTP_SSL(env['ALERT_SMTP_HOST'],int(env.get('ALERT_SMTP_PORT','465')),timeout=10) as smtp:
        if env.get('ALERT_SMTP_USER'):smtp.login(env['ALERT_SMTP_USER'],env['ALERT_SMTP_PASSWORD'])
        smtp.send_message(message)
    for row in pending:store.put(row['idempotency_key'][5:],dict(row['progress'],email_sent=True))
    store.put('email-health',dict(ready=True,at=time.time()))

def maintenance(store,env,stop):
    row=store.get('policy');policy=Policy(**row['progress']).model_dump() if row else Policy().model_dump()
    with store.pool.connection() as c:
        size=c.execute('SELECT pg_database_size(current_database()) AS size').fetchone()['size']
    previous=store.get('storage-health')
    measurement=storage_measurement(size,policy,env,time.time(),previous['progress'] if previous else None)
    used=measurement['percent'];store.put('storage-health',measurement)
    print(json.dumps(dict(event='database_storage_health',**measurement)),flush=True)
    # Catalog statistics, not scans of historical event bodies. Sample on the
    # existing five-minute maintenance cadence and never log SQL text or users.
    try:
        with store.pool.connection() as c:
            tables=c.execute("""SELECT relname,n_live_tup,n_dead_tup,seq_scan,idx_scan,
                pg_total_relation_size(relid) AS bytes FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC LIMIT 10""").fetchall()
            database=c.execute("""SELECT numbackends,xact_commit,xact_rollback,blks_read,blks_hit,
                temp_bytes,deadlocks FROM pg_stat_database WHERE datname=current_database()""").fetchone()
        print(json.dumps(dict(event='database_operational_sample',tables=tables,database=database),default=str),flush=True)
    except Exception as error:
        print(json.dumps(dict(event='database_operational_sample_unavailable',error_type=type(error).__name__)),flush=True)
    if used>=policy['storage_warning_percent']:store.alert('storage',f'Database data uses {used:.1f}% of {measurement["provisioned_gb"]} GB capacity. Review storage and archiving thresholds.',used>=policy['storage_critical_percent'])
    else:store.clear_alert('storage')
    objects=None;failed=False
    def failure(error,stage):
        nonlocal failed
        failed=True
        print(json.dumps(dict(event='demo_backup_verification_failed',original_records_retained=True,
                              **failure_details(error,stage))),flush=True)
    try:
        objects=object_store(env)
    except Exception as error:failure(error,'object_store')
    if objects:
        def due_backup():
            last=store.get('backup-health')
            if not last or time.time()-last['progress'].get('at',0)>policy['backup_hours']*3600:
                if env.get('MT_CONTROL_BACKUP_V2_ENABLED','false')=='true':
                    # Opt-in only after a verified paused-worker trial.
                    # Source records are preserved and never deleted here.
                    from services.demo.control_backup_v2 import backup_controls
                    backup_controls(store,objects)
                else:
                    backup(store,objects)
        try:
            for stage,operation in (
                    ('archive',lambda:archive_events(store,objects,policy,used>=policy['storage_warning_percent'])
                     if (policy['archive_enabled'] and
                         env.get('MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED','false')=='true')
                     else None),
                    ('restore',lambda:restore_requests(store,objects)),('backup',due_backup)):
                try:operation()
                except Exception as error:failure(error,stage)
        finally:objects.client.close()
    if failed:store.alert('backup','Demo backup or archive verification failed. Original records are retained.',True)
    else:store.clear_alert('backup')
    try:emails(store,env,policy['critical_email'])
    except Exception:store.put('email-health',dict(ready=False,message='Critical email delivery failed; review the in-app alerts'))

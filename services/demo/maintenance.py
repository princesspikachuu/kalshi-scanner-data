"""Bounded verified archiving and control backups. Historical evidence stays intact."""
import gzip,hashlib,json,os,smtplib,time
from datetime import datetime,timezone
from email.message import EmailMessage
from tempfile import TemporaryFile
from uuid import uuid4
from psycopg.types.json import Jsonb
from services.api.demo_models import Policy

MAX_OBJECT=4*1024*1024

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
    with store.pool.connection() as c:
        rows=c.execute("""SELECT id::text,parameters,progress FROM research_job
            WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
            AND NOT(progress ? 'archive') AND coalesce((progress->>'restored_at')::numeric,0)<extract(epoch from clock_timestamp())-86400 AND created_at<clock_timestamp()-%s*interval '1 day'
            ORDER BY created_at LIMIT 50""",(7 if pressure else policy['archive_days'],)).fetchall()
    if not rows:return
    reference=put_verified(objects,'events',rows)
    # Verify bytes before replacing event detail with a searchable pointer.
    with store.pool.connection() as c:
        for row in rows:
            c.execute("UPDATE research_job SET progress=%s WHERE id=%s AND NOT(progress ? 'archive')",
                (Jsonb(dict(archive=reference,archived=True)),row['id']))
    store.put('archive-health',dict(at=time.time(),last_count=len(rows),verified=True))

def restore_requests(store,objects):
    for request in store.rows('restore/',5):
        if request['progress'].get('done'):continue
        identifier=request['progress']['event_id']
        with store.pool.connection() as c:
            row=c.execute('SELECT progress FROM research_job WHERE id=%s',(identifier,)).fetchone()
        reference=row['progress'].get('archive') if row else None
        if reference:
            records=read_verified(objects,reference)
            record=next((r for r in records if r['id']==identifier),None)
            if not record:raise ValueError('Archive member not found')
            with store.pool.connection() as c:c.execute('UPDATE research_job SET progress=%s WHERE id=%s',(Jsonb(dict(record['progress'],restored_at=time.time())),identifier))
        store.put(request['idempotency_key'][5:],dict(request['progress'],done=True))

def backup(store,objects):
    # Back up mutable controls/open positions, not duplicate immutable historical
    # datasets already in R2. Never export credentials into audit archives.
    with store.pool.connection() as c:
        rows=c.execute("""SELECT id::text,idempotency_key,parameters,progress FROM research_job
            WHERE (idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz')
            OR (idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND progress->>'status' NOT IN ('closed','rejected'))
            OR idempotency_key IN ('demo/policy','demo/account') LIMIT 701""").fetchall()
    if len(rows)>700:raise ValueError('Backup chunk capacity reached')
    reference=put_verified(objects,'backups',dict(version=1,created_at=time.time(),records=rows))
    # Reading and parsing the written object is a bounded restore validation.
    restored=read_verified(objects,reference)
    if len(restored['records'])!=len(rows):raise ValueError('Backup restore verification failed')
    store.put('backup-health',dict(at=time.time(),verified=True,reference=reference,records=len(rows),scope='Demo controls and open orders; historical R2 evidence remains intact'))

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
    used=100*size/(policy['storage_limit_gb']*1024**3)
    store.put('storage-health',dict(at=time.time(),database_bytes=size,provisioned_gb=policy['storage_limit_gb'],percent=used))
    if used>=policy['storage_warning_percent']:store.alert('storage',f'Database uses {used:.1f}% of configured capacity. Review storage and archiving thresholds.',used>=policy['storage_critical_percent'])
    else:store.clear_alert('storage')
    objects=None
    try:
        objects=object_store(env)
        if policy['archive_enabled']:archive_events(store,objects,policy,used>=policy['storage_warning_percent'])
        restore_requests(store,objects)
        last=store.get('backup-health')
        if not last or time.time()-last['progress'].get('at',0)>policy['backup_hours']*3600:backup(store,objects)
        store.clear_alert('backup')
    except Exception:store.alert('backup','Demo backup or archive verification failed. Original records are retained.',True)
    finally:
        if objects:objects.client.close()
    try:emails(store,env,policy['critical_email'])
    except Exception:store.put('email-health',dict(ready=False,message='Critical email delivery failed; review the in-app alerts'))

"""Owner-only Demo controls; browsers read durable snapshots, never poll Kalshi."""
import os,time
from uuid import UUID,uuid4
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .demo_models import BotConfig,Controls,Policy,PERIOD_HOURS
from services.demo.store import DemoStore

class BotChanges(BotConfig):
    expected_settings_revision:int|None=Field(default=None,ge=1)

def install_demo(app,auth,mutate,pool):
    store=DemoStore(pool)
    from .demo_versions import VersionCatalog,version_clause
    versions=VersionCatalog(pool);app.state.demo_versions=versions
    def require_query(request,allowed=()):
        if any(k not in allowed or len(request.query_params.getlist(k))!=1 for k in request.query_params):raise HTTPException(422,'Invalid filters')
    def bot_get(identifier):
        row=store.get('bot/'+str(identifier))
        if not row:raise HTTPException(404,'Bot not found')
        return row
    def verify_config(config):
        config=config.model_dump();verified=[]
        config['column_maximum_cents']={} # Legacy configs remain readable; column limits are retired.
        square_caps=any(s.get('maximum_cents') is not None for s in config['squares'])
        square_exits=any(s.get('loss_prevention_cents') is not None for s in config['squares'])
        if square_caps or square_exits or config['strategy']=='buy_low_sell_high':
            health=store.get('health')
            features=health['progress'].get('features',[]) if health else []
            if config['strategy']=='buy_low_sell_high' and 'buy_low_sell_high_v1' not in features:raise HTTPException(409,'Buy low, sell high is being updated. Your draft is saved; try saving again shortly.')
            if square_caps and 'square_bid_caps_v1' not in features:raise HTTPException(409,'Square bid limits are temporarily unavailable; your draft has been kept')
            if square_exits and 'square_loss_prevention_v1' not in features:raise HTTPException(409,'Square loss prevention is temporarily unavailable; your draft has been kept')
        with pool.connection() as c:
            identifiers=sorted({s['report_id'] for s in config['squares'] if s['report_id']})
            reports={r['id']:r for r in c.execute("SELECT id,asset,report#>'{historical,cells}' AS cells FROM research_result WHERE id=ANY(%s)",(identifiers,)).fetchall()} if identifiers else {}
            for square in config['squares']:
                square['expected_roi']=None;square['loss_cents']=None
                if not square['report_id']:
                    if config['loss_mode']=='research' and square.get('loss_prevention_cents') is None:raise HTTPException(422,'Select saved research or enter this square’s loss prevention')
                    continue
                row=reports.get(square['report_id'])
                if not row or row['asset']!=square['asset']:raise HTTPException(422,'Research source not found')
                band=f"{square['min_price']:02d}-{square['max_price']+1:02d}"
                cell=next((x for x in row['cells'] if x['hold']['minutes_before_close']==square['max_minutes'] and x['hold']['price_band_cents']==band),None)
                from services.research.reports import MINUTES
                lower=max((m for m in MINUTES[square['asset']] if m<square['max_minutes']),default=0)
                if not cell or not cell['hold']['sampled_markets'] or square['min_minutes']!=lower:raise HTTPException(422,'Choose an available research square')
                square['expected_roi']=cell['hold']['hypothetical_roi_percent']
                loss=cell.get('loss_prevention') or cell.get('conditional_loss') or {}
                square['loss_cents']=loss.get('sell_threshold_cents') or loss.get('threshold_cents')
                if config['loss_mode']=='research' and not square['loss_cents'] and square.get('loss_prevention_cents') is None:raise HTTPException(422,'This square has no verified exit recommendation; enter its loss prevention or choose manual or off')
        return config
    from services.demo.reset import ResetRequest,request_reset,ResetConflict,UndoResetRequest,undo_reset
    @app.post('/demo/reset')
    def reset_demo(body:ResetRequest,request:Request):
        mutate(request);require_query(request)
        try:result=request_reset(store,body)
        except ResetConflict as error:raise HTTPException(409,str(error)) from None
        return dict(contract='demo-v1',request_id=result['request_id'],state=result['state'])
    @app.post('/demo/reset/undo')
    def undo_demo(body:UndoResetRequest,request:Request):
        mutate(request);require_query(request)
        try:result=undo_reset(store,body.request_id)
        except ResetConflict as error:raise HTTPException(409,str(error)) from None
        return dict(contract='demo-v1',request_id=result['request_id'],state=result['state'],
            restored=result['restored'],resumed=result['resumed'])
    @app.get('/demo/workspace')
    def workspace(request:Request):
        auth(request);require_query(request,('period','version'))
        analysis_version=request.query_params.get('version','full')
        try:scope,scope_args=version_clause(analysis_version,versions.load())
        except ValueError:raise HTTPException(422,'Invalid analysis version') from None
        period=request.query_params.get('period','24H')
        if period not in PERIOD_HOURS:raise HTTPException(422,'Invalid period')
        bots=[]
        for row in store.rows('bot/',101):
            data=row['parameters'];state=row['progress']
            bots.append(dict(id=row['id'],key=row['idempotency_key'].split('/')[-1],config=data['config'],revision=data['revision'],settings_revision=data.get('settings_revision',data['revision']),fresh_test=bool(data.get('reset_source')),analysis_version_info=versions.load().get(row['idempotency_key'].split('/')[-1]),**state))
        health=store.get('health');account=store.get('account');policy=store.get('policy')
        alerts=[dict(key=r['idempotency_key'].split('/')[-1],**r['progress']) for r in store.rows('alert/',30) if r['progress'].get('active')]
        reset=store.get('reset')
        status=health['progress'] if health else dict(state='waiting',message='Trading worker has not checked in yet')
        if time.time()-status.get('at',0)>90:status=dict(status,state='waiting',message='Trading worker heartbeat is stale; entries require verified recovery')
        values=account['progress'] if account else None
        with pool.connection() as c:
            health_rows=c.execute("SELECT idempotency_key,progress FROM research_job WHERE idempotency_key=ANY(%s)",(['demo/storage-health','demo/backup-health','demo/email-health','demo/compaction-health'],)).fetchall()
        hours=PERIOD_HOURS[period]
        with pool.connection() as c:
            first=c.execute("SELECT progress FROM research_job WHERE idempotency_key>='demo/equity/' AND idempotency_key<'demo/equity/zzzz' AND created_at>clock_timestamp()-%s*interval '1 hour' ORDER BY created_at LIMIT 1",(hours,)).fetchone()
            performance=c.execute("SELECT parameters->>'bot' AS bot,coalesce(sum((progress->>'realized_cents')::numeric),0) AS pnl,count(*) AS closed FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND progress ? 'realized_cents' AND (progress->>'closed_at')::numeric>%s AND "+scope+" GROUP BY parameters->>'bot'",[time.time()-hours*3600,*scope_args]).fetchall()
        from .demo_performance import summary_metrics
        with pool.connection() as c:card_metrics=summary_metrics(c,scope,scope_args)
        metrics={r['bot']:dict(realized_cents=int(r['pnl']),closed=r['closed']) for r in performance}
        for b in bots:
            if b.get('fresh_test') or analysis_version=='latest' and b.get('analysis_version_info'):metrics.setdefault(b['key'],dict(realized_cents=0,closed=0))
        account_change=values['equity_cents']-first['progress']['value'] if values and first else None
        monitoring={r['idempotency_key'].split('/')[-1].split('-')[0]:r['progress'] for r in health_rows}
        return dict(contract='demo-v1',environment='demo',reset_mode='archive_copy',reset=({**reset['progress'],'request_id':reset['parameters']['request_id']} if reset else None),bots=bots[:100],capacity_reached=len(bots)>100,
            health=status,account=values,alerts=alerts,policy=policy['progress'] if policy else Policy().model_dump(),
            connection_configured=bool(store.get('credentials') or os.environ.get('KALSHI_DEMO_API_KEY_ID')),
            vault_ready=bool(os.environ.get('DEMO_VAULT_KEY')),monitoring=monitoring,metrics=metrics,summary_metrics=card_metrics,account_change_cents=account_change,period=period,analysis_version=analysis_version)
    @app.post('/demo/bots')
    def create(body:BotConfig,request:Request):
        mutate(request);require_query(request)
        config=verify_config(body);identifier=str(uuid4())
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741930)')
            count=c.execute("SELECT count(*) AS n FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'").fetchone()['n']
            if count>=100:raise HTTPException(409,'Bot capacity reached')
            from psycopg.types.json import Jsonb
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                (identifier,Jsonb(dict(config=config,revision=1)),Jsonb(dict(desired='paused',state='paused',message='Ready to review and resume')),'demo/bot/'+identifier))
        store.event('bot_created',config['name']+' saved with '+str(len(config['squares']))+' conditions',bot=identifier)
        return dict(contract='demo-v1',id=identifier)
    @app.post('/demo/bots/{identifier}/configure')
    def configure(identifier:UUID,body:BotChanges,request:Request):
        mutate(request);require_query(request);config=verify_config(body);config.pop('expected_settings_revision',None)
        with pool.connection() as c:
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Bot not found')
            parameters=row['parameters'];settings_revision=parameters.get('settings_revision',parameters['revision'])
            if body.expected_settings_revision is not None and body.expected_settings_revision!=settings_revision:raise HTTPException(409,'Bot settings changed elsewhere. Your draft is saved; reopen Manage to review the latest settings.')
            old=BotConfig.model_validate(parameters['config']).model_dump()
            changed={k for k in config if config[k]!=old[k]}
            if not changed:return dict(contract='demo-v1',updated=True)
            same_rules=[{k:v for k,v in s.items() if k not in ('maximum_cents','loss_prevention_cents')} for s in config['squares']]==[{k:v for k,v in s.items() if k not in ('maximum_cents','loss_prevention_cents')} for s in old['squares']]
            live_settings=changed<={'name','bid_percent','market_percent','bot_percent','squares','column_maximum_cents'} and same_rules
            if not live_settings:
                health=store.get('health')
                if not health or 'editable_rules_v1' not in health['progress'].get('features',[]):raise HTTPException(409,'Bot rule editing is being updated. Your draft is saved; try saving again shortly.')
                from services.demo.engine import protective_threshold
                prior=dict(parameters.get('prior_protection',{}))
                prior[str(parameters['revision'])]=[protective_threshold(old,square) for square in old['squares']]
                parameters=dict(parameters,prior_protection=prior)
            from psycopg.types.json import Jsonb
            parameters=dict(parameters,config=config,revision=parameters['revision']+(0 if live_settings else 1),settings_revision=settings_revision+1)
            c.execute('UPDATE research_job SET parameters=%s WHERE idempotency_key=%s',(Jsonb(parameters),'demo/bot/'+str(identifier)))
        store.event('bot_updated',config['name']+' configuration updated',bot=str(identifier),details=dict(
            rule_revision_changed=not live_settings,revision=parameters['revision'],settings_revision=parameters['settings_revision'],changed_fields=sorted(changed),
            old_cycle_buy_cents=old.get('cycle_buy_cents'),old_cycle_sell_cents=old.get('cycle_sell_cents'),
            cycle_buy_cents=config.get('cycle_buy_cents'),cycle_sell_cents=config.get('cycle_sell_cents')))
        versions.invalidate()
        return dict(contract='demo-v1',updated=True)
    @app.post('/demo/bots/{identifier}/control')
    def control(identifier:UUID,body:Controls,request:Request):
        mutate(request);require_query(request)
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741930)')
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Bot not found')
            if row['parameters']['revision']!=body.revision:raise HTTPException(409,'Bot changed; refresh before retrying')
            state=row['progress'];state['desired']='running' if body.action=='resume' else 'paused'
            state['archived']=body.action=='archive' if body.action in ('archive','restore') else state.get('archived',False)
            if body.action=='resume':state['archived']=False
            state['message']='Waiting for verified reconciliation' if body.action=='resume' else 'Entry cancellation requested; filled positions remain protected'
            from psycopg.types.json import Jsonb
            c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),'demo/bot/'+str(identifier)))
        store.event('bot_'+body.action,body.action.title()+' requested',bot=str(identifier))
        return dict(contract='demo-v1',accepted=True)
    class BulkItem(BaseModel):
        id:UUID
        revision:int=Field(ge=1)
    class BulkControl(BaseModel):
        model_config=ConfigDict(extra='forbid')
        action:str
        bots:list[BulkItem]=Field(min_length=1,max_length=100)
    @app.post('/demo/bulk')
    def bulk(body:BulkControl,request:Request):
        mutate(request);require_query(request)
        if body.action not in ('pause','resume') or len({b.id for b in body.bots})!=len(body.bots):raise HTTPException(422,'Invalid bulk control')
        keys=['demo/bot/'+str(b.id) for b in body.bots];expected={str(b.id):b.revision for b in body.bots}
        from psycopg.types.json import Jsonb
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741930)')
            rows=c.execute('SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key=ANY(%s) FOR UPDATE',(keys,)).fetchall()
            if len(rows)!=len(keys) or any(r['parameters']['revision']!=expected[r['idempotency_key'].split('/')[-1]] for r in rows):raise HTTPException(409,'Bots changed; refresh before retrying')
            for row in rows:
                state=dict(row['progress'],desired='running' if body.action=='resume' else 'paused')
                c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),row['idempotency_key']))
        store.event('bulk_'+body.action,f'{body.action.title()} requested for {len(rows)} bots')
        return dict(contract='demo-v1',accepted=True,count=len(rows))
    @app.get('/demo/activity')
    def activity(request:Request):
        auth(request);require_query(request,('before','bot','ticker','kind','version'))
        before=request.query_params.get('before');bot=request.query_params.get('bot');ticker=request.query_params.get('ticker');kind=request.query_params.get('kind')
        try:
            if before:UUID(before)
            if bot:UUID(bot)
        except ValueError:raise HTTPException(422,'Invalid identifier') from None
        if ticker and len(ticker)>256 or kind and len(kind)>800:raise HTTPException(422,'Invalid filter')
        kinds=None
        if kind:
            import re
            selected=kind.split(',')
            if len(selected)>20 or any(not re.fullmatch('[a-z_]{1,40}',part) for part in selected):raise HTTPException(422,'Invalid activity types')
            transactions=['order_intent','order','order_rejected','order_uncertain','fill','fill_recovered','cancel','settlement','realized','position_offset']
            kinds=list(dict.fromkeys(k for part in selected for k in (transactions if part=='transactions' else [part])))
        analysis_version=request.query_params.get('version','full')
        if analysis_version not in ('full','latest'):raise HTTPException(422,'Invalid analysis version')
        from .demo_versions import activity_version_clause
        activity_scope,activity_args=activity_version_clause(analysis_version,versions.load())
        with pool.connection() as c:
            rows=c.execute("""SELECT id::text,parameters,progress FROM research_job
                WHERE status='succeeded' AND idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                AND (%s::uuid IS NULL OR (created_at,id)<(SELECT created_at,id FROM research_job WHERE id=%s::uuid))
                AND (%s::text IS NULL OR parameters->>'bot'=%s)
                AND (%s::text IS NULL OR parameters->>'ticker'=%s)
                AND (%s::text[] IS NULL OR parameters->>'kind'=ANY(%s::text[]))
                AND """+activity_scope+""" ORDER BY created_at DESC,id DESC LIMIT 51""",[before,before,bot,bot,ticker,ticker,kinds,kinds,*activity_args]).fetchall()
        return dict(contract='demo-v1',items=[{'id':r['id'],**r['parameters'],**r['progress']} for r in rows[:50]],next_before=rows[49]['id'] if len(rows)>50 else None)
    @app.get('/demo/orders')
    def orders(request:Request):
        auth(request);require_query(request,('client_id','completed','before','bot','ticker','version'))
        if request.query_params.get('completed')=='true':
            if 'client_id' in request.query_params:raise HTTPException(422,'Choose one order view')
            before=request.query_params.get('before') or None;bot=request.query_params.get('bot') or None;ticker=request.query_params.get('ticker') or None
            try:
                if before:UUID(before)
                if bot:UUID(bot)
            except ValueError:raise HTTPException(422,'Invalid identifier') from None
            if ticker and len(ticker)>256:raise HTTPException(422,'Invalid market')
            from .demo_pairs import completed_pairs
            analysis_version=request.query_params.get('version','full')
            if analysis_version not in ('full','latest'):raise HTTPException(422,'Invalid analysis version')
            return completed_pairs(pool,before,bot,ticker,analysis_version,versions.load())
        if any(k!='client_id' for k in request.query_params):raise HTTPException(422,'Invalid filters')
        if 'client_id' not in request.query_params:return dict(contract='demo-v1',items=store.active_orders())
        try:identifier=str(UUID(request.query_params['client_id']))
        except ValueError:raise HTTPException(422,'Choose a valid order') from None
        selected=store.get('order/'+identifier)
        if not selected:raise HTTPException(404,'Saved order not found')
        chosen=dict(selected['parameters'],**selected['progress'])
        if chosen.get('kind')=='exit':
            parent=chosen.get('parent')
            if not isinstance(parent,str):raise HTTPException(409,'This sell has no verified buy link')
            root=store.get('order/'+parent)
        else:root=selected
        if not root:raise HTTPException(409,'The linked buy is unavailable')
        entry=dict(root['parameters'],**root['progress'])
        if entry.get('kind')!='entry' or not entry.get('client_id'):raise HTTPException(409,'The linked buy could not be verified')
        def same_lot(order):return all(order.get(k)==entry.get(k) for k in ('bot','ticker','side'))
        if chosen.get('kind')=='exit' and not same_lot(chosen):raise HTTPException(409,'Order links need reconciliation')
        with pool.connection() as c:
            rows=c.execute("""SELECT parameters,progress,finished_at FROM research_job
                WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND parameters->>'kind'='exit' AND parameters->>'parent'=%s
                ORDER BY (progress->>'status' NOT IN ('closed','rejected')) DESC,created_at DESC,id DESC LIMIT 101""",(entry['client_id'],)).fetchall()
        exits=[dict(r['parameters'],**r['progress'],saved_at=r['finished_at']) for r in rows[:100]]
        if any(not same_lot(o) for o in exits):raise HTTPException(409,'Order links need reconciliation')
        with pool.connection() as c:
            settled=c.execute("""SELECT progress FROM research_job WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                AND parameters->>'kind'='settlement' AND parameters->>'bot'=%s
                AND progress#>>'{details,client_id}'=%s ORDER BY created_at DESC,id DESC LIMIT 1""",(entry.get('bot'),entry['client_id'])).fetchone()
        return dict(contract='demo-v1',entry=entry,exits=exits,selected=identifier,settlement=settled['progress'] if settled else None,
            saved_at=root['finished_at'],limited=len(rows)>100,at=time.time())
    @app.get('/demo/chart')
    def chart(request:Request):
        auth(request);require_query(request,('period',))
        period=request.query_params.get('period','24H');hours=PERIOD_HOURS.get(period)
        if hours is None:raise HTTPException(422,'Invalid period')
        with pool.connection() as c:
            rows=c.execute("""SELECT progress FROM research_job WHERE idempotency_key>='demo/equity/'
                AND idempotency_key<'demo/equity/zzzz' AND created_at>clock_timestamp()-%s*interval '1 hour'
                ORDER BY created_at DESC LIMIT 2880""",(hours,)).fetchall()
        # At most 192 points on mobile, independent of underlying snapshot count.
        points=[r['progress'] for r in reversed(rows)];step=max(1,(len(points)+191)//192)
        return dict(contract='demo-v1',points=points[::step],period=period)
    @app.get('/demo/performance')
    def square_performance(request:Request):
        auth(request);require_query(request,('bot','group','period','timezone','start','end','version'))
        try:identifier=str(UUID(request.query_params.get('bot','')))
        except ValueError:raise HTTPException(422,'Choose a bot') from None
        bot=bot_get(identifier)
        group=request.query_params.get('group','square');period=request.query_params.get('period','all');zone=request.query_params.get('timezone','America/Los_Angeles')
        from .demo_performance import query_performance,time_bounds
        analysis_version=request.query_params.get('version','full')
        if analysis_version not in ('full','latest'):raise HTTPException(422,'Invalid analysis version')
        cohort=versions.load().get(identifier) if analysis_version=='latest' else None
        try:items,limited=query_performance(pool,bot['parameters'],identifier,group,period,zone,request.query_params.get('start') or None,request.query_params.get('end') or None,revision=cohort['revision'] if cohort else None)
        except (ValueError,KeyError,OverflowError):raise HTTPException(422,'Invalid performance filters') from None
        return dict(contract='demo-v1',bot=identifier,analysis_version=analysis_version,analysis_version_info=cohort,period='Lifetime' if period=='all' else period,group=group,timezone=zone,time_bounds=time_bounds(bot['parameters']),default_entry_price=bot['parameters']['config'].get('cycle_buy_cents'),start=request.query_params.get('start'),end=request.query_params.get('end'),items=items,limited=limited,at=time.time())
    @app.get('/demo/research')
    def research(request:Request):
        auth(request);require_query(request,('asset','bot','start','end'))
        from datetime import date,timedelta
        from services.research.reports import SERIES
        asset=request.query_params.get('asset');bot=request.query_params.get('bot') or None
        if asset not in SERIES:raise HTTPException(422,'Choose a category')
        try:
            start=date.fromisoformat(request.query_params.get('start',''));end=date.fromisoformat(request.query_params.get('end',''))
            if bot:UUID(bot)
            if end<start or end-start>timedelta(days=3660):raise ValueError()
        except ValueError:raise HTTPException(422,'Choose a valid date range') from None
        from datetime import datetime,timezone
        begin=datetime.combine(start,datetime.min.time(),timezone.utc);through=datetime.combine(end+timedelta(days=1),datetime.min.time(),timezone.utc)
        with pool.connection() as c:
            rows=c.execute("""SELECT parameters->'condition' AS condition,parameters->>'side' AS side,
                count(*) AS orders,coalesce(sum((progress->>'filled')::numeric),0) AS contracts,
                coalesce(sum((progress->>'realized_cents')::numeric),0) AS realized_cents
                FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND parameters->>'kind'='entry' AND parameters->'condition'->>'asset'=%s
                AND created_at >= %s AND created_at < %s AND (%s::text IS NULL OR parameters->>'bot'=%s)
                GROUP BY parameters->'condition',parameters->>'side' LIMIT 101""",(asset,begin,through,bot,bot)).fetchall()
        return dict(contract='demo-v1',source='kalshi-demo',items=rows[:100],limited=len(rows)>100)
    @app.post('/demo/policy')
    def policy(body:Policy,request:Request):
        mutate(request);require_query(request);store.put('policy',body.model_dump())
        store.event('policy_updated','Storage, archiving and alert settings updated')
        return dict(contract='demo-v1',saved=True)
    class Connection(BaseModel):
        model_config=ConfigDict(extra='forbid')
        key_id:str=Field(min_length=1,max_length=128)
        private_key:str=Field(min_length=100,max_length=12000)
    @app.post('/demo/connection')
    def connect(body:Connection,request:Request):
        mutate(request);require_query(request)
        key=os.environ.get('DEMO_VAULT_KEY')
        if not key:raise HTTPException(503,'Secure account connection is not configured yet')
        from services.demo.exchange import encrypt_credentials,CredentialInputError
        try:encrypted=encrypt_credentials(key,body.key_id,body.private_key)
        except CredentialInputError as error:raise HTTPException(422,str(error)) from None
        except Exception:raise HTTPException(503,'The server could not securely save the connection. Your key has not been marked invalid; please retry shortly.') from None
        store.put('credentials',dict(encrypted=encrypted,changed_at=time.time()))
        store.event('connection_updated','Demo account credentials updated; verification pending')
        return dict(contract='demo-v1',saved=True)
    @app.post('/demo/refresh')
    def refresh(request:Request):
        mutate(request);require_query(request);store.put('refresh',dict(requested_at=time.time()))
        return dict(contract='demo-v1',accepted=True)
    @app.post('/demo/restore/{identifier}')
    def restore(identifier:UUID,request:Request):
        mutate(request);require_query(request)
        with pool.connection() as c:
            row=c.execute("SELECT progress FROM research_job WHERE id=%s AND idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'",(identifier,)).fetchone()
        if not row or not row['progress'].get('archive'):raise HTTPException(404,'Archived event not found')
        store.put('restore/'+str(identifier),dict(event_id=str(identifier),requested_at=time.time()))
        return dict(contract='demo-v1',accepted=True)

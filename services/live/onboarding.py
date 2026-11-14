"""Owner-driven Kalshi setup. No orders, automatic money movement, or saved setup key."""
import hashlib,json,time,re
from decimal import Decimal,ROUND_DOWN
from uuid import UUID,uuid4
import httpx
from psycopg.types.json import Jsonb
from services.demo.exchange import DemoSigner,ExchangeFailure,PATH,PUBLIC_ACTIVITY_ROOT
from services.trading.mode import LOCK as MODE_LOCK

SETUP_LOCK=723741943
KEY='live/onboarding'
CONFIRM=dict(upgrade='REQUEST ADVANCED ACCESS',create='CREATE ISOLATED ACCOUNT',prepare='PREPARE UP TO $50',fund='FUND ISOLATED ACCOUNT $50',connect='CREATE RESTRICTED KEY')
TIERS={'advanced','expert','premier','paragon','prime','prestige','institutional','market_maker'}
class SetupError(ValueError):pass

class SetupExchange:
    """Ephemeral broad key; narrowly fixed production routes, never trading."""
    def __init__(self,key_id,pem,client=None):
        self.signer=DemoSigner(key_id,pem)
        self.client=client or httpx.Client(timeout=httpx.Timeout(8,connect=5),follow_redirects=False)
        self.approved=None
    def close(self):self.client.close()
    def call(self,method,path,params=None,body=None):
        reads=path in ('/api_keys','/account/limits','/portfolio/subaccounts/balances','/portfolio/balance','/portfolio/orders','/portfolio/positions','/portfolio/subaccounts/transfers','/portfolio/intra_exchange_instance_transfers','/markets') or re.fullmatch(r'/portfolio/intra_exchange_instance_transfers/[A-Za-z0-9-]{1,128}',path)
        writes=path in ('/account/api_usage_level/upgrade','/portfolio/subaccounts','/portfolio/subaccounts/transfer','/portfolio/intra_exchange_instance_transfer','/api_keys/generate')
        if method=='GET' and not reads or method!='GET' and (method!='POST' or not writes or self.approved!=(path,body)):
            raise SetupError('Setup cannot trade or call an unsupported operation')
        try:
            with self.client.stream(method,PUBLIC_ACTIVITY_ROOT+PATH+path,params=params,json=body,headers=self.signer.headers(method,PATH+path)) as response:
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>1048576:raise ExchangeFailure('response_too_large',method!='GET')
                if not 200<=response.status_code<300:
                    raise ExchangeFailure('setup_provider_rejected',method!='GET' and response.status_code>=500,status=response.status_code)
                result=json.loads(data) if data else {}
                if not isinstance(result,dict):raise ExchangeFailure('invalid_page',method!='GET')
                return result
        except (httpx.HTTPError,ValueError):raise ExchangeFailure('setup_connection',method!='GET') from None
    def write(self,path,body):
        validate_write(path,body)
        self.approved=(path,dict(body))
        try:return self.call('POST',path,body=body)
        finally:self.approved=None

def validate_write(path,body):
    def index(v):return type(v) is int and 0<=v<=100
    def account(v):return type(v) is int and 1<=v<=63
    def identifier(v):
        try:return str(UUID(v))==v
        except (ValueError,TypeError,AttributeError):return False
    valid=False
    if path=='/account/api_usage_level/upgrade':valid=body=={}
    elif path=='/portfolio/subaccounts':valid=set(body)=={'exchange_index'} and index(body['exchange_index'])
    elif path=='/portfolio/subaccounts/transfer':
        valid=set(body)=={'from_subaccount','to_subaccount','amount_cents','exchange_index','client_transfer_id'} and type(body['from_subaccount']) is int and body['from_subaccount']==0 and account(body['to_subaccount']) and type(body['amount_cents']) is int and body['amount_cents']==5000 and index(body['exchange_index']) and identifier(body['client_transfer_id'])
    elif path=='/portfolio/intra_exchange_instance_transfer':
        valid=set(body)=={'source','destination','source_subaccount','destination_subaccount','source_exchange_shard','destination_exchange_shard','amount','client_transfer_id'} and body['source']==body['destination']=='event_contract' and type(body['source_subaccount']) is int and type(body['destination_subaccount']) is int and body['source_subaccount']==body['destination_subaccount']==0 and index(body['source_exchange_shard']) and index(body['destination_exchange_shard']) and body['source_exchange_shard']!=body['destination_exchange_shard'] and type(body['amount']) is int and 0<body['amount']<=500000 and body['amount']%100==0 and identifier(body['client_transfer_id'])
    elif path=='/api_keys/generate':
        valid=set(body)=={'name','subaccount','scopes','key_type'} and account(body['subaccount']) and body['scopes']==['read','write::trade'] and body['key_type']=='ed25519' and isinstance(body['name'],str) and body['name'].startswith('Money Tree Trading ') and identifier(body['name'][19:])
    if not valid:raise SetupError('Setup write exceeds the fixed $50 plan or allowed key permissions')

def get(c,key):
    row=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()
    return row['progress'] if row else None

def put(c,key,data):
    c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
        VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())
        ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(data),key))

def lock(c):
    c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
    c.execute('SELECT pg_advisory_xact_lock(%s)',(SETUP_LOCK,))
    mode=get(c,'trading/mode') or dict(mode='demo')
    if mode.get('mode')!='demo' or get(c,'live/trial'):raise SetupError('Setup is available only before a LIVE trial, while the worker is in Demo mode')

def fingerprint(exchange):return hashlib.sha256(('setup\0'+exchange.signer.identifier).encode()).hexdigest()

def cents(raw):
    d=Decimal(str(raw))
    if not d.is_finite() or d<0:raise SetupError('Kalshi returned an invalid cash balance')
    return int((d*100).to_integral_value(rounding=ROUND_DOWN))

def public(state):
    if not state:return None
    keys=('id','bot','tier','eligible','can_write','exchange_index','market_running','subaccount','account_cents','market_cents','primary_market_cents','prepare_cents','source_index','busy','message','connected','updated_at')
    return {k:state.get(k) for k in keys}

class Onboarding:
    def __init__(self,store,exchange,vault_key):self.store,self.exchange,self.vault=store,exchange,vault_key
    def record(self):
        row=self.store.get('onboarding');return row['progress'] if row else None
    def snapshot(self,bot,subaccount=None):
        key_rows=self.exchange.call('GET','/api_keys').get('api_keys')
        if not isinstance(key_rows,list):raise SetupError('Could not verify setup-key permissions')
        key=next((k for k in key_rows if k.get('api_key_id')==self.exchange.signer.identifier),None)
        if not key or key.get('subaccount') is not None or key.get('fcm_subtrader_id'):
            raise SetupError('Use a temporary unrestricted setup key here. Use the existing connection form for a restricted trading key.')
        scopes=key.get('scopes',[])
        if 'read' not in scopes:raise SetupError('The setup key needs Read permission')
        limits=self.exchange.call('GET','/account/limits');tier=limits.get('usage_tier')
        if not isinstance(tier,str) or not re.fullmatch('[a-z_]{1,30}',tier):raise SetupError('Could not verify your API access tier')
        row=self.store.get('bot/'+bot)
        if not row:raise SetupError('Select an existing LIVE bot for setup')
        from services.research.reports import SERIES
        from services.demo.runtime import quote
        series={s for square in row['parameters']['config']['squares'] for s in SERIES[square['asset']]}
        if len(series)!=1:raise SetupError('Select a bot covering one 15-minute market series')
        now=time.time();page=self.exchange.call('GET','/markets',params=dict(series_ticker=next(iter(series)),status='open',min_close_ts=int(now),max_close_ts=int(now+900),limit=200))
        if not isinstance(page.get('markets'),list) or page.get('cursor'):raise SetupError('Could not fully verify the selected market')
        current=[q for raw in page['markets'] if (parsed:=quote(raw,now)) and (q:=parsed[1])['series'] in series and q['status']=='active' and q.get('open',now+1)<=now<q['close']]
        index=min(current,key=lambda q:q['close'])['exchange_index'] if current else None
        rows=self.exchange.call('GET','/portfolio/subaccounts/balances').get('subaccount_balances') if tier in TIERS else []
        if not isinstance(rows,list) or len(rows)>6464:raise SetupError('Could not verify your subaccounts')
        balances={}
        for r in rows:
            n=r.get('subaccount_number');i=r.get('exchange_index')
            if type(n) is not int or not 0<=n<=63 or type(i) is not int or not 0<=i<=100 or (n,i) in balances:raise SetupError('Invalid subaccount balance response')
            balances[n,i]=cents(r['balance'])
        primary=balances.get((0,index),0);needed=max(0,5000-primary)
        donors=sorted(((-v,i) for (n,i),v in balances.items() if n==0 and i!=index and v>=needed)) if needed else []
        result=dict(tier=tier,eligible=tier in TIERS,can_write='write' in scopes,exchange_index=index,market_running=bool(current),primary_market_cents=min(primary,5000),
            prepare_cents=needed,source_index=donors[0][1] if donors and index is not None else None,account_cents=None,market_cents=None)
        if subaccount is not None:
            result['account_cents']=sum(v for (n,i),v in balances.items() if n==subaccount)
            result['market_cents']=balances.get((subaccount,index),0)
            if not any(n==subaccount for n,i in balances):raise SetupError('The selected isolated subaccount could not be found')
            orders=self.exchange.call('GET','/portfolio/orders',params=dict(subaccount=subaccount,status='resting',limit=1))
            if orders.get('orders')!=[] or orders.get('cursor'):
                raise SetupError('The isolated subaccount has resting orders; resolve those before setup')
            positions=self.exchange.call('GET','/portfolio/positions',params=dict(subaccount=subaccount,count_filter='position',limit=1))
            if positions.get('market_positions')!=[] or positions.get('cursor'):raise SetupError('The isolated subaccount must have no positions')
        return result
    def check(self,bot):
        old=self.record();bound=fingerprint(self.exchange)
        if old and old.get('binding')!=bound:raise SetupError('This setup belongs to a different setup key; keep using the original key until its pending actions are resolved')
        if old and old.get('bot')!=bot:raise SetupError('Finish the existing setup before selecting a different bot')
        snap=self.snapshot(bot,old.get('subaccount') if old else None)
        with self.store.pool.connection() as c:
            lock(c);state=get(c,KEY)
            if state and state.get('binding')!=bound:raise SetupError('Setup changed; refresh first')
            if get(c,'live/credentials') and not (state or {}).get('connected'):raise SetupError('LIVE already has a connection; use its readiness check')
            state=state or dict(id=str(uuid4()),bot=bot,binding=bound,subaccount=None,busy=None,connected=False)
            if state.get('subaccount') and state.get('exchange_index')!=snap['exchange_index']:
                raise SetupError('The selected market moved exchanges. Review the existing setup before moving funds.')
            state.update(snap,updated_at=time.time())
            state['message']='Account checked. All bots remain unchanged.' if state['eligible'] else 'Advanced access is required. Kalshi requires an API-created order among your last 100 Predictions orders for its self-service upgrade. This setup never places qualifying orders.'
            put(c,KEY,state)
        self.reconcile(state)
        return public(self.record())
    def opkey(self,state,action):return 'live/onboarding-op/'+state['id']+'/'+action
    def reconcile(self,state):
        action=state.get('busy')
        if action not in ('prepare','fund','upgrade'):return
        row=self.store.get('onboarding-op/'+state['id']+'/'+action)
        if not row:return
        op=row['progress'];body=op['body'];transfer=None
        if action=='upgrade':
            if state.get('eligible'):self.finish(state,action,op,dict(message='Advanced API access verified. Continue to account creation.'))
            return
        if action=='fund':
            # The history endpoint omits client_transfer_id. Verify the result
            # against fresh scoped cash instead of inventing an ID match.
            if state.get('account_cents')==5000 and state.get('market_cents')==5000:
                self.finish(state,action,op,dict(message='Exactly $50 is isolated. Funding will not be repeated.'))
            return
        if action=='prepare' and op.get('transfer_id'):
            transfer=self.exchange.call('GET','/portfolio/intra_exchange_instance_transfers/'+op['transfer_id']).get('transfer')
        else:
            path='/portfolio/intra_exchange_instance_transfers' if action=='prepare' else '/portfolio/subaccounts/transfers'
            cursor=None
            for _ in range(5):
                page=self.exchange.call('GET',path,params=dict(limit=200,**({'cursor':cursor} if cursor else {})))
                rows=page.get('transfers')
                if not isinstance(rows,list) or len(rows)>200:raise SetupError('Transfer history could not be verified')
                transfer=next((r for r in rows if r.get('client_transfer_id')==body['client_transfer_id']),None)
                nxt=page.get('cursor')
                if transfer or not nxt:break
                if nxt==cursor:raise SetupError('Transfer history is incomplete')
                cursor=nxt
        if not transfer:return
        if action=='prepare':
            matches=transfer.get('source')=='event_contract' and transfer.get('destination')=='event_contract' and transfer.get('source_exchange_shard')==body['source_exchange_shard'] and transfer.get('destination_exchange_shard')==body['destination_exchange_shard'] and Decimal(str(transfer.get('amount','-1')))*10000==body['amount'] and transfer.get('status')=='complete'
        else:
            matches=all(transfer.get(k)==body[k] for k in ('client_transfer_id','from_subaccount','to_subaccount','amount_cents','exchange_index'))
        if matches:self.finish(state,action,op,dict(message='Transfer confirmed. Refresh setup to verify current cash.'))
    def finish(self,state,action,op,changes,credentials=None):
        with self.store.pool.connection() as c:
            lock(c);saved=get(c,KEY)
            if not saved or saved['id']!=state['id'] or saved.get('busy')!=action:raise SetupError('Setup changed during verification; no additional action was requested')
            if credentials:
                if get(c,'live/credentials'):raise SetupError('LIVE connection changed; review before replacing it')
                put(c,'live/credentials',credentials)
            put(c,self.opkey(state,action),dict(op,status='complete',completed_at=time.time()))
            saved.update(changes,busy=None,updated_at=time.time());put(c,KEY,saved)
    def perform(self,action,bot,draft,confirmation):
        if confirmation!=CONFIRM.get(action):raise SetupError('Type the confirmation shown beside this setup action')
        state=self.record()
        if not state or state['id']!=draft or state.get('binding')!=fingerprint(self.exchange) or state.get('bot')!=bot:raise SetupError('Check this account first; setup details changed')
        if state.get('connected'):return public(state)
        snap=self.snapshot(bot,state.get('subaccount'))
        if not snap['can_write']:raise SetupError('The temporary setup key needs Read and Write permissions')
        if action!='upgrade' and not snap['eligible']:raise SetupError('Advanced API access is required before creating the isolated account')
        if state.get('exchange_index')!=snap['exchange_index']:raise SetupError('The selected market changed. Refresh setup before proceeding')
        n=state.get('subaccount');index=snap['exchange_index']
        if action=='upgrade':path='/account/api_usage_level/upgrade';body={}
        elif action=='create':
            if n is not None:raise SetupError('This setup already has an isolated account')
            if index is None:raise SetupError('Wait until the selected market is running before creating its isolated account')
            path='/portfolio/subaccounts';body=dict(exchange_index=index)
        elif action=='prepare':
            if not n or snap['account_cents']!=0:raise SetupError('Create an empty isolated account first')
            amount=snap['prepare_cents']
            if not amount:raise SetupError('Enough primary cash is already available for this market; continue to funding')
            if snap['source_index'] is None:raise SetupError('No single primary exchange balance can supply the cash needed for this $50 setup')
            path='/portfolio/intra_exchange_instance_transfer';body=dict(source='event_contract',destination='event_contract',source_subaccount=0,destination_subaccount=0,source_exchange_shard=snap['source_index'],destination_exchange_shard=index,amount=amount*100,client_transfer_id=str(uuid4()))
        elif action=='fund':
            if not n or snap['account_cents']!=0:raise SetupError('Funding requires an empty isolated account; the setup will not top up or send a second $50')
            if snap['primary_market_cents']<5000:raise SetupError('Prepare the primary cash for this market first')
            path='/portfolio/subaccounts/transfer';body=dict(from_subaccount=0,to_subaccount=n,amount_cents=5000,exchange_index=index,client_transfer_id=str(uuid4()))
        elif action=='connect':
            if not n or snap['account_cents']!=5000 or snap['market_cents']!=5000:raise SetupError('The isolated account must contain exactly $50 on the selected market exchange')
            if not self.vault:raise SetupError('Secure trading-key storage is not configured')
            from cryptography.fernet import Fernet
            try:Fernet(self.vault.encode())
            except (ValueError,TypeError):raise SetupError('Secure trading-key storage is not configured') from None
            path='/api_keys/generate';body=dict(name='Money Tree Trading '+state['id'],subaccount=n,scopes=['read','write::trade'],key_type='ed25519')
        else:raise SetupError('Unknown setup action')
        with self.store.pool.connection() as c:
            lock(c);saved=get(c,KEY)
            if not saved or saved['id']!=draft or saved.get('binding')!=state['binding'] or saved.get('busy'):raise SetupError('A setup action is already pending; refresh to verify it before doing anything else')
            old=get(c,self.opkey(state,action))
            if old:raise SetupError('This action was already requested. Refresh setup; it will not be automatically repeated.')
            if get(c,'live/credentials'):raise SetupError('LIVE already has a connection')
            op=dict(status='intent',path=path,body=body,at=time.time())
            put(c,self.opkey(state,action),op);saved.update(busy=action,updated_at=time.time(),message='Action requested. Unknown responses are verified before any further action.');put(c,KEY,saved)
        try:
            result=self.exchange.write(path,body)
            if action=='upgrade':
                tier=self.exchange.call('GET','/account/limits').get('usage_tier')
                self.finish(state,action,op,dict(tier=tier,eligible=tier in TIERS,message='API access checked. Refresh setup before continuing.'))
            elif action=='create':
                number=result.get('subaccount_number')
                if type(number) is not int or not 1<=number<=63:raise ExchangeFailure('setup_create_contract',True)
                self.finish(state,action,op,dict(subaccount=number,account_cents=0,market_cents=0,message='Isolated account created. Refresh to check the $50 funding steps.'))
            elif action=='prepare':
                identifier=result.get('transfer_id')
                if not isinstance(identifier,str) or not re.fullmatch('[A-Za-z0-9-]{1,128}',identifier):raise ExchangeFailure('setup_transfer_contract',True)
                self.store.put('onboarding-op/'+state['id']+'/'+action,dict(op,status='pending',transfer_id=identifier))
                self.reconcile(self.record())
            elif action=='fund':
                cash=self.exchange.call('GET','/portfolio/balance',params=dict(subaccount=n))
                if cash.get('balance')==5000 and cash.get('portfolio_value')==0:
                    self.finish(state,action,op,dict(account_cents=5000,market_cents=5000,message='Exactly $50 is isolated. Refresh setup, then create the restricted trading key.'))
                else:self.store.put('onboarding-op/'+state['id']+'/'+action,dict(op,status='pending'))
            else:
                from services.live.exchange import verified_connection
                record=verified_connection(result['api_key_id'],result['private_key'],n,self.vault)
                self.finish(state,action,op,dict(connected=True,message='Restricted trading key verified and encrypted. All LIVE bots remain paused. Clear and revoke the temporary setup key in Kalshi Profile Settings.'),credentials=record)
        except Exception as error:
            # Durable intent blocks repeat writes even after a lost response or
            # a failure between the provider write and the database commit.
            self.store.put('onboarding-op/'+state['id']+'/'+action,dict(op,status='uncertain',error_status=getattr(error,'status',None)))
            raise SetupError('The setup action could not be fully verified. Refresh setup before continuing; no automatic retry or trading will occur.') from None
        return public(self.record())

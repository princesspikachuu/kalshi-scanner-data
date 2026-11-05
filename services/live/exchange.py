"""Production-only, restricted-subaccount transport. No money-transfer routes."""
import hashlib,json,re,time
import httpx
from cryptography.fernet import Fernet
from services.demo.exchange import Exchange,ExchangeFailure,DemoSigner,PATH,PUBLIC_ACTIVITY_ROOT

class LiveConnectionError(ValueError):pass

def binding(key_id,subaccount):
    return hashlib.sha256(('live\0'+key_id+'\0'+str(subaccount)).encode()).hexdigest()

class LiveExchange(Exchange):
    root=PUBLIC_ACTIVITY_ROOT
    ws_root="wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    def __init__(self,signer,subaccount,*,client=None,guard=lambda:None,order_guard=None):
        if type(subaccount) is not int or not 1<=subaccount<=63:raise LiveConnectionError('Use a numbered, isolated live subaccount')
        super().__init__(signer,client=client,guard=guard)
        self.subaccount=subaccount;self.scope_verified=False;self.order_guard=order_guard;self.guarded_body=None
    def call(self,method,path,*,params=None,body=None):
        if path.startswith('/portfolio/'):
            if method=='GET':
                allowed=path in ('/portfolio/balance','/portfolio/positions','/portfolio/orders','/portfolio/fills','/portfolio/settlements') or re.fullmatch(r'/portfolio/orders/[A-Za-z0-9-]{1,128}',path)
                if not allowed:raise LiveConnectionError('Live read route is not allowed')
                params=dict(params or {},subaccount=self.subaccount)
            elif method=='POST' and path in ('/portfolio/events/orders','/portfolio/events/orders/batched'):
                if not self.scope_verified:raise LiveConnectionError('Live subaccount is not verified')
                if self.guarded_body is None or body!=self.guarded_body:raise LiveConnectionError('Live order did not pass the pilot guard')
                body=dict(body or {})
                if path.endswith('/batched'):
                    body['orders']=[dict(o,subaccount=self.subaccount) for o in body.get('orders',[])]
                else:body['subaccount']=self.subaccount
            elif method=='DELETE' and re.fullmatch(r'/portfolio/events/orders/[A-Za-z0-9-]{1,128}',path):
                if not self.scope_verified:raise LiveConnectionError('Live subaccount is not verified')
                params=dict(params or {},subaccount=self.subaccount)
            else:raise LiveConnectionError('Live transfers and unsupported writes are disabled')
        elif method!='GET' or path not in ('/account/limits','/account/endpoint_costs'):
            if method=='GET':return self.public_get(path,params=params)
            raise LiveConnectionError('Live writes are limited to owned orders')
        return super().call(method,path,params=params,body=body)
    def public_get(self,path,params=None):
        allowed=path in ('/markets','/markets/trades','/exchange/status','/events/fee_changes','/series/fee_changes') or re.fullmatch(r'/(?:markets/[A-Za-z0-9-]{1,128}(?:/orderbook)?|series/[A-Za-z0-9-]{1,128})',path)
        if not allowed:raise LiveConnectionError('Unsupported public market-data route')
        if time.monotonic()<getattr(self,'public_cooldown',0):raise ExchangeFailure('activity_rate_limited')
        try:
            with self.client.stream('GET',self.root+PATH+path,params=params) as response:
                if response.status_code==429:
                    self.public_cooldown=time.monotonic()+30;raise ExchangeFailure('activity_rate_limited')
                if response.status_code!=200:raise ExchangeFailure('activity_unavailable',status=response.status_code)
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>1048576:raise ExchangeFailure('response_too_large')
                result=json.loads(data)
                if not isinstance(result,dict):raise ExchangeFailure('invalid_page')
                return result
        except (httpx.HTTPError,ValueError):raise ExchangeFailure('activity_unavailable') from None
    def market_activity_call(self,method,path,*,params=None):
        if method!='GET':raise LiveConnectionError('Activity checks are read-only')
        return self.public_get(path,params)
    def verify_scope(self):
        # Verify read access to the chosen bucket, then require the exchange to
        # explicitly reject a read of the always-existing primary bucket.
        self.call('GET','/portfolio/balance')
        try:
            with self.client.stream('GET',self.root+PATH+'/portfolio/balance',params=dict(subaccount=0),headers=self.signer.headers('GET',PATH+'/portfolio/balance')) as response:
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk[:max(0,4096-len(data))])
                    if len(data)>=4096:break
                message=bytes(data).decode(errors='replace').lower().replace('-','').replace(' ','')
                if response.status_code!=403 or 'restricted' not in message or 'subaccount' not in message:
                    raise LiveConnectionError('Use an API key restricted to the selected subaccount; a full-portfolio key is not accepted')
        except httpx.HTTPError:raise LiveConnectionError('Could not verify subaccount restrictions') from None
        self.scope_verified=True
        return True
    def submit(self,intent):
        if self.order_guard is None:raise LiveConnectionError('Live order guard is missing')
        from services.demo.engine import wire_order
        poll=self.before_read;self.before_read=None
        try:self.order_guard([intent])
        finally:self.before_read=poll
        self.guarded_body=wire_order(intent)
        try:return super().submit(intent)
        finally:self.guarded_body=None
    def submit_batch(self,intents):
        if self.order_guard is None:raise LiveConnectionError('Live order guard is missing')
        raise LiveConnectionError('Batched orders are disabled during the one-contract pilot')

def save_connection(store,key_id,pem,subaccount,vault_key):
    signer=DemoSigner(key_id,pem)
    exchange=LiveExchange(signer,subaccount)
    try:exchange.verify_scope()
    finally:exchange.close()
    payload=dict(environment='live',key_id=key_id,pem=pem,subaccount=subaccount,binding=binding(key_id,subaccount))
    sealed=Fernet(vault_key.encode()).encrypt(json.dumps(payload).encode()).decode()
    store.put('credentials',dict(encrypted=sealed,subaccount=subaccount,binding=payload['binding'],verified_at=time.time()))
    return payload['binding']

def load_connection(store,vault_key):
    row=store.get('credentials')
    if not row or not vault_key:return None
    data=json.loads(Fernet(vault_key.encode()).decrypt(row['progress']['encrypted'].encode()))
    if data.get('environment')!='live' or data.get('binding')!=binding(data['key_id'],data['subaccount']):raise LiveConnectionError('Live credential binding is invalid')
    return data

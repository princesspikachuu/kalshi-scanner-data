"""Demo-only V2 transport. Fixed destinations, bounded responses, no write retries."""
import base64,json,time,re
import httpx
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding,ed25519
from cryptography.fernet import Fernet

ROOT='https://external-api.demo.kalshi.co'
WS='wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2'
PATH='/trade-api/v2'
PUBLIC_ACTIVITY_ROOT='https://external-api.kalshi.com'
class ExchangeFailure(Exception):
    def __init__(self,code,ambiguous=False,*,status=None,provider_code=None,reason=None):
        self.code,self.ambiguous=code,ambiguous
        self.status,self.provider_code,self.reason=status,provider_code,reason

class CredentialInputError(ValueError):
    """Fixed, safe form feedback; never includes submitted credential content."""


def normalize_pem(pem):
    text=pem.strip().lstrip('\ufeff').replace('\\r\\n','\n').replace('\\n','\n').replace('\r\n','\n')
    text=text.strip()
    if len(text)>1 and text[0]==text[-1] and text[0] in ('"',"'"):text=text[1:-1].strip()
    if text.startswith('```') and text.endswith('```'):text='\n'.join(text.splitlines()[1:-1]).strip()
    if '-----BEGIN ENCRYPTED PRIVATE KEY-----' in text:
        raise CredentialInputError('This private key is password-protected. Use the original unencrypted private-key file downloaded from Kalshi.')
    match=re.fullmatch(r'-----BEGIN (RSA PRIVATE KEY|PRIVATE KEY)-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END \1-----',text)
    if not match:
        raise CredentialInputError('The private-key format could not be read. Include the complete BEGIN and END lines from the Kalshi key file.')
    body=re.sub(r'\s+','',match[2])
    return '-----BEGIN '+match[1]+'-----\n'+'\n'.join(body[i:i+64] for i in range(0,len(body),64))+'\n-----END '+match[1]+'-----\n'

class DemoSigner:
    def __init__(self,key_id,pem):
        identifier=key_id.strip().lstrip('\ufeff')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',identifier):
            raise CredentialInputError('Enter the API key ID in the key-ID field, separate from the private key.')
        normalized=normalize_pem(pem)
        try:self.key=serialization.load_pem_private_key(normalized.encode(),None)
        except (ValueError,TypeError):
            raise CredentialInputError('The private-key contents could not be read. Try the complete original file downloaded from Kalshi.') from None
        if not isinstance(self.key,(rsa.RSAPrivateKey,ed25519.Ed25519PrivateKey)):
            raise CredentialInputError('Kalshi credentials must use an Ed25519 or RSA private key.')
        if isinstance(self.key,rsa.RSAPrivateKey) and self.key.key_size<2048:
            raise CredentialInputError('RSA private keys must be at least 2048 bits.')
        self.identifier=identifier
    def headers(self,method,path):
        if not path.startswith(('/trade-api/v2/','/trade-api/ws/v2')):raise ValueError('Invalid API path')
        timestamp=str(int(time.time()*1000));message=(timestamp+method+path.split('?')[0]).encode()
        if isinstance(self.key,ed25519.Ed25519PrivateKey):signature=self.key.sign(message)
        else:signature=self.key.sign(message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        return {'KALSHI-ACCESS-KEY':self.identifier,'KALSHI-ACCESS-TIMESTAMP':timestamp,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(signature).decode()}

def encrypt_credentials(key,key_id,pem):
    signer=DemoSigner(key_id,pem)
    canonical=signer.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    return Fernet(key.encode()).encrypt(json.dumps(dict(key_id=signer.identifier,pem=canonical)).encode()).decode()

def credentials(store,env):
    if env.get('KALSHI_DEMO_API_KEY_ID') and env.get('KALSHI_DEMO_PRIVATE_KEY_PEM'):
        return DemoSigner(env['KALSHI_DEMO_API_KEY_ID'],env['KALSHI_DEMO_PRIVATE_KEY_PEM'])
    row=store.get('credentials')
    if not row or not env.get('DEMO_VAULT_KEY'):return None
    data=json.loads(Fernet(env['DEMO_VAULT_KEY'].encode()).decrypt(row['progress']['encrypted'].encode()))
    return DemoSigner(data['key_id'],data['pem'])

class Exchange:
    root=ROOT
    def __init__(self,signer,*,client=None,guard=lambda:None):
        self.signer,self.guard=signer,guard
        self.client=client or httpx.Client(timeout=httpx.Timeout(8,connect=5),follow_redirects=False,
            limits=httpx.Limits(max_connections=2,max_keepalive_connections=2))
        self.next_read=0;self.next_write=0;self.reads=0;self.writes=0
        self.buckets={};self.endpoint_costs=[];self.default_cost=10.;self.max_entry_batch=1;self.next_limits=0
        # Optional Demo-worker callback: process the already-received WS buffer
        # between REST reads. Never called for writes or from a background thread.
        self.before_read=None
    def close(self):self.client.close()
    def market_activity_call(self,method,path,*,params=None):
        """Credential-free, read-only public activity reference. Never orders."""
        if method!='GET' or not (path in ('/markets','/markets/trades') or re.fullmatch(r'/markets/[A-Za-z0-9-]{1,128}/orderbook',path)):
            raise ValueError('Invalid public activity route')
        if getattr(self,'next_activity_read',0)-time.monotonic()>1:
            raise ExchangeFailure('activity_rate_limited')
        while time.monotonic()<getattr(self,'next_activity_read',0):
            if self.before_read:self.before_read()
            time.sleep(min(.1,max(0,self.next_activity_read-time.monotonic())))
        if self.before_read:self.before_read()
        self.next_activity_read=time.monotonic()+.35
        try:
            with self.client.stream('GET',PUBLIC_ACTIVITY_ROOT+PATH+path,params=params) as response:
                if response.status_code==429:
                    self.next_activity_read=time.monotonic()+30
                    raise ExchangeFailure('activity_rate_limited')
                if response.status_code!=200:raise ExchangeFailure('activity_unavailable',status=response.status_code)
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>1048576:raise ExchangeFailure('response_too_large')
                result=json.loads(data)
                if not isinstance(result,dict):raise ExchangeFailure('invalid_page')
                return result
        except (httpx.HTTPError,ValueError):raise ExchangeFailure('activity_unavailable') from None
    def refresh_limits(self):
        """Use authenticated budgets; failed/unknown contracts retain slow mode."""
        from .pacing import Bucket,positive
        self.next_limits=time.monotonic()+300
        try:
            limits=self.call('GET','/account/limits')
            costs=self.call('GET','/account/endpoint_costs')
            default=positive(costs['default_cost']);rows=costs['endpoint_costs']
            if not isinstance(rows,list) or len(rows)>500:raise ValueError()
            parsed=[]
            for row in rows:
                path=row['path'];method=row['method']
                if not isinstance(path,str) or len(path)>300 or method not in ('GET','POST','PUT','DELETE','PATCH'):raise ValueError()
                if path.startswith(PATH):path=path[len(PATH):]
                pattern=re.sub(r'\\\{[^{}]+\\\}',r'[^/]+',re.escape(path))
                parsed.append((method,re.compile('^'+pattern+'$'),positive(row['cost'])))
            buckets={}
            for key in ('read','write'):
                # Leave headroom for manual activity and other account clients.
                buckets[key]=Bucket(positive(limits[key]['refill_rate'])*.8,positive(limits[key]['bucket_capacity'])*.8)
            tier=limits.get('usage_tier','unknown')
            if not isinstance(tier,str) or not re.fullmatch('[a-z_]{1,30}',tier):raise ValueError()
            balance_rate=5 if tier in ('premier','prime','institutional') else 1
            buckets['balance']=Bucket(balance_rate*.8,1)
            self.buckets=buckets;self.endpoint_costs=parsed;self.default_cost=default
            cost=self.request_cost('POST','/portfolio/events/orders/batched')
            if min(buckets['read'].capacity,buckets['write'].capacity)<max(default,cost):raise ValueError()
            self.max_entry_batch=max(1,min(64,int(buckets['write'].capacity/cost)))
            print(json.dumps(dict(event='demo_api_limits',verified=True,tier=tier,
                read_tokens_per_second=buckets['read'].rate,write_tokens_per_second=buckets['write'].rate,
                default_cost=default,batch_item_cost=cost,max_entry_batch=self.max_entry_batch)),flush=True)
            return True
        except (ExchangeFailure,KeyError,TypeError,ValueError,OverflowError):
            self.buckets={};self.max_entry_batch=1
            print(json.dumps(dict(event='demo_api_limits',verified=False,max_entry_batch=1)),flush=True)
            return False
    def request_cost(self,method,path):
        return next((cost for verb,pattern,cost in self.endpoint_costs if verb==method and pattern.fullmatch(path)),self.default_cost)
    def entry_batch_capacity(self):
        if not self.buckets:return 1
        if self.next_write>time.monotonic():return 0
        cost=self.request_cost('POST','/portfolio/events/orders/batched')
        return min(self.max_entry_batch,int(self.buckets['write'].available()/cost))
    def call(self,method,path,*,params=None,body=None):
        if not path.startswith('/') or '..' in path or '://' in path:raise ValueError('Invalid path')
        write=method!='GET';now=time.monotonic();next_at=self.next_write if write else self.next_read
        bucket=self.buckets.get('write' if write else 'balance' if path=='/portfolio/balance' else 'read')
        cost=1 if path=='/portfolio/balance' else self.request_cost(method,path)
        if write and path.endswith('/batched'):cost*=len((body or {}).get('orders',[]))
        if bucket and cost>bucket.capacity:raise ExchangeFailure('request_budget')
        if not write:
            poll=self.before_read
            if poll is not None:poll()
            # Don't let a 250 ms read pace or a provider-imposed 5-second
            # cooldown strand market events. The REST request itself stays
            # synchronous and no order write may be replayed by this hook.
            last_poll=time.monotonic()
            while True:
                remaining=max(next_at-time.monotonic(),bucket.delay(cost) if bucket else 0)
                if remaining<=0:break
                if poll is not None and time.monotonic()-last_poll>=.2:
                    poll();last_poll=time.monotonic()
                remaining=max(next_at-time.monotonic(),bucket.delay(cost) if bucket else 0)
                if remaining<=0:break
                time.sleep(min(.1,remaining))
        elif bucket:
            while True:
                remaining=max(next_at-time.monotonic(),bucket.delay(cost) if bucket else 0)
                if remaining<=0:break
                time.sleep(min(.1,remaining))
        elif next_at>now:time.sleep(min(5,next_at-now))
        if bucket:bucket.take(cost)
        if write:self.guard();self.next_write=time.monotonic()+(0 if bucket else 1);self.writes+=1
        else:self.next_read=time.monotonic()+(0 if bucket else .25);self.reads+=1
        try:
            with self.client.stream(method,self.root+PATH+path,params=params,json=body,headers=self.signer.headers(method,PATH+path)) as response:
                if response.status_code==429:
                    operation=path if path in ('/portfolio/balance','/portfolio/positions','/portfolio/orders','/markets','/account/limits','/account/endpoint_costs') else 'other'
                    print(json.dumps(dict(event='demo_rate_limit',method=method,operation=operation)),flush=True)
                    self.next_read=self.next_write=time.monotonic()+5
                    raise ExchangeFailure('rate_limited')
                if not 200<=response.status_code<300:
                    # Bounded parsing: expose only a token code and fixed reason labels,
                    # never raw provider messages, credentials or response bodies.
                    raw=bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk[:max(0,8192-len(raw))])
                        if len(raw)>=8192:break
                    try:
                        info=json.loads(raw);info=info.get('error',info)
                        token=info.get('code')
                        provider=token if isinstance(token,str) and re.fullmatch(r'[a-zA-Z0-9_:-]{1,80}',token) else None
                        detail=' '.join(str(info.get(k,'')) for k in ('code','message','details')).lower()
                        reason=next((name for name,words in [('post_only',('post only','post_only','post-only')),('price_tick',('tick','price increment')),('expiration',('expiration','expired')),('balance',('balance','buying power','funds')),('routing',('shard','exchange_index')),('market',('market','ticker')),('quantity',('count','quantity'))] if any(w in detail for w in words)),None)
                    except (ValueError,AttributeError):provider=reason=None
                    raise ExchangeFailure('authentication' if response.status_code in (401,403) else 'exchange_rejected',write and response.status_code>=500,status=response.status_code,provider_code=provider,reason=reason)
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>1048576:raise ExchangeFailure('response_too_large',write)
                return json.loads(data)
        except (httpx.HTTPError,ValueError):raise ExchangeFailure('connection',write) from None
    def pages(self,path,key,**params):
        cursor=None
        for _ in range(20):
            page=self.call('GET',path,params=dict(params,limit=200,**({'cursor':cursor} if cursor else {})))
            values=page.get(key)
            if not isinstance(values,list) or len(values)>200:raise ExchangeFailure('invalid_page')
            yield from values
            following=page.get('cursor')
            if not following:return
            if following==cursor:raise ExchangeFailure('invalid_cursor')
            cursor=following
        raise ExchangeFailure('reconciliation_capacity')
    def submit(self,intent):
        from .engine import wire_order
        return self.call('POST','/portfolio/events/orders',body=wire_order(intent))
    def submit_batch(self,intents):
        from .engine import wire_order
        if not 1<=len(intents)<=self.max_entry_batch:raise ExchangeFailure('batch_capacity')
        return self.call('POST','/portfolio/events/orders/batched',body=dict(orders=[wire_order(i) for i in intents]))
    def cancel(self,order_id,ticker):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',order_id):raise ValueError('Invalid order ID')
        return self.call('DELETE','/portfolio/events/orders/'+order_id,params=dict(market_ticker=ticker,exchange_index=-1))

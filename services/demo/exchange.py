"""Demo-only V2 transport. Fixed destinations, bounded responses, no write retries."""
import base64,json,time,re
import httpx
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.fernet import Fernet

ROOT='https://external-api.demo.kalshi.co'
WS='wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2'
PATH='/trade-api/v2'
class ExchangeFailure(Exception):
    def __init__(self,code,ambiguous=False):self.code,self.ambiguous=code,ambiguous

class DemoSigner:
    def __init__(self,key_id,pem):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',key_id):raise ValueError('Invalid demo key identifier')
        self.key=serialization.load_pem_private_key(pem.encode(),None)
        if not isinstance(self.key,rsa.RSAPrivateKey) or self.key.key_size<2048:raise ValueError('A demo RSA key is required')
        self.identifier=key_id
    def headers(self,method,path):
        if not path.startswith(('/trade-api/v2/','/trade-api/ws/v2')):raise ValueError('Invalid API path')
        timestamp=str(int(time.time()*1000))
        signature=self.key.sign((timestamp+method+path.split('?')[0]).encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        return {'KALSHI-ACCESS-KEY':self.identifier,'KALSHI-ACCESS-TIMESTAMP':timestamp,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(signature).decode()}

def encrypt_credentials(key,key_id,pem):
    DemoSigner(key_id,pem)
    return Fernet(key.encode()).encrypt(json.dumps(dict(key_id=key_id,pem=pem)).encode()).decode()

def credentials(store,env):
    if env.get('KALSHI_DEMO_API_KEY_ID') and env.get('KALSHI_DEMO_PRIVATE_KEY_PEM'):
        return DemoSigner(env['KALSHI_DEMO_API_KEY_ID'],env['KALSHI_DEMO_PRIVATE_KEY_PEM'])
    row=store.get('credentials')
    if not row or not env.get('DEMO_VAULT_KEY'):return None
    data=json.loads(Fernet(env['DEMO_VAULT_KEY'].encode()).decrypt(row['progress']['encrypted'].encode()))
    return DemoSigner(data['key_id'],data['pem'])

class Exchange:
    def __init__(self,signer,*,client=None,guard=lambda:None):
        self.signer,self.guard=signer,guard
        self.client=client or httpx.Client(timeout=httpx.Timeout(8,connect=5),follow_redirects=False,
            limits=httpx.Limits(max_connections=2,max_keepalive_connections=2))
        self.next_read=0;self.next_write=0;self.reads=0;self.writes=0
    def close(self):self.client.close()
    def call(self,method,path,*,params=None,body=None):
        if not path.startswith('/') or '..' in path or '://' in path:raise ValueError('Invalid path')
        write=method!='GET';now=time.monotonic();next_at=self.next_write if write else self.next_read
        if next_at>now:time.sleep(min(5,next_at-now))
        if write:self.guard();self.next_write=time.monotonic()+1;self.writes+=1
        else:self.next_read=time.monotonic()+.25;self.reads+=1
        try:
            with self.client.stream(method,ROOT+PATH+path,params=params,json=body,headers=self.signer.headers(method,PATH+path)) as response:
                if response.status_code==429:
                    self.next_read=self.next_write=time.monotonic()+5
                    raise ExchangeFailure('rate_limited')
                if not 200<=response.status_code<300:raise ExchangeFailure('authentication' if response.status_code in (401,403) else 'exchange_rejected',write and response.status_code>=500)
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
    def cancel(self,order_id):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',order_id):raise ValueError('Invalid order ID')
        return self.call('DELETE','/portfolio/events/orders/'+order_id)

"""Demo-only V2 transport. Fixed destinations, bounded responses, no write retries."""
import base64,json,time,re
import httpx
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding,ed25519
from cryptography.fernet import Fernet

ROOT='https://external-api.demo.kalshi.co'
WS='wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2'
PATH='/trade-api/v2'
class ExchangeFailure(Exception):
    def __init__(self,code,ambiguous=False):self.code,self.ambiguous=code,ambiguous

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

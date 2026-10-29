"""Explicit read-only Kalshi signing. No order endpoint can be signed here."""
import base64,re,time
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import ed25519,rsa,padding


class ReadSigner:
    def __init__(self,key_id,pem,*,clock=time.time):
        if not isinstance(key_id,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,128}',key_id):raise ValueError('Invalid Kalshi key ID')
        try:
            key=serialization.load_pem_private_key(pem.encode(),password=None)
            if not isinstance(key,(ed25519.Ed25519PrivateKey,rsa.RSAPrivateKey)):raise ValueError()
            if isinstance(key,rsa.RSAPrivateKey) and key.key_size<2048:raise ValueError()
        except Exception:raise ValueError('Invalid Kalshi private key') from None
        self.key_id,self._key,self.clock=key_id,key,clock

    def headers(self,method,path):
        path=path.split('?')[0]
        if method!='GET' or not path.startswith('/trade-api/v2/') or not (
            path.startswith(('/trade-api/v2/markets','/trade-api/v2/historical/','/trade-api/v2/series/'))
            or path in ('/trade-api/v2/account/limits','/trade-api/v2/account/endpoint_costs')):
            raise ValueError('Only market-data and allowance reads may be signed')
        timestamp=str(int(self.clock()*1000));message=(timestamp+method+path).encode()
        if isinstance(self._key,ed25519.Ed25519PrivateKey):signature=self._key.sign(message)
        else:signature=self._key.sign(message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        return {'KALSHI-ACCESS-KEY':self.key_id,'KALSHI-ACCESS-TIMESTAMP':timestamp,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(signature).decode()}


def signer_from_env(env):
    identifier,pem=env.get('KALSHI_API_KEY_ID',''),env.get('KALSHI_PRIVATE_KEY_PEM','')
    if not identifier and not pem:return None
    if not identifier or not pem:raise ValueError('Configure both Kalshi key ID and private key')
    return ReadSigner(identifier,pem)

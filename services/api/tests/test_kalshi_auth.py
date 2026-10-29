import base64,unittest
import httpx
from test_kalshi import reply
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import ed25519,rsa,padding
from services.research.kalshi_auth import ReadSigner,signer_from_env
from services.research.kalshi import KalshiInventory


class SigningTests(unittest.TestCase):
    def signer(self,key):
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        return ReadSigner('test-key',pem,clock=lambda:123.456)
    def test_both_key_types_sign_get_path_without_query_and_reject_orders(self):
        for key in (ed25519.Ed25519PrivateKey.generate(),rsa.generate_private_key(public_exponent=65537,key_size=2048)):
            signer=self.signer(key);headers=signer.headers('GET','/trade-api/v2/markets?cursor=abc')
            signature=base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']);message=b'123456GET/trade-api/v2/markets'
            if isinstance(key,ed25519.Ed25519PrivateKey):key.public_key().verify(signature,message)
            else:key.public_key().verify(signature,message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
            for method,path in (('POST','/trade-api/v2/markets'),('GET','/trade-api/v2/portfolio/orders')):
                with self.assertRaises(ValueError):signer.headers(method,path)
    def test_limits_and_endpoint_costs_determine_read_allowance(self):
        seen=[]
        def handler(request):
            seen.append(request);self.assertIn('KALSHI-ACCESS-SIGNATURE',request.headers)
            return reply(payload={'read':{'refill_rate':200},'usage_tier':'basic'} if request.url.path.endswith('/limits') else {'default_cost':10,'endpoint_costs':[]})
        with KalshiInventory(signer=self.signer(ed25519.Ed25519PrivateKey.generate()),transport=httpx.MockTransport(handler)) as provider:
            self.assertEqual(provider.account_allowance(),dict(usage_tier='basic',requests_per_second=20,burst_capacity=20))
        self.assertEqual(len(seen),2)
    def test_incomplete_credentials_fail_closed(self):
        self.assertIsNone(signer_from_env({}))
        with self.assertRaises(ValueError):signer_from_env({'KALSHI_API_KEY_ID':'test-key'})

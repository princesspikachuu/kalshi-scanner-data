"""Exercise Google's actual signature verifier with a local test certificate."""
import datetime as dt
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt,jwt
from services.api.auth_policy import verify_google_login,LoginRejected


class GoogleSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'local-test')]);now=dt.datetime.now(dt.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(cls.key.public_key()).serial_number(1).not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=1)).sign(cls.key,hashes.SHA256())
        cls.cert=cert.public_bytes(serialization.Encoding.PEM).decode()
        private=cls.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        cls.signer=crypt.RSASigner.from_string(private,key_id='local-key')
    def token(self,**changes):
        claims={'iss':'https://accounts.google.com','aud':'test-client','sub':'owner','email':'owner@gmail.com','email_verified':True,
                'iat':int(time.time())-1,'exp':int(time.time())+300,'nonce':'n'*43}
        claims.update(changes)
        return jwt.encode(self.signer,claims).decode()
    def verify(self,token):
        response=SimpleNamespace(status=200,data=json.dumps({'local-key':self.cert}).encode())
        with patch('services.api.auth_policy._google_request',return_value=lambda *a,**kw:response):
            return verify_google_login(credential=token,client_id='test-client',expected_nonce='n'*43)
    def test_actual_sdk_accepts_valid_signature_and_claims(self):
        identity=self.verify(self.token())
        self.assertEqual(identity.subject,'owner');self.assertTrue(identity.email_authoritative)
    def test_actual_sdk_rejects_wrong_audience_expiry_and_tampered_signature(self):
        for token in [self.token(aud='another-client'),self.token(exp=int(time.time())-60),self.token()[:-20]+'x'*20]:
            with self.subTest(token_kind=token[:12]),self.assertRaises(LoginRejected):self.verify(token)
    def test_third_party_email_cannot_bootstrap_by_email_alone(self):
        self.assertFalse(self.verify(self.token(email='owner@third-party.test')).email_authoritative)

if __name__=='__main__':unittest.main()

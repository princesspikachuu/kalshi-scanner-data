import unittest
from collections import defaultdict
from fastapi.testclient import TestClient
from services.api.app import create_app,SESSION,CSRF
from services.api.auth_policy import GoogleIdentity,require_owner
from services.api.config import Settings


class MemoryStore:
    """Test double only; production always uses PostgresStore."""
    def __init__(self):self.challenges={};self.sessions={};self.counts=defaultdict(int)
    def ready(self):return True
    def allow(self,key,n):self.counts[key]+=1;return self.counts[key]<=n
    def challenge(self,t,c,n):self.challenges[t]=(c,n)
    def consume(self,t,c,n):
        if self.challenges.get(t)!=(c,n):return False
        del self.challenges[t];return True
    def session(self,identity,material,settings,previous_hash=None):
        require_owner(identity,settings.owner_subject)
        if previous_hash:self.sessions.pop(previous_hash,None)
        self.sessions[material['token_hash']]={'csrf_hash':material['csrf_hash'],'display_email':identity.email}
    def current(self,t):return self.sessions.get(t)
    def revoke(self,t):self.sessions.pop(t,None)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.store=MemoryStore();self.calls=0
        self.settings=Settings('https://app.test','client','postgresql://unused','x'*32,owner_subject='owner')
        def verifier(**kwargs):self.calls+=1;return GoogleIdentity('owner','owner@gmail.com',True)
        self.client=TestClient(create_app(self.settings,self.store,verifier),base_url='https://app.test',
                               headers={'X-Pocket-Proxy':'x'*32,'Origin':'https://app.test'})
    def tearDown(self):self.client.close()
    def challenge(self):return self.client.get('/auth/challenge').json()
    def login(self):
        challenge=self.challenge()
        return self.client.post('/auth/google',json={'credential':'opaque-token','nonce':challenge['nonce'],'csrf_token':challenge['csrf_token']})

    def test_login_session_and_csrf_logout(self):
        r=self.login();self.assertEqual(r.status_code,200)
        cookie=r.headers.get_list('set-cookie')[0]
        self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=strict',cookie)
        self.assertNotIn('Domain=',cookie)
        self.assertEqual(self.client.get('/auth/me').json()['email'],'owner@gmail.com')
        csrf=self.client.cookies[CSRF]
        self.assertEqual(self.client.post('/auth/logout',headers={'x-csrf-token':csrf}).status_code,204)
        self.assertEqual(self.client.get('/auth/me').status_code,401)
        self.assertFalse(self.store.sessions)

    def test_replayed_challenge_is_rejected_before_google_verification(self):
        c=self.challenge();body={'credential':'opaque-token','nonce':c['nonce'],'csrf_token':c['csrf_token']}
        cookies=dict(self.client.cookies)
        self.assertEqual(self.client.post('/auth/google',json=body).status_code,200)
        self.client.cookies.update(cookies)
        self.assertEqual(self.client.post('/auth/google',json=body).status_code,401)
        self.assertEqual(self.calls,1)

    def test_cross_origin_and_mismatched_csrf_never_call_google(self):
        c=self.challenge();body={'credential':'opaque-token','nonce':c['nonce'],'csrf_token':c['csrf_token']}
        self.assertEqual(self.client.post('/auth/google',json=body,headers={'Origin':'https://attacker.test'}).status_code,403)
        body['csrf_token']='z'*43
        self.assertEqual(self.client.post('/auth/google',json=body).status_code,403)
        self.assertEqual(self.calls,0)

    def test_direct_backend_requests_cannot_bypass_proxy_or_session(self):
        self.assertEqual(self.client.get('/auth/me',headers={'x-pocket-proxy':'wrong'}).status_code,403)
        self.assertEqual(self.client.get('/auth/me').status_code,401)
        self.assertEqual(self.client.get('/health/live',headers={'x-pocket-proxy':''}).status_code,200)

    def test_limits_and_validation_do_not_echo_credentials(self):
        response=self.client.post('/auth/google',content=b'x'*20481,headers={'content-type':'application/json'})
        self.assertEqual(response.status_code,413)
        r=self.client.post('/auth/google',json={'credential':123,'nonce':'private-sentinel','csrf_token':'private-sentinel'})
        self.assertEqual(r.status_code,422);self.assertNotIn('private-sentinel',r.text)
        for i in range(30):self.assertEqual(self.client.get('/auth/challenge').status_code,200)
        self.assertEqual(self.client.get('/auth/challenge').status_code,429)

    def test_bad_logout_csrf_does_not_revoke_owner_session(self):
        self.login()
        self.assertEqual(self.client.post('/auth/logout',headers={'x-csrf-token':'z'*43}).status_code,403)
        self.assertEqual(self.client.get('/auth/me').status_code,200)

    def test_relogin_rotates_and_revokes_previous_session(self):
        self.login();first=self.client.cookies[SESSION]
        self.login();second=self.client.cookies[SESSION]
        self.assertNotEqual(first,second);self.assertEqual(len(self.store.sessions),1)
        self.client.cookies.clear();self.client.cookies.set(SESSION,first)
        self.assertEqual(self.client.get('/auth/me').status_code,401)

    def test_invalid_configuration_fails_closed_without_exposing_secrets(self):
        with self.assertRaises(ValueError):Settings('http://app.test','client','secret-dsn','x'*32,owner_subject='owner')
        with self.assertRaises(ValueError):Settings('https://app.test','client','secret-dsn','x'*32)
        self.assertNotIn('postgresql://unused',repr(self.settings))


if __name__=='__main__':unittest.main()

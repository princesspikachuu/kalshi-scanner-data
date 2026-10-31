"""Real PostgreSQL integration. Runs only against an explicit disposable test DB."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from services.api.app import create_app,CSRF
from services.api.auth_policy import GoogleIdentity,LoginRejected,new_session_material
from services.api.config import Settings
from services.api.manage import migrate
from services.api.store import PostgresStore

URL=os.environ.get('POCKET_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'Set POCKET_TEST_DATABASE_URL to a disposable pocket_test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Integration tests require the disposable pocket_test database')
        migrate(URL);migrate(URL)
        cls.store=PostgresStore(URL);cls.store.open()
        cls.settings=Settings('https://app.test','client',URL,'x'*32,owner_email='owner@gmail.com')
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('TRUNCATE owner_session,owner_account,login_challenge,login_rate CASCADE')
    def test_migrations_are_idempotent_and_ready(self):
        self.assertTrue(self.store.ready())
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n'],9)
    def test_challenge_consumption_is_atomic_under_concurrency(self):
        self.store.challenge('a'*64,'b'*64,'c'*64)
        with ThreadPoolExecutor(max_workers=8) as executor:
            result=list(executor.map(lambda _:self.store.consume('a'*64,'b'*64,'c'*64),range(8)))
        self.assertEqual(sum(result),1)
    def test_owner_bootstrap_is_explicit_and_bound_to_subject(self):
        with self.assertRaises(LoginRejected):
            self.store.session(GoogleIdentity('bad','attacker@gmail.com',True),new_session_material(),self.settings)
        owner=GoogleIdentity('owner','owner@gmail.com',True)
        self.store.session(owner,new_session_material(),self.settings)
        with self.assertRaises(LoginRejected):
            self.store.session(GoogleIdentity('another-subject','owner@gmail.com',True),new_session_material(),self.settings)
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT google_subject FROM owner_account').fetchone()['google_subject'],'owner')
            self.assertEqual(c.execute('SELECT count(*) AS n FROM owner_session').fetchone()['n'],1)
    def test_expired_sessions_and_revocation_fail_closed(self):
        material=new_session_material()
        self.store.session(GoogleIdentity('owner','owner@gmail.com',True),material,self.settings)
        self.assertIsNotNone(self.store.current(material['token_hash']))
        with self.store.pool.connection() as c:
            c.execute("UPDATE owner_session SET created_at=now()-interval '1 day',expires_at=now()-interval '1 second'")
        self.assertIsNone(self.store.current(material['token_hash']))
        material=new_session_material()
        self.store.session(GoogleIdentity('owner','owner@gmail.com',True),material,self.settings)
        self.store.revoke(material['token_hash'])
        self.assertIsNone(self.store.current(material['token_hash']))
    def test_full_http_login_and_logout_use_database_state(self):
        with TestClient(create_app(self.settings,self.store,lambda **_:GoogleIdentity('owner','owner@gmail.com',True)),
                        base_url='https://app.test',headers={'X-Pocket-Proxy':'x'*32,'Origin':'https://app.test'}) as client:
            challenge=client.get('/auth/challenge').json()
            r=client.post('/auth/google',json={'credential':'opaque-test-token','nonce':challenge['nonce'],'csrf_token':challenge['csrf_token']})
            self.assertEqual(r.status_code,200)
            self.assertEqual(client.get('/auth/me').status_code,200)
            csrf=client.cookies[CSRF]
            self.assertEqual(client.post('/auth/logout',headers={'x-csrf-token':csrf}).status_code,204)
            self.assertEqual(client.get('/auth/me').status_code,401)
    def test_database_rate_budget_is_shared(self):
        for _ in range(3):self.assertTrue(self.store.allow('test',3))
        self.assertFalse(self.store.allow('test',3))

if __name__=='__main__':unittest.main()

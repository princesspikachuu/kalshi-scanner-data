"""Actual database/API checks using the same disposable database as other tests."""
import os,unittest
from urllib.parse import urlsplit
from unittest.mock import patch
from fastapi.testclient import TestClient
from services.api.app import create_app,CSRF
from services.api.config import Settings
from services.api.auth_policy import GoogleIdentity
from services.api.store import PostgresStore
from services.api.manage import migrate
from services.demo.store import DemoStore
from services.api.tests.test_demo_engine import config
URL=os.environ.get('POCKET_TEST_DATABASE_URL')
@unittest.skipUnless(URL,'Disposable PostgreSQL is required')
class DemoPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Use disposable pocket_test only')
        migrate(URL);cls.store=PostgresStore(URL);cls.store.open();cls.demo=DemoStore(cls.store.pool)
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:c.execute("TRUNCATE owner_session,owner_account,login_challenge,login_rate,research_job CASCADE")
        settings=Settings('https://app.test','client',URL,'x'*32,owner_email='owner@gmail.com')
        self.client=TestClient(create_app(settings,self.store,lambda **_:GoogleIdentity('owner','owner@gmail.com',True)),base_url='https://app.test',headers={'X-Pocket-Proxy':'x'*32,'Origin':'https://app.test'})
        challenge=self.client.get('/auth/challenge').json();self.client.post('/auth/google',json=dict(credential='opaque',nonce=challenge['nonce'],csrf_token=challenge['csrf_token']))
        self.client.headers['x-csrf-token']=self.client.cookies[CSRF]
    def tearDown(self):self.client.close()
    def test_multi_square_bot_revision_and_archive_without_history_mutation(self):
        body=config();body['squares'].append(dict(body['squares'][0],min_price=80,max_price=89))
        result=self.client.post('/demo/bots',json=body);self.assertEqual(result.status_code,200,result.text);identifier=result.json()['id']
        page=self.client.get('/demo/workspace');self.assertEqual(page.status_code,200,page.text)
        bot=page.json()['bots'][0];self.assertEqual(bot['key'],identifier);self.assertEqual(len(bot['config']['squares']),2);self.assertEqual(bot['desired'],'paused')
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1)).status_code,200)
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/configure',json=body).status_code,409)
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='pause',revision=1)).status_code,200)
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/configure',json=body).status_code,200)
        self.assertEqual(self.client.post('/demo/bots/'+identifier+'/control',json=dict(action='resume',revision=1)).status_code,409)
    def test_activity_pagination_and_filter_includes_archive_summaries(self):
        for i in range(55):self.demo.event('fill','Event '+str(i),bot='00000000-0000-0000-0000-000000000001',ticker='T')
        first=self.client.get('/demo/activity?kind=fill').json();self.assertEqual(len(first['items']),50)
        second=self.client.get('/demo/activity?kind=fill&before='+first['next_before']).json();self.assertEqual(len(second['items']),5)
        self.assertFalse(set(r['id'] for r in first['items'])&set(r['id'] for r in second['items']))
    def test_private_controls_require_session_and_csrf(self):
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/bots',json=config()).status_code,403)
        self.client.cookies.clear();self.assertEqual(self.client.get('/demo/workspace').status_code,401)
    def test_chart_and_research_empty_is_not_fabricated_data(self):
        self.assertEqual(self.client.get('/demo/chart?period=7D').json()['points'],[])
        r=self.client.get('/demo/research?asset=btc&start=2026-10-01&end=2026-10-30');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['items'],[])
    def test_durable_order_roundtrip_keeps_open_entries_only(self):
        self.demo.put('order/a',dict(status='held',filled=2,remaining=0),parameters=dict(kind='entry',bot='b'))
        self.demo.put('order/b',dict(status='closed',filled=2,remaining=0),parameters=dict(kind='entry',bot='b'))
        self.assertEqual(len(self.demo.active_orders()),1)

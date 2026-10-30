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
    def test_minimum_bid_roundtrip_validation_and_existing_config_default(self):
        body=config(minimum_cents=60,maximum_cents=96)
        response=self.client.post('/demo/bots',json=body)
        self.assertEqual(response.status_code,200,response.text)
        saved=self.client.get('/demo/workspace').json()['bots'][0]['config']
        self.assertEqual(saved['minimum_cents'],60);self.assertEqual(saved['maximum_cents'],96)
        body['minimum_cents']=97
        self.assertEqual(self.client.post('/demo/bots',json=body).status_code,422)
        body.pop('minimum_cents')
        response=self.client.post('/demo/bots',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(self.demo.get('bot/'+response.json()['id'])['parameters']['config']['minimum_cents'])
    def test_reset_is_idempotent_pauses_bots_blocks_resume_and_preserves_history(self):
        from uuid import uuid4
        from services.demo.reset import archive_and_clone
        created=self.client.post('/demo/bots',json=config()).json()['id']
        self.client.post('/demo/bots/'+created+'/control',json=dict(action='resume',revision=1))
        self.demo.event('fill','Existing historical execution')
        history=self.demo.rows('event/',100)
        body=dict(request_id=str(uuid4()),fresh_bots=True,target_balance_cents=100000)
        response=self.client.post('/demo/reset',json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.post('/demo/reset',json=body).status_code,200)
        self.assertEqual(self.client.post('/demo/bots/'+created+'/control',json=dict(action='resume',revision=1)).status_code,409)
        page=self.client.get('/demo/workspace').json();self.assertEqual(page['bots'][0]['desired'],'paused')
        self.assertEqual(page['reset']['target_balance_cents'],100000)
        reset=self.demo.get('reset');archive_and_clone(self.demo,reset['parameters']);archive_and_clone(self.demo,reset['parameters'])
        bots=self.demo.rows('bot/',100);self.assertEqual(len(bots),2)
        old=self.demo.get('bot/'+created);self.assertTrue(old['progress']['archived'])
        fresh=next(b for b in bots if b['idempotency_key']!='demo/bot/'+created)
        self.assertEqual(fresh['progress']['desired'],'paused');self.assertEqual(fresh['parameters']['config']['squares'],config()['squares'])
        for prior in history:self.assertEqual(self.demo.get(prior['idempotency_key'][5:])['progress'],prior['progress'])
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/reset',json=body).status_code,403)
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
    def test_ask_policy_upgrade_uses_saved_trigger_evidence_and_preserves_completed_sales(self):
        import threading
        from services.demo.runtime import Worker
        order=dict(client_id='entry',kind='entry',bot='bot',revision=1,ticker='T',side='yes',square=0,price=96,quantity=2,sold=1,close=1800000000,exit_triggered=True,exit_ceiling_cents=2)
        self.demo.put('order/entry',dict(status='held',filled=2,remaining=0),parameters=order)
        self.demo.put('order/completed',dict(status='closed',filled=1,remaining=0),parameters=dict(client_id='completed',kind='exit',parent='entry',bot='bot',ticker='T',side='yes',price=2,quantity=1))
        self.demo.event('exit_trigger','Previous bid rule',bot='bot',details=dict(client_id='entry',side='yes',threshold=55,quote=dict(bid=1,ask=99)))
        completed=self.demo.get('order/completed')
        worker=Worker(self.demo,object(),threading.Event(),lambda:None);worker.orders=self.demo.active_orders();worker.recovered=True
        self.assertFalse(worker.upgrade_legacy_exits())
        params=self.demo.get('order/entry')['parameters']
        self.assertFalse(params['exit_triggered']);self.assertEqual(params['exit_reference'],'ask');self.assertNotIn('exit_ceiling_cents',params)
        self.assertEqual(self.demo.get('order/completed')['progress'],completed['progress'])
        self.assertEqual(self.demo.get('order/completed')['parameters'],completed['parameters'])
    def test_workspace_returns_actionable_issue_evidence(self):
        import time
        self.demo.put('health',dict(state='attention',message='Saved order not returned',at=time.time(),issue=dict(summary='Saved order not returned',action='Review Activity',control='retry',phase='reconciliation',market='T',order_id='one',code='not_found')))
        result=self.client.get('/demo/workspace');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['health']['issue']['order_id'],'one')
        self.assertEqual(result.json()['health']['issue']['action'],'Review Activity')

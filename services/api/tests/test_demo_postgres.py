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
    def test_reset_archives_and_copies_without_funding_or_order_mutation(self):
        from uuid import uuid4
        created=self.client.post('/demo/bots',json=config()).json()['id']
        self.client.post('/demo/bots/'+created+'/control',json=dict(action='resume',revision=1))
        self.demo.event('fill','Existing historical execution')
        history=self.demo.rows('event/',100)
        self.demo.put('account',dict(cash_cents=53627,equity_cents=53627))
        self.demo.put('order/unsettled',dict(status='held',filled=1,remaining=0),parameters=dict(kind='entry',bot=created,ticker='T'))
        prior=self.demo.get('order/unsettled')
        # Old cached clients may still send these fields: neither is a gate.
        body=dict(request_id=str(uuid4()),fresh_bots=False,target_balance_cents=100000)
        response=self.client.post('/demo/reset',json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'complete')
        self.assertEqual(self.client.post('/demo/reset',json=body).status_code,200)
        bots=self.demo.rows('bot/',100);self.assertEqual(len(bots),2)
        old=self.demo.get('bot/'+created);self.assertTrue(old['progress']['archived']);self.assertEqual(old['progress']['desired'],'paused')
        fresh=next(b for b in bots if b['idempotency_key']!='demo/bot/'+created)
        self.assertEqual(fresh['progress']['desired'],'paused');self.assertEqual(fresh['parameters']['config']['squares'],config()['squares'])
        fresh_id=fresh['idempotency_key'].split('/')[-1]
        self.assertEqual(self.client.post('/demo/bots/'+fresh_id+'/control',json=dict(action='resume',revision=1)).status_code,200)
        self.assertEqual(self.demo.get('account')['progress']['cash_cents'],53627)
        self.assertEqual(self.demo.get('order/unsettled')['progress'],prior['progress'])
        self.assertEqual(self.demo.get('order/unsettled')['parameters'],prior['parameters'])
        for previous in history:self.assertEqual(self.demo.get(previous['idempotency_key'][5:])['progress'],previous['progress'])
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/reset',json=body).status_code,403)
    def test_legacy_reset_unblocks_resumes_and_reuses_existing_copies(self):
        from uuid import uuid4
        from services.demo.reset import ResetController
        from unittest.mock import MagicMock
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        self.client.post('/demo/reset',json=dict(request_id=str(uuid4())))
        reset=self.demo.get('reset');params=dict(reset['parameters'],target_balance_cents=100000)
        pending=dict(client_id='legacy-unknown-sale')
        self.demo.put('reset',dict(reset['progress'],state='awaiting_funds',pending=pending,cash_cents=100001),parameters=params)
        fresh=next(b for b in self.demo.rows('bot/',100) if not b['progress'].get('archived'))
        fresh_id=fresh['idempotency_key'].split('/')[-1]
        result=self.client.post('/demo/bulk',json=dict(action='resume',bots=[dict(id=fresh_id,revision=1)]))
        self.assertEqual(result.status_code,200,result.text)
        exchange=MagicMock();ResetController(self.demo,exchange).step(self.demo.get('reset'))
        self.assertEqual(exchange.mock_calls,[])
        self.assertEqual(self.demo.get('reset')['progress']['state'],'complete')
        self.assertEqual(self.demo.get('reset')['progress']['pending'],pending)
        self.assertEqual(len(self.demo.rows('bot/',100)),2)
        self.assertEqual(self.demo.get('bot/'+fresh_id)['progress']['desired'],'running')
        ResetController(self.demo,exchange).step(self.demo.get('reset'))
        self.assertEqual(len(self.demo.rows('bot/',100)),2)
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

    def test_per_square_performance_separates_revisions_and_reset_closures(self):
        identifier=self.client.post('/demo/bots',json=config()).json()['id']
        condition=self.demo.get('bot/'+identifier)['parameters']['config']['squares'][0]
        for name,state,params in [
            ('open',dict(status='held',filled=3,remaining=0),dict(sold=1)),
            ('closed',dict(status='closed',filled=2,remaining=0,realized_cents=35),{}),
            ('reset',dict(status='closed',filled=2,remaining=0,reset_closed=True),{}),
            ('rejected',dict(status='rejected',filled=0,remaining=0),{}),
            ('old',dict(status='closed',filled=1,remaining=0,realized_cents=-20),dict(revision=0)),
        ]:
            self.demo.put('order/'+name,state,parameters=dict(dict(bot=identifier,kind='entry',revision=1,square=0,condition=condition),**params))
        self.demo.put('order/exit',dict(status='closed',filled=1,realized_cents=999),parameters=dict(bot=identifier,kind='exit',revision=1,square=0))
        response=self.client.get('/demo/performance?bot='+identifier);self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['items'];self.assertEqual(len(rows),2)
        current=next(r for r in rows if r['revision']==1)
        self.assertEqual(current['orders'],4);self.assertEqual(current['contracts'],7)
        self.assertEqual(current['held_contracts'],2);self.assertEqual(current['scored'],1)
        self.assertEqual(current['unscored_resets'],1);self.assertEqual(current['recorded_pnl_cents'],35)
        self.assertEqual(next(r for r in rows if r['revision']==0)['recorded_pnl_cents'],-20)
        for query in ['','?bot=bad','?bot='+identifier+'&period=7D','?bot='+identifier+'&bot='+identifier]:
            self.assertEqual(self.client.get('/demo/performance'+query).status_code,422)
        self.client.cookies.clear();self.assertEqual(self.client.get('/demo/performance?bot='+identifier).status_code,401)

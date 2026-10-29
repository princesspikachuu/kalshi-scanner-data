import os,time,unittest
from uuid import uuid4
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_campaigns as fixtures
from services.api.paper import install_paper
from services.paper.worker import PaperWorker


@unittest.skipUnless(os.environ.get('POCKET_TEST_DATABASE_URL'),'Requires disposable pocket_test PostgreSQL')
class PaperRouteTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CampaignPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.CampaignPostgresTests.tearDownClass.__func__)
    make_worker=fixtures.CampaignPostgresTests.make_worker
    create=fixtures.CampaignPostgresTests.create
    drive=fixtures.CampaignPostgresTests.drive
    def setUp(self):
        fixtures.CampaignPostgresTests.setUp(self)
        def auth(request):
            if request.headers.get('x-test-owner')!='owner':raise HTTPException(401,'Sign in required')
        def mutate(request):
            auth(request)
            if request.headers.get('x-test-csrf')!='csrf':raise HTTPException(403,'Request rejected')
        app=FastAPI();install_paper(app,auth,mutate,self.db.pool);self.client=TestClient(app)
        self.headers={'x-test-owner':'owner','x-test-csrf':'csrf'}
    def test_owner_csrf_strategy_snapshot_idempotent_replay_and_persisted_results(self):
        identifier=self.create(end='2026-10-25');self.drive(identifier)
        self.assertEqual(self.client.get('/paper/workspace').status_code,401)
        strategy=dict(name='Test',asset='btc',minutes=[15,10,5,3,1],min_price=70,max_price=98,bid_offset=0,contracts=1,starting_cash_cents=10000)
        self.assertEqual(self.client.post('/paper/strategies',json=strategy,headers={'x-test-owner':'owner'}).status_code,403)
        saved=self.client.post('/paper/strategies',json=strategy,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        workspace=self.client.get('/paper/workspace',headers=self.headers).json()
        self.assertFalse(workspace['live_trading_enabled']);self.assertEqual(len(workspace['strategies']),1)
        body=dict(strategy_id=saved.json()['id'],dataset_id=workspace['datasets'][0]['id'],request_key=str(uuid4()))
        first=self.client.post('/paper/replays',json=body,headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        detail=self.client.get('/paper/replays/'+first.json()['id'],headers=self.headers)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertTrue(detail.json()['run']['source_days'])
        self.assertEqual(self.client.post('/paper/replays',json=body,headers=self.headers).json()['id'],first.json()['id'])
        before=list(self.inventory.calls)
        self.assertTrue(PaperWorker(self.db.pool,self.archives).run_once())
        self.assertEqual(self.inventory.calls,before)
        result=self.client.get('/paper/workspace',headers=self.headers).json()['runs'][0]
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['result']['simulated_fills'],0)
        self.assertNotIn('trades',result['result'])
    def test_table_strategy_validates_saved_square_and_shared_portfolio_replays(self):
        identifier=self.create(end='2026-10-25');self.drive(identifier)
        with self.db.pool.connection() as c:
            report=c.execute("SELECT id,report FROM research_result WHERE asset='btc' ORDER BY id DESC LIMIT 1").fetchone()
        cell=next(cell for cell in report['report']['historical']['cells'] if cell['hold']['sampled_markets'])['hold']
        minute=cell['minutes_before_close'];low,high=map(int,cell['price_band_cents'].split('-'))
        strategy=dict(name='From square',asset='btc',minutes=[minute],min_price=low,max_price=high-1,report_id=report['id'],
            entry_minute_min=max([m for m in (15,10,5,3,1) if m<minute],default=0),entry_minute_max=minute,
            below_ask_cents=2,maximum_bid_cents=None,contracts=10,balance_percent=10,loss_trigger_cents=60,starting_cash_cents=10000)
        self.assertEqual(self.client.post('/paper/strategies',json={**strategy,'report_id':999999},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/paper/strategies',json={**strategy,'balance_percent':11},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/paper/strategies',json={**strategy,'bid_reference':'best_bid'},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/paper/strategies',json={**strategy,'bid_reference':'ask','bid_adjustment_cents':0},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/paper/strategies',json={**strategy,'bid_reference':'not_supported','bid_adjustment_cents':0},headers=self.headers).status_code,422)
        for adjustment in (0,1,-2):
            bid_strategy={**strategy,'bid_reference':'best_bid','bid_adjustment_cents':adjustment}
            response=self.client.post('/paper/strategies',json=bid_strategy,headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            saved_id=response.json()['id']
            saved_strategy=next(s['strategy'] for s in self.client.get('/paper/workspace',headers=self.headers).json()['strategies'] if s['id']==saved_id)
            self.assertEqual(saved_strategy['bid_reference'],'best_bid')
            self.assertEqual(saved_strategy['bid_adjustment_cents'],adjustment)
        saved=self.client.post('/paper/strategies',json=strategy,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        workspace=self.client.get('/paper/workspace',headers=self.headers).json()
        self.assertEqual(workspace['strategies'][0]['strategy']['statistical_yield_percent'],cell['hypothetical_roi_percent'])
        body=dict(name='Sports and crypto test',strategy_ids=[saved.json()['id']],dataset_ids=[workspace['datasets'][0]['id']],starting_cash_cents=10000,fill_model='estimated',request_key=str(uuid4()))
        self.assertEqual(self.client.post('/paper/replays',json=body,headers={'x-test-owner':'owner'}).status_code,403)
        first=self.client.post('/paper/replays',json=body,headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        detail=self.client.get('/paper/replays/'+first.json()['id'],headers=self.headers)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertTrue(detail.json()['run']['source_days'])
        self.assertEqual(self.client.post('/paper/replays',json=body,headers=self.headers).json()['id'],first.json()['id'])
        self.assertEqual(self.client.post('/paper/replays',json={**body,'fill_model':'conservative'},headers=self.headers).status_code,409)
        before=list(self.inventory.calls)
        self.assertTrue(PaperWorker(self.db.pool,self.archives).run_once())
        self.assertEqual(self.inventory.calls,before)
        result=self.client.get('/paper/workspace',headers=self.headers).json()['runs'][0]
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['result']['mode'],'historical portfolio replay')
        self.assertEqual(result['activity']['phase'],'finished');self.assertEqual(result['activity']['provider_reads'],0)
        self.assertTrue(result['activity']['updated_at']);self.assertTrue(result['started_at'])
        self.assertLessEqual(result['result']['peak_event_exposure_percent'],10)
    def test_owner_can_cancel_queued_and_active_paper_jobs_and_late_results_are_fenced(self):
        from services.research.queue import ResearchQueue
        from unittest.mock import patch
        queue=ResearchQueue(self.db.pool)
        parameters=dict(collector='paper-replay-v1',dataset_ids=[1],strategies=[],starting_cash_cents=10000,fill_model='estimated',name='Cancel test')
        queued=queue.enqueue('btc',parameters,'paper-replay/'+str(uuid4()))
        path='/paper/replays/'+str(queued['id'])+'/cancel'
        self.assertEqual(self.client.post(path,json={}).status_code,401)
        self.assertEqual(self.client.post(path,json={},headers={'x-test-owner':'owner'}).status_code,403)
        self.assertEqual(self.client.post(path,json={},headers=self.headers).json()['status'],'cancelled')
        self.assertEqual(self.client.post(path,json={},headers=self.headers).json()['status'],'cancelled')
        self.assertFalse(PaperWorker(self.db.pool,self.archives).run_once())
        active=queue.enqueue('btc',parameters,'paper-replay/'+str(uuid4()))
        def cancel_during_replay(*args,**kwargs):
            response=self.client.post('/paper/replays/'+str(active['id'])+'/cancel',json={},headers=self.headers)
            self.assertEqual(response.json()['status'],'cancelled')
            kwargs['on_progress'](dict(phase='checking canceled ownership'))
            self.fail('Canceled worker retained its lease')
        with patch('services.paper.worker.replay_portfolio',side_effect=cancel_during_replay):
            self.assertTrue(PaperWorker(self.db.pool,self.archives).run_once())
        state=queue.get(active['id']);self.assertEqual(state['status'],'cancelled');self.assertNotIn('result',state['progress'])
        unrelated=queue.enqueue('btc',dict(collector='unrelated'),'unrelated/'+str(uuid4()))
        self.assertEqual(self.client.post('/paper/replays/'+str(unrelated['id'])+'/cancel',json={},headers=self.headers).status_code,404)

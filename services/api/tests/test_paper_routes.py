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
        self.assertEqual(self.client.post('/paper/replays',json=body,headers=self.headers).json()['id'],first.json()['id'])
        self.assertTrue(PaperWorker(self.db.pool,self.archives).run_once())
        result=self.client.get('/paper/workspace',headers=self.headers).json()['runs'][0]
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['result']['simulated_fills'],0)
        self.assertNotIn('trades',result['result'])

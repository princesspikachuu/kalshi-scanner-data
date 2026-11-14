import copy,time,unittest,os
from uuid import uuid4
from psycopg.types.json import Jsonb
import test_campaigns as fixtures
from test_paper_routes import PaperRouteTests
from services.paper.live_store import LiveStore
from services.research.queue import LeaseLost
from test_live_paper import strategy,quote,trade


@unittest.skipUnless(os.environ.get('POCKET_TEST_DATABASE_URL'),'Requires disposable pocket_test PostgreSQL')
class LivePaperRouteTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CampaignPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.CampaignPostgresTests.tearDownClass.__func__)
    setUp=PaperRouteTests.setUp
    make_worker=fixtures.CampaignPostgresTests.make_worker
    create=fixtures.CampaignPostgresTests.create
    drive=fixtures.CampaignPostgresTests.drive

    def start(self):
        identifier=uuid4();s=strategy();s.pop('series')
        with self.db.pool.connection() as c:
            c.execute("INSERT INTO research_job(id,asset,parameters,idempotency_key,status) VALUES(%s,'btc',%s,%s,'succeeded')",
                (identifier,Jsonb(dict(collector='paper-strategy-v1',strategy=s)),'paper-strategy/'+str(identifier)))
        body=dict(strategy_ids=[str(identifier)],request_key=str(uuid4()),starting_cash_cents=10000,name='Live test')
        response=self.client.post('/paper/live',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['id'],body

    def test_owner_csrf_idempotency_single_account_and_immutable_setup(self):
        self.assertEqual(self.client.get('/paper/live').status_code,401)
        self.assertEqual(self.client.post('/paper/live',json=dict(strategy_ids=[str(uuid4())],request_key=str(uuid4())),headers={'x-test-owner':'owner'}).status_code,403)
        identifier,body=self.start()
        self.assertEqual(self.client.post('/paper/live',json=body,headers=self.headers).json()['id'],identifier)
        self.assertEqual(self.client.post('/paper/live',json={**body,'name':'different'},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/paper/live',json={**body,'request_key':str(uuid4())},headers=self.headers).status_code,409)
        result=self.client.get('/paper/live/'+identifier,headers=self.headers).json()
        self.assertFalse(result['live_trading_enabled']);self.assertTrue(result['live_paper_enabled'])
        self.assertEqual(result['session']['configuration']['strategies'][0]['series'],['KXBTC15M'])
        self.assertEqual(self.client.get('/paper/live/'+identifier+'?host=evil',headers=self.headers).status_code,422)

    def test_checkpoint_crash_recovery_dedup_audit_and_old_lease_fencing(self):
        identifier,_=self.start();store=LiveStore(self.db.pool);job=store.claim();now=time.time()
        market=dict(ticker='a',event='one',series='KXBTC15M',close=now+300,status='active',result='')
        store.checkpoint(job,now,metadata=[market],feed='connected',messages=[quote(t=now)])
        state=store.checkpoint(job,now+3,messages=[trade(t=now+3)])
        self.assertEqual(state['filled_contracts'],2)
        # A new process recovers the saved state, not the original paper cash.
        with self.db.pool.connection() as c:c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(identifier,))
        replacement=store.claim();self.assertNotEqual(job['lease_token'],replacement['lease_token'])
        with self.assertRaises(LeaseLost):store.checkpoint(job,now+4)
        state=store.checkpoint(replacement,now+4,messages=[trade(t=now+3)])
        self.assertEqual(state['filled_contracts'],2)
        audit=self.client.get('/paper/live/'+identifier+'/events',headers=self.headers).json()['events']
        self.assertEqual([e['kind'] for e in audit],['fill','bid'])
        self.assertEqual(audit[0]['order_id'],audit[1]['order_id'])
        earlier=self.client.get('/paper/live/'+identifier+'/events?before=2',headers=self.headers).json()['events']
        self.assertEqual([e['kind'] for e in earlier],['bid'])

    def test_stop_revokes_unfilled_money_keeps_positions_and_prevents_new_entries(self):
        identifier,_=self.start();store=LiveStore(self.db.pool);job=store.claim();now=time.time()
        market=dict(ticker='a',event='one',series='KXBTC15M',close=now+300,status='active',result='')
        store.checkpoint(job,now,metadata=[market],feed='connected',messages=[quote(t=now)])
        store.checkpoint(job,now+3,messages=[trade(t=now+3)])
        path='/paper/live/'+identifier+'/stop'
        self.assertEqual(self.client.post(path,json={},headers={'x-test-owner':'owner'}).status_code,403)
        self.assertEqual(self.client.post(path,json={},headers=self.headers).status_code,200)
        state=store.checkpoint(job,now+4,feed='connected',messages=[quote(t=now+4)])
        self.assertTrue(state['stopping']);self.assertFalse(state['orders']);self.assertEqual(state['cash'],9822)
        self.assertEqual(len(state['positions']),1)
        market.update(status='settled',result='yes')
        store.checkpoint(job,now+301,metadata=[market])
        detail=self.client.get('/paper/live/'+identifier,headers=self.headers).json()['session']
        self.assertEqual(detail['status'],'succeeded');self.assertEqual(detail['state']['cash'],10022)
        with self.assertRaises(LeaseLost):store.checkpoint(job,now+302)

    def test_stop_queued_account_finishes_and_events_query_is_bounded(self):
        identifier,_=self.start()
        self.client.post('/paper/live/'+identifier+'/stop',json={},headers=self.headers)
        self.assertIsNone(LiveStore(self.db.pool).claim())
        for query in ('?before=2&before=1','?before=-1','?before=1234567890123','?url=evil'):
            self.assertEqual(self.client.get('/paper/live/'+identifier+'/events'+query,headers=self.headers).status_code,422)

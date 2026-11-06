import json,time,unittest,tempfile,shutil
from unittest.mock import Mock
from decimal import Decimal as D
from services.paper_demo.shadow.core import Engine,StrategyFleet,FeePolicy,Lot
from services.paper_demo.shadow.migrate import profiles,initialize
from services.paper_demo.shadow.state import encode,restore
from services.paper_demo.shadow.storage import HostedAudit,put
from services.api.tests import test_demo_postgres as fixture

class StateTests(unittest.TestCase):
    def test_restore_preserves_inventory_cash_and_arming_but_cancels_unknown_downtime(self):
        audit=Mock();engine=Engine(audit);fleet=StrategyFleet(engine,profiles())
        audit.log=Mock();engine.advance(1000)
        engine.add_market(dict(ticker='KXBTC15M-test',close=1900),FeePolicy())
        engine.wallet.lots=[Lot('id','KXBTC15M-test','yes',D(3),D('.1'),D(0),1,True)]
        order=engine.place('KXBTC15M-test','yes','buy',D(2),D('.1'))
        data=json.loads(json.dumps(encode(engine,fleet),default=str))
        expected_random=engine.rng.random()
        new=Engine(Mock());new_fleet=StrategyFleet(new,profiles());restore(new,new_fleet,data)
        self.assertEqual(new.wallet.cash,engine.wallet.cash)
        self.assertTrue(new.wallet.lots[0].is_armed)
        self.assertEqual(new.orders[order].status,'cancelled')
        self.assertFalse(new.wallet.stat('KXBTC15M-test').valid)
        self.assertIn('KXBTC15M-test',new_fleet.halted)
        self.assertEqual(new.rng.random(),expected_random)
        self.assertEqual(new.pending,[])

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class HostedPostgres(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)

    def seed(self):
        self.assertTrue(initialize(self.demo,lambda:None))

    def test_rollout_is_idempotent_and_preserves_old_history(self):
        from services.api.tests.test_demo_engine import config
        self.demo.put('bot/old',dict(desired='running'),parameters=dict(config=config(),revision=7))
        self.demo.put('order/old',dict(status='closed',realized_cents=123),parameters=dict(kind='entry',bot='old',revision=7))
        self.seed();self.seed()
        self.assertEqual(len(self.demo.rows('shadow/bot/',100)),28)
        self.assertEqual(self.demo.get('order/old')['progress']['realized_cents'],123)
        self.assertTrue(self.demo.get('bot/old')['progress']['archived'])
        self.assertFalse(self.demo.get('engine')['progress']['real_orders_enabled'])

    def test_workspace_and_revision_change_keep_previous_version_results(self):
        self.seed()
        with self.demo.pool.connection() as c:
            put(c,'demo/shadow/report/KXBTC15M-example',{},dict(ticker='KXBTC15M-example',bot_id='btc',bot_revision=1,
                at=time.time(),data_valid=True,gross_profit='2',total_fees_paid='.1',net_realized_pnl='1.9',
                closed_contracts='10',winning_contracts='6',final=True))
        result=self.client.get('/demo/shadow/workspace').json()
        self.assertEqual(len(result['bots']),28)
        btc=next(b for b in result['bots'] if b['id']=='btc')
        self.assertEqual(D(btc['metrics']['all']['net_realized_pnl']),D('1.9'))
        changed=self.client.post('/demo/shadow/bots/btc',json=dict(revision=1,contracts=2))
        self.assertEqual(changed.status_code,200)
        current=self.client.get('/demo/shadow/workspace').json()
        self.assertEqual(D(next(b for b in current['bots'] if b['id']=='btc')['metrics']['all']['net_realized_pnl']),0)
        full=self.client.get('/demo/shadow/workspace?version=full').json()
        self.assertEqual(D(next(b for b in full['bots'] if b['id']=='btc')['metrics']['all']['net_realized_pnl']),D('1.9'))

    def test_refill_request_is_deduplicated_and_atomic_with_checkpoint(self):
        self.seed();request=dict(amount_cents=5000,request_id='test-refill-request-123')
        for _ in range(2):self.assertEqual(self.client.post('/demo/shadow/funds',json=request).status_code,200)
        audit=HostedAudit(self.demo,lambda:None);engine=Engine(audit);fleet=StrategyFleet(engine,profiles())
        audit.engine,audit.fleet=engine,fleet
        audit.command_key='demo/shadow/command/'+request['request_id']
        engine.refill(D(50))
        self.assertTrue(self.demo.get('shadow/command/'+request['request_id'])['progress']['done'])
        self.assertEqual(D(self.demo.get('shadow/checkpoint')['progress']['wallet']['cash']),100)
        self.assertEqual(self.client.post('/demo/shadow/funds',json=request).status_code,200)
        self.assertTrue(self.demo.get('shadow/command/'+request['request_id'])['progress']['done'])
        self.assertEqual(self.client.post('/demo/shadow/funds',json=dict(request,amount_cents=5001)).status_code,409)
        shutil.rmtree(audit.path)

    def test_burst_commit_preserves_every_audit_record_and_atomic_checkpoint(self):
        self.seed()
        audit=HostedAudit(self.demo,lambda:None);engine=Engine(audit);fleet=StrategyFleet(engine,profiles())
        audit.engine,audit.fleet=engine,fleet;engine.advance(1000)
        audit.begin()
        for _ in range(54):engine.refill(D(1))
        audit.flush()
        with self.demo.pool.connection() as c:
            count=c.execute("SELECT count(*) AS n FROM research_job WHERE idempotency_key>='demo/shadow/event/' AND idempotency_key<'demo/shadow/event/zzzz'").fetchone()['n']
            balances=c.execute("SELECT (progress->>'cash')::numeric AS cash FROM research_job WHERE idempotency_key>='demo/shadow/event/' AND idempotency_key<'demo/shadow/event/zzzz'").fetchall()
        self.assertEqual(count,54)
        self.assertEqual(sorted(row['cash'] for row in balances),list(range(51,105)))
        self.assertEqual(D(self.demo.get('shadow/checkpoint')['progress']['wallet']['cash']),104)
        shutil.rmtree(audit.path)

    def test_controls_require_csrf_and_do_not_allow_real_routing(self):
        self.seed();self.client.headers.pop('x-csrf-token')
        self.assertEqual(self.client.post('/demo/shadow/bulk',json=dict(action='resume')).status_code,403)
        self.assertEqual(self.client.get('/demo/shadow/workspace').status_code,200)
        response=self.client.post('/demo/shadow/bots/btc',json=dict(revision=1,live_enabled=True))
        self.assertIn(response.status_code,(403,422))

    def test_gap_cycles_do_not_inflate_valid_strategy_metrics(self):
        self.seed()
        with self.demo.pool.connection() as c:
            put(c,'demo/shadow/report/KXBTC15M-gap',{},dict(ticker='KXBTC15M-gap',bot_id='btc',bot_revision=1,
                at=time.time(),data_valid=False,gross_profit='200',total_fees_paid='1',net_realized_pnl='199',
                closed_contracts='100',winning_contracts='100',final=True))
        result=self.client.get('/demo/shadow/workspace').json()
        metric=next(b for b in result['bots'] if b['id']=='btc')['metrics']['all']
        self.assertEqual(D(metric['net_realized_pnl']),0)
        self.assertEqual(metric['excluded_cycles'],1)

class HostedFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_input_does_not_checkpoint_uncertain_mutated_memory(self):
        import asyncio
        from services.paper_demo.shadow.host import HostedRun
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.audit=Mock();run.verified_data=Mock()
        async def fail():raise RuntimeError('commit failed')
        async def wait():await asyncio.Event().wait()
        run.discover=fail
        run.kalshi=run.spot=run.clock=run.consume=run.control=run.fee_maintenance=wait
        run.selected={};run.engine=Mock()
        with self.assertRaises(RuntimeError):await run.run()
        run.audit.checkpoint.assert_not_called()

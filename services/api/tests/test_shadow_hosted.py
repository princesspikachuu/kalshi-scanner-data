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
        engine.wallet.lots=[Lot('id','KXBTC15M-test','yes',D(3),D('.1'),D(0),1,True,acquired_at=999.5)]
        order=engine.place('KXBTC15M-test','yes','buy',D(2),D('.1'))
        data=json.loads(json.dumps(encode(engine,fleet),default=str))
        expected_random=engine.rng.random()
        new=Engine(Mock());new_fleet=StrategyFleet(new,profiles());restore(new,new_fleet,data)
        self.assertEqual(new.wallet.cash,engine.wallet.cash)
        self.assertTrue(new.wallet.lots[0].is_armed)
        self.assertEqual(new.wallet.lots[0].acquired_at,999.5)
        self.assertEqual(new.orders[order].status,'cancelled')
        self.assertFalse(new.wallet.stat('KXBTC15M-test').valid)
        self.assertIn('KXBTC15M-test',new_fleet.halted)
        self.assertEqual(new.rng.random(),expected_random)
        self.assertEqual(new.pending,[])
        # Existing checkpoints without entry timestamps retain their flags.
        data['wallet']['lots'][0].pop('acquired_at')
        old=Engine(Mock());old_fleet=StrategyFleet(old,profiles());restore(old,old_fleet,data)
        self.assertTrue(old.wallet.lots[0].is_armed)
        self.assertEqual(old.wallet.lots[0].acquired_at,0)

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

    def test_archive_keyset_pages_cover_both_histories_without_dropping_events(self):
        import io
        from services.demo.maintenance import archive_events,read_verified
        from services.paper_demo.shadow.storage import UPSERT,entry
        class Objects:
            bucket='private'
            def __init__(self):self.client=self;self.objects={}
            def put_object(self,**kw):self.objects[kw['Key']]=kw['Body']
            def get_object(self,**kw):
                body=self.objects[kw['Key']];return dict(ContentLength=len(body),Body=io.BytesIO(body))
        records=[entry('demo/event/'+f'{i:04}',{},dict(original=i)) for i in range(201)]
        records.append(entry('demo/shadow/event/one',{},dict(original='shadow',restored_at=None)))
        with self.demo.pool.connection() as c:
            with c.cursor() as cur:cur.executemany(UPSERT,records)
            c.execute("UPDATE research_job SET created_at=clock_timestamp()-interval '40 days'")
        objects=Objects()
        for _ in range(3):archive_events(self.demo,objects,{'archive_days':7},False)
        with self.demo.pool.connection() as c:
            archived=c.execute("SELECT progress FROM research_job WHERE progress ? 'archive'").fetchall()
        self.assertEqual(len(archived),202)
        references={r['progress']['archive']['key']:r['progress']['archive'] for r in archived}
        restored=[row for ref in references.values() for row in read_verified(objects,ref)]
        self.assertEqual(len(restored),202);self.assertEqual(len({r['id'] for r in restored}),202)
        self.assertEqual(self.demo.get('archive-scan')['progress']['cursors']['demo/event/'],'demo/event/')

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

    def test_multirow_audit_commit_preserves_all_events_and_checkpoint_atomically(self):
        self.seed()
        audit=HostedAudit(self.demo,lambda:None)
        self.addCleanup(shutil.rmtree,audit.path)
        engine=Engine(audit)
        fleet=StrategyFleet(engine,profiles())
        audit.engine,audit.fleet=engine,fleet
        audit.durability_log_at=float('inf')
        engine.advance(1000)
        audit.begin()
        for i in range(145):
            engine.refill(D(1))
        audit.flush()
        with self.demo.pool.connection() as c:
            rows=c.execute("SELECT progress FROM research_job "
                "WHERE starts_with(idempotency_key,'demo/shadow/event/')").fetchall()
        self.assertEqual(len(rows),145)
        self.assertEqual(sorted(D(row['progress']['cash']) for row in rows),
                         list(map(D,range(51,196))))
        self.assertEqual(D(self.demo.get('shadow/checkpoint')['progress']['wallet']['cash']),195)
        self.assertEqual(audit.durability_profile['bulk_event_rows'],145)
        self.assertEqual(audit.durability_profile['bulk_event_groups'],3)
        self.assertEqual(audit.durability_profile['commits'],1)

    def test_async_commit_keeps_refill_marker_events_and_wallet_atomic(self):
        import asyncio
        self.seed();request=dict(amount_cents=5000,request_id='async-refill-request-123')
        self.assertEqual(self.client.post('/demo/shadow/funds',json=request).status_code,200)
        audit=HostedAudit(self.demo,lambda:None);engine=Engine(audit);fleet=StrategyFleet(engine,profiles())
        self.addCleanup(shutil.rmtree,audit.path)
        audit.engine,audit.fleet=engine,fleet
        audit.command_key='demo/shadow/command/'+request['request_id']
        audit.begin();engine.refill(D(50));asyncio.run(audit.flush_async())
        self.assertTrue(self.demo.get('shadow/command/'+request['request_id'])['progress']['done'])
        self.assertEqual(D(self.demo.get('shadow/checkpoint')['progress']['wallet']['cash']),100)
        with self.demo.pool.connection() as c:
            events=c.execute("SELECT progress FROM research_job WHERE starts_with(idempotency_key,'demo/shadow/event/') AND progress->>'event'='REFILL'").fetchall()
        self.assertEqual(len(events),1);self.assertEqual(D(events[0]['progress']['cash']),100)

    def test_hosted_control_publishes_through_serialized_async_database_path(self):
        import asyncio,threading
        from unittest.mock import patch
        from services.paper_demo.shadow.host import HostedRun
        self.seed();run=HostedRun(self.demo,lambda:None,threading.Event(),Mock())
        self.addCleanup(shutil.rmtree,run.audit.path)
        async def stop_after_pass(_):run.done.set()
        with patch('services.paper_demo.shadow.host.asyncio.sleep',side_effect=stop_after_pass):
            asyncio.run(run.control())
        self.assertIsNotNone(self.demo.get('shadow/status'))
        self.assertEqual(self.demo.get('health')['progress']['state'],'waiting')
        self.assertFalse(run.state_mutex().locked())

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

    def test_financial_totals_include_gap_losses_and_reconcile_with_open_positions(self):
        from services.api.tests.test_shadow_accounting import fixture as accounting_fixture,PROFILES
        from services.paper_demo.shadow.accounting import snapshot
        self.seed();money=snapshot(accounting_fixture(),PROFILES,1000)
        self.demo.put('shadow/status',dict(at=1000,accounting=money))
        with self.demo.pool.connection() as c:
            for ticker,bot,gross,net,fees,at in (
                    ('KXBTC15M-old','btc','-19','-20','1',100),
                    ('KXETH15M-old','eth','2','1.3','.7',100),
                    ('KXBTC15M-test','btc','999','999','0',900)):
                put(c,'demo/shadow/report/'+ticker,{},dict(ticker=ticker,bot_id=bot,bot_revision=1,
                    at=at,data_valid=False,gross_profit=gross,total_fees_paid=fees,net_realized_pnl=net,
                    closed_contracts='10',winning_contracts='0',final=ticker.endswith('old')))
        result=self.client.get('/demo/shadow/workspace').json()
        btc=next(b for b in result['bots'] if b['id']=='btc')
        self.assertEqual(D(btc['metrics']['all']['net_realized_pnl']),0)
        self.assertEqual(D(btc['financial_metrics']['all']['net_realized_pnl']),-20)
        self.assertEqual(D(btc['account']['total_pnl']),-11)
        a=result['accounting']['portfolio']
        self.assertEqual(D(a['total_pnl']),-3);self.assertEqual(D(a['reconciliation_difference']),0)
        self.assertEqual(result['accounting']['quality'],{'verified_cycles':0,'gap_cycles':2})
        # Version filters change realized-result analysis, never all-history cash exposure.
        self.client.post('/demo/shadow/bots/btc',json=dict(revision=1,contracts=2))
        latest=self.client.get('/demo/shadow/workspace').json()
        btc=next(b for b in latest['bots'] if b['id']=='btc')
        self.assertEqual(D(btc['financial_metrics']['all']['net_realized_pnl']),0)
        self.assertEqual(D(btc['account']['total_pnl']),-11)
        full=self.client.get('/demo/shadow/workspace?version=full').json()
        self.assertEqual(D(next(b for b in full['bots'] if b['id']=='btc')['financial_metrics']['all']['net_realized_pnl']),-20)

    def test_gap_money_follows_hour_six_and_day_windows_without_becoming_zero_lifetime(self):
        self.seed();now=time.time()
        with self.demo.pool.connection() as c:
            put(c,'demo/shadow/report/KXBTC15M-older',{},dict(ticker='KXBTC15M-older',bot_id='btc',
                bot_revision=1,at=now-3700,data_valid=False,gross_profit='-9',total_fees_paid='1',
                net_realized_pnl='-10',closed_contracts='1',winning_contracts='0',final=True))
        result=self.client.get('/demo/shadow/workspace').json()
        periods=next(b for b in result['bots'] if b['id']=='btc')['financial_metrics']
        self.assertEqual(D(periods['1H']['net_realized_pnl']),0)
        for period in ('all','6H','24H'):self.assertEqual(D(periods[period]['net_realized_pnl']),-10)

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

"""A reporting timeout must not reset execution or hold the trading state lock."""
import asyncio,shutil,threading,time,unittest
from unittest.mock import Mock,AsyncMock,patch
from psycopg.errors import QueryCanceled
from services.paper_demo.shadow.history_sampling import MinuteHistory
from services.api.tests import test_demo_postgres as fixture

class HistorySamplingTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_defers_without_marking_missing_sample_successful_and_retries(self):
        h=MinuteHistory();audit=Mock();audit.durable_io=AsyncMock(side_effect=[None,QueryCanceled('timeout')])
        at=[100.0];sample=({}, {},600,[])
        with patch('services.paper_demo.shadow.history_sampling.time',Mock(wraps=time,monotonic=lambda:at[0])):
            await h.write(audit,Mock(),sample)
            self.assertIsNone(h.minute);self.assertFalse(h.due(600))
            at[0]=130;self.assertTrue(h.due(600))
            audit.durable_io=AsyncMock();await h.write(audit,Mock(),sample)
            self.assertEqual(h.minute,10);self.assertFalse(h.due(600));self.assertTrue(h.due(660))
    async def test_fencing_unexpected_errors_and_cancellation_are_not_suppressed(self):
        for error in (RuntimeError('ownership lost'),ValueError('bad sample'),asyncio.CancelledError()):
            h=MinuteHistory();audit=Mock();audit.durable_io=AsyncMock(side_effect=error)
            with self.assertRaises(type(error)):await h.write(audit,Mock(),({}, {},600,[]))
            self.assertIsNone(h.minute)
    async def test_frozen_snapshot_is_independent_and_excludes_research_cells(self):
        h=MinuteHistory();accounts={'maker':{'cash':'1000'}};positions=[{'quantity':'2'}]
        experiments={'maker':{'bots':{'B':{'net_realized_pnl':'.02','scalper':{
            'totals':{'completed':1,'rejections':{'depth':2}},'cells':{'expensive':'research'}}}}}}
        a,e,now,p=h.freeze(accounts,experiments,600,positions)
        accounts['maker']['cash']='0';positions[0]['quantity']='0'
        experiments['maker']['bots']['B']['scalper']['totals']['rejections']['depth']=9
        self.assertEqual(a['maker']['cash'],'1000');self.assertEqual(p[0]['quantity'],'2')
        self.assertEqual(e['maker']['bots']['B']['scalper']['totals']['rejections']['depth'],2)
        self.assertNotIn('cells',e['maker']['bots']['B']['scalper'])

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class HostedHistoryIsolationTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)
    def run_once(self,writer):
        from services.paper_demo.shadow.host import HostedRun
        from services.paper_demo.shadow.migrate import initialize
        self.assertTrue(initialize(self.demo,lambda:None))
        run=HostedRun(self.demo,lambda:None,threading.Event(),Mock())
        self.addCleanup(shutil.rmtree,run.audit.path)
        async def stop(_):run.done.set()
        with patch('services.paper_demo.shadow.host.asyncio.sleep',side_effect=stop),writer(run):
            asyncio.run(run.control())
        self.assertIsNotNone(self.demo.get('shadow/status'));self.assertFalse(run.state_mutex().locked())
    def test_history_writer_runs_outside_execution_mutex(self):
        called=[]
        def writer(run):
            async def sample(history,audit,store,inputs):
                called.append(True);self.assertFalse(run.state_mutex().locked())
                async with run.state_mutex():self.assertTrue(run.state_mutex().locked())
            return patch.object(MinuteHistory,'write',new=sample)
        self.run_once(writer);self.assertEqual(called,[True])
    def test_real_control_survives_reporting_timeout_and_publishes_status(self):
        self.run_once(lambda run:patch('services.paper_demo.shadow.history_sampling.record_bot_balances',side_effect=QueryCanceled('timeout')))

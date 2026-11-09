"""Amortize durable writes while retaining FIFO processing and immediate risk gates."""
import asyncio,time,unittest
from unittest.mock import Mock,patch
from services.api.tests import test_flat_experiment_feed as feed
from services.paper_demo.shadow.host import HostedRun
from services.paper_demo.shadow.scalper import VolatilityScalper,SCALPER_FOLDERS
from services.paper_demo.shadow.market_maker import MM_FOLDERS

class BurstTimeBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_backlog_uses_bounded_longer_batch_and_keeps_fifo(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.prepare_fees=lambda source,payload,now:payload
        seen=[];commits=[];clock=[0.0]
        def handle(source,payload,now):
            seen.append(payload['n']);clock[0]+=.03
            if len(seen)==44:run.done.set()
        run.engine.handle=handle;run.audit.flush.side_effect=lambda:commits.append(len(seen))
        for n in range(2500):await run.queue.put(('clock',dict(n=n),1000+n*.01))
        with patch('services.paper_demo.shadow.host.time',Mock(wraps=time,monotonic=lambda:clock[0],time=time.time)):await run.consume()
        self.assertEqual(seen,list(range(44)));self.assertEqual(commits,[22,44]);self.assertEqual(run.queue._unfinished_tasks,2456)
    async def test_large_backlog_never_exceeds_4096_inputs_in_one_atomic_batch(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.prepare_fees=lambda source,payload,now:payload;seen=[]
        run.engine.handle.side_effect=lambda source,payload,now:seen.append(payload['n'])
        run.audit.flush.side_effect=run.done.set
        for n in range(5000):await run.queue.put(('clock',dict(n=n),1000+n*.01))
        with patch('services.paper_demo.shadow.host.time',Mock(wraps=time,monotonic=lambda:0,time=time.time)):await run.consume()
        self.assertEqual(seen,list(range(4096)));self.assertEqual(run.queue._unfinished_tasks,904)
    async def test_time_budget_yields_before_input_cap_and_preserves_every_input(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.prepare_fees=lambda source,payload,now:payload
        seen=[];commits=[];clock=[0.0];yielded=asyncio.Event();loop=asyncio.get_running_loop()
        def handle(source,payload,now):
            seen.append(payload['n']);clock[0]+=.05
            if len(seen)==1:loop.call_soon(yielded.set)
            if len(seen)==10:run.done.set()
        run.engine.handle=handle
        run.audit.flush.side_effect=lambda:commits.append((len(seen),yielded.is_set()))
        for n in range(768):await run.queue.put(('clock',dict(n=n),1000+n*.01))
        with patch('services.paper_demo.shadow.host.time',Mock(wraps=time,monotonic=lambda:clock[0],time=time.time)):await run.consume()
        self.assertEqual(seen,list(range(10)))
        self.assertEqual([n for n,_ in commits],[5,10])
        self.assertTrue(all(flag for _,flag in commits))
        self.assertEqual(run.queue._unfinished_tasks,758)

class SharedRiskBudgetTests(unittest.TestCase):
    def suite(self):
        fixture=feed.FlatExperimentFeedTests();suite=fixture.suite();fixture.book(suite,200.1,1)
        return fixture,suite
    def test_one_budget_read_per_shared_market_input(self):
        fixture,suite=self.suite();suite.monitoring.limits=Mock(wraps=suite.monitoring.limits)
        with patch('services.paper_demo.shadow.experiments.time',Mock(wraps=time,time=lambda:1000)):
            fixture.delta(suite,200.2,2,'yes','.45','1')
        suite.monitoring.limits.assert_called_once_with(1000)
    def test_feed_timestamp_does_not_falsely_age_current_operational_telemetry(self):
        fixture,suite=self.suite()
        from services.paper_demo.shadow.monitoring import MonitoringBudget
        suite.monitoring=MonitoringBudget();suite.monitoring.observe(1000,0,0,.1)
        with patch('services.paper_demo.shadow.experiments.time',Mock(wraps=time,time=lambda:1000.1)):
            fixture.delta(suite,200.2,2,'yes','.45','1')
            self.assertTrue(suite.extra_capacity(['NEW-MARKET'],200.2))
            self.assertTrue(suite.search_capacity('market_maker',200.2))
        self.assertFalse(any(b.resource_paused for folder,(_,fleet,_) in suite.portfolios.items()
            if folder in (*SCALPER_FOLDERS,*MM_FOLDERS) for b in fleet.bots.values()))
        # Old or overloaded operational telemetry must still stop new entries.
        with patch('services.paper_demo.shadow.experiments.time',Mock(wraps=time,time=lambda:1011)):
            fixture.delta(suite,200.3,3,'yes','.45','1')
            self.assertFalse(suite.extra_capacity(['NEW-MARKET'],200.3))
        self.assertTrue(all(b.resource_paused for folder,(_,fleet,_) in suite.portfolios.items()
            if folder in (*SCALPER_FOLDERS,*MM_FOLDERS) for b in fleet.bots.values()))
        suite.monitoring.observe(1012,3000,3,.1)
        with patch('services.paper_demo.shadow.experiments.time',Mock(wraps=time,time=lambda:1012.1)):
            fixture.delta(suite,200.4,4,'yes','.45','1')
            self.assertFalse(suite.extra_capacity(['NEW-MARKET'],200.4))
        self.assertTrue(all(b.resource_paused for folder,(_,fleet,_) in suite.portfolios.items()
            if folder in (*SCALPER_FOLDERS,*MM_FOLDERS) for b in fleet.bots.values()))
    def test_unchanged_budget_avoids_rewriting_profiles_but_transitions_apply_immediately(self):
        fixture,suite=self.suite();writes=[]
        def record(bot,name,value):
            if name=='resource_paused':writes.append((id(bot),value))
            object.__setattr__(bot,name,value)
        with patch.object(VolatilityScalper,'__setattr__',record,create=True):
            for i in range(5):fixture.delta(suite,200.2+i*.01,i+2,'yes','.45','1')
            self.assertEqual(writes,[])
            prior=suite.monitoring.limits(200.3)
            suite.monitoring.limits=lambda now:dict(prior,admitting=False)
            fixture.delta(suite,200.4,7,'yes','.45','1')
            bots=[b for f,(_,fleet,_) in suite.portfolios.items() if f in (*SCALPER_FOLDERS,*MM_FOLDERS) for b in fleet.bots.values()]
            self.assertEqual(len(writes),len(bots));self.assertTrue(all(b.resource_paused for b in bots))
            writes.clear();fixture.delta(suite,200.5,8,'yes','.45','1');self.assertEqual(writes,[])
            suite.monitoring.limits=lambda now:dict(prior,admitting=True)
            fixture.delta(suite,200.6,9,'yes','.45','1')
            self.assertEqual(len(writes),len(bots));self.assertFalse(any(b.resource_paused for b in bots))

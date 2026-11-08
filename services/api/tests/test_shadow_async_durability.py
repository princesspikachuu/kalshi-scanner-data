"""Database waits must leave sockets live without allowing concurrent wallet mutation."""
import asyncio,shutil,threading,unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,StrategyFleet
from services.paper_demo.shadow.host import HostedRun
from services.paper_demo.shadow.storage import HostedAudit

class AsyncDurability(unittest.IsolatedAsyncioTestCase):
    def audit(self):
        audit=HostedAudit(Mock(),lambda:None);self.addCleanup(shutil.rmtree,audit.path)
        audit.engine=Engine(audit,cash='1000');audit.fleet=StrategyFleet(audit.engine,[])
        return audit

    async def test_sockets_keep_receiving_during_commit_but_next_mutation_waits(self):
        audit=self.audit();started=threading.Event();release=threading.Event();committed=[]
        run=object.__new__(HostedRun);run.audit=audit;run.engine=audit.engine
        run.queue=asyncio.Queue();run.done=asyncio.Event();run.prepare_fees=lambda source,payload,now:payload
        def write(prepared):
            started.set()
            if not release.wait(2):raise RuntimeError('test release timeout')
            committed.append(prepared[0][0][2].obj['wallet']['cash'])
        audit.write=write
        def handle(source,payload,now):
            run.engine.now=now;run.engine.refill(D(1))
            if run.engine.wallet.cash==D(1002):run.done.set()
        run.engine.handle=handle
        await run.put('clock',{})
        task=asyncio.create_task(run.consume())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,1))
            await run.put('clock',{})
            self.assertEqual(run.queue.qsize(),1)
            self.assertEqual(run.engine.wallet.cash,D(1001))
            self.assertTrue(run.state_mutex().locked())
            self.assertEqual(run.queue._unfinished_tasks,2)
            mutation_entered=asyncio.Event()
            async def control():
                async with run.state_mutex():mutation_entered.set()
            control_task=asyncio.create_task(control());await asyncio.sleep(0)
            self.assertFalse(mutation_entered.is_set())
            release.set();await asyncio.wait_for(task,2);await control_task
            self.assertEqual(committed,['1001','1002'])
            self.assertEqual(run.queue._unfinished_tasks,0)
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_repeated_shutdown_cancellation_waits_for_database_completion(self):
        audit=self.audit();started=threading.Event();release=threading.Event();finished=threading.Event();lock=asyncio.Lock()
        def write():
            started.set();release.wait(2);finished.set()
        async def holder():
            async with lock:await audit.durable_io(write)
        task=asyncio.create_task(holder())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,1))
            for _ in range(2):
                task.cancel();await asyncio.sleep(0)
                self.assertTrue(lock.locked());self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
            self.assertTrue(finished.is_set());self.assertFalse(lock.locked())
        finally:
            release.set();await asyncio.gather(task,return_exceptions=True)

    async def test_failed_async_commit_leaves_queue_unacknowledged(self):
        audit=self.audit();run=object.__new__(HostedRun)
        run.audit=audit;run.engine=audit.engine;run.done=asyncio.Event();run.queue=asyncio.Queue()
        run.prepare_fees=lambda source,payload,now:payload
        run.engine.handle=lambda *args:run.engine.refill(D(1))
        audit.write=Mock(side_effect=RuntimeError('database write failed'))
        await run.put('clock',{})
        with self.assertRaisesRegex(RuntimeError,'database write failed'):await run.consume()
        self.assertEqual(run.queue._unfinished_tasks,1)
        self.assertFalse(run.state_mutex().locked());self.assertIsNone(audit.buffer)

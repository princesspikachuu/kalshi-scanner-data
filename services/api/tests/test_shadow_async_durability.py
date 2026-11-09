"""Database waits must leave sockets live without allowing concurrent wallet mutation."""
import asyncio,shutil,threading,unittest
from types import SimpleNamespace
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

    async def test_durability_breakdown_reports_only_successfully_committed_writes(self):
        from unittest.mock import MagicMock
        store=Mock();store.pool.connection.return_value=MagicMock()
        audit=HostedAudit(store,lambda:None)
        self.addCleanup(shutil.rmtree,audit.path)
        audit.engine=Engine(audit,cash='1000')
        audit.fleet=StrategyFleet(audit.engine,[])
        audit.durability_log_at=float('inf')
        audit.begin();audit.engine.refill(D(1));audit.flush()
        profile=audit.durability_profile
        self.assertEqual(profile['commits'],1)
        self.assertEqual(profile['audit_and_extra_rows'],1)
        self.assertEqual(profile['command_rows'],0)
        # Tiny test checkpoints are intentionally inlined; production-sized
        # checkpoints instead contribute their compressed transport byte size.
        self.assertEqual(profile['checkpoint_bytes'],0)
        self.assertEqual(profile['inline_checkpoint_commits'],1)
        self.assertGreater(profile['prepare_ms'],0)
        self.assertGreaterEqual(profile['total_write_ms'],0)
        self.assertGreaterEqual(profile['upsert_ms'],0)
        self.assertGreaterEqual(profile['transaction_finalize_ms'],0)
        audit.begin();audit.engine.refill(D(1));audit.flush()
        self.assertEqual(audit.durability_profile['commits'],2)
        self.assertEqual(audit.rows_written,4)

        before=dict(audit.durability_profile)
        store.pool.connection.side_effect=RuntimeError('database unavailable')
        audit.begin();audit.engine.refill(D(1))
        with self.assertRaisesRegex(RuntimeError,'database unavailable'):
            audit.flush()
        self.assertEqual(dict(audit.durability_profile),before)
        self.assertEqual(audit.commits,2)

    async def test_identical_compressed_checkpoint_skips_only_redundant_upsert(self):
        from unittest.mock import MagicMock, patch
        from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint
        from services.paper_demo.shadow.storage import KEY, entry
        audit=self.audit();audit.store.pool.connection.return_value=MagicMock()
        audit.durability_log_at=float('inf')
        payload=pack_checkpoint(dict(wallet=dict(cash='1000', padding='x'*100000)),
                                threshold=0,binary=True)
        events=lambda:([entry(KEY,{},payload),
                         entry('demo/shadow/event/'+str(id(object())),{},dict(event='TEST'))],
                        [],[dict(event='TEST')])
        cursor=audit.store.pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        with patch('builtins.print'):
            audit.write(events())
            audit.write(events())
        # First commit contains checkpoint and event; second contains only its
        # fresh audit event. Nothing in the evidence stream is discarded.
        self.assertEqual(cursor.executemany.call_count,2)
        self.assertEqual([len(c.args[1]) for c in cursor.executemany.call_args_list],[2,1])
        self.assertEqual(audit.durability_profile['checkpoint_upserts'],1)
        self.assertEqual(audit.durability_profile['checkpoint_unchanged_skips'],1)
        self.assertGreater(audit.durability_profile['checkpoint_bytes_avoided'],0)
        self.assertEqual(audit.rows_written,3)
        # Force periodic durability rewrite without sleeping 30 seconds.
        audit.committed_checkpoint_at=-1e9
        with patch('builtins.print'):audit.write(events())
        self.assertEqual(len(cursor.executemany.call_args.args[1]),2)
        self.assertEqual(audit.durability_profile['checkpoint_upserts'],2)

    async def test_changed_checkpoint_and_failed_commit_never_skip_persistence(self):
        from unittest.mock import MagicMock,patch
        from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint
        from services.paper_demo.shadow.storage import KEY,entry
        audit=self.audit();audit.store.pool.connection.return_value=MagicMock()
        audit.durability_log_at=float('inf')
        def prepared(cash):
            payload=pack_checkpoint(dict(wallet=dict(cash=cash,padding='x'*100000)),
                                    threshold=0,binary=True)
            return ([entry(KEY,{},payload)],[],[])
        with patch('builtins.print'):
            audit.write(prepared('1000'))
        original_signature=audit.committed_checkpoint_signature
        audit.store.pool.connection.side_effect=RuntimeError('database unavailable')
        with self.assertRaisesRegex(RuntimeError,'database unavailable'):
            audit.write(prepared('1001'))
        self.assertEqual(audit.committed_checkpoint_signature,original_signature)
        audit.store.pool.connection.side_effect=None
        with patch('builtins.print'):
            audit.write(prepared('1001'))
        self.assertNotEqual(audit.committed_checkpoint_signature,original_signature)
        self.assertEqual(audit.durability_profile['checkpoint_upserts'],2)
        self.assertEqual(audit.durability_profile['checkpoint_unchanged_skips'],0)

    async def test_event_kind_attribution_is_bounded_without_losing_audit_rows(self):
        import json
        from unittest.mock import MagicMock,patch
        audit=self.audit()
        audit.store.pool.connection.return_value=MagicMock()
        audit.begin()
        for i in range(20):
            audit.log(1000,'TEST_EVENT_'+str(i),audit.engine.wallet)
        with patch('builtins.print') as output:
            audit.flush()
        events=[json.loads(call.args[0]) for call in output.call_args_list
                if call.args and isinstance(call.args[0],str) and
                'shadow_durability_cost' in call.args[0]]
        self.assertEqual(len(events),1)
        report=events[0]
        self.assertEqual(report['commits'],1)
        self.assertEqual(report['audit_and_extra_rows'],20)
        self.assertEqual(len(report['event_kinds']),16)
        self.assertEqual(report['event_kinds_other'],4)
        self.assertEqual(sum(report['event_kinds'].values())+report['event_kinds_other'],20)
        cursor=audit.store.pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.executemany.assert_called_once()  # one unchanged checkpoint row
        self.assertEqual(len(cursor.executemany.call_args.args[1]),1)
        cursor.execute.assert_called_once()  # one 20-event SQL statement
        self.assertEqual(len(cursor.execute.call_args.args[1]),20*4)
        self.assertEqual(report['bulk_event_rows'],20)
        self.assertEqual(report['bulk_event_groups'],1)

    async def test_checkpoint_preparation_leaves_socket_loop_responsive(self):
        audit=self.audit();started=threading.Event();release=threading.Event()
        original=audit.prepare
        def prepare(records):
            started.set()
            if not release.wait(2):raise RuntimeError('test release timeout')
            return original(records)
        audit.prepare=prepare;audit.write=Mock()
        audit.begin();audit.engine.refill(D(1))
        task=asyncio.create_task(audit.flush_async())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,1))
            # This coroutine must run while preparation is still waiting.
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set();await asyncio.wait_for(task,2)
            audit.write.assert_called_once()
        finally:
            release.set();await asyncio.gather(task,return_exceptions=True)

    async def test_concurrent_discovery_cannot_mutate_frozen_checkpoint_cache(self):
        audit=self.audit();discovery=dict(cursor='before',candidates={'one':{'score':1}})
        audit.experiments=SimpleNamespace(maker_discovery=discovery,state=lambda:dict(_maker_discovery=discovery))
        started=threading.Event();release=threading.Event();original=audit.prepare
        def prepare(records):
            started.set()
            if not release.wait(2):raise RuntimeError('test release timeout')
            return original(records)
        audit.prepare=prepare;audit.write=Mock();audit.begin();audit.engine.refill(D(1))
        task=asyncio.create_task(audit.flush_async())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,1))
            discovery['cursor']='after';discovery['candidates']['two']={'score':2}
            release.set();await asyncio.wait_for(task,2)
            payload=audit.write.call_args.args[0][0][0][2].obj
            self.assertEqual(payload['experiments']['_maker_discovery'],dict(cursor='before',candidates={'one':{'score':1}}))
            self.assertEqual(discovery['cursor'],'after')
            self.assertFalse(hasattr(audit,'_frozen_discovery'))
        finally:
            release.set();await asyncio.gather(task,return_exceptions=True)

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

"""Production stream recovery must stay scoped and preserve invalid-cycle evidence."""
import asyncio
import json
import unittest
from decimal import Decimal as D
from unittest.mock import Mock, patch, AsyncMock
from services.paper_demo.shadow.core import Engine, FeePolicy
from services.paper_demo.shadow.runner import ForwardRun
from services.paper_demo.shadow.host import HostedRun


class InputRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.run=object.__new__(ForwardRun)
        self.engine=self.run.engine=Engine(Mock())
        self.engine.advance(1000)
        for ticker in ('BTC','WTI'):
            self.engine.add_market(dict(ticker=ticker,close=1900),FeePolicy())
            self.engine.books[ticker].valid=True
        self.engine.audit.reset_mock()

    def test_bad_book_does_not_invalidate_an_unrelated_market(self):
        payload=dict(msg=dict(market_ticker='BTC'))
        self.run.reject_input('kalshi',payload,ValueError('negative depth'))
        self.assertFalse(self.engine.books['BTC'].valid)
        self.assertTrue(self.engine.books['WTI'].valid)
        self.assertTrue(self.engine.wallet.stat('WTI').valid)
        self.assertEqual(self.engine.audit.log.call_args.kwargs['reason'],'negative depth')

    def test_same_gap_does_not_repeat_cancel_or_audit(self):
        order=self.engine.place('BTC','yes','buy',D(1),D('.1'))
        self.engine.data_gap('BTC','negative depth')
        count=len(self.engine.pending);self.engine.audit.reset_mock()
        for _ in range(10):self.engine.data_gap('BTC','negative depth')
        self.assertEqual(len(self.engine.pending),count)
        self.engine.audit.log.assert_not_called()
        self.assertEqual(self.engine.orders[order].remaining,1)

    def test_repeated_gap_after_fresh_snapshot_does_not_repeat_audit_or_revalidate_cycle(self):
        self.engine.data_gap('BTC','negative depth')
        self.engine.books['BTC'].valid=True
        self.engine.audit.reset_mock()
        self.engine.data_gap('BTC','negative depth')
        self.engine.audit.log.assert_not_called()
        self.assertFalse(self.engine.wallet.stat('BTC').valid)

    def test_resnapshot_outage_loop_has_bounded_gap_and_cancel_writes(self):
        ident=self.engine.place('BTC','yes','buy',D(1),D('.1'))
        self.engine.audit.reset_mock()
        for i in range(1000):
            self.engine.books['BTC'].valid=True
            self.engine.data_gap('BTC','invalid/stale spot' if i%2 else 'market/spot data stale')
        events=[call.args[1] for call in self.engine.audit.log.call_args_list]
        self.assertEqual(events.count('DATA_GAP'),2)
        self.assertEqual(events.count('CANCEL_SUBMITTED'),1)
        self.assertEqual(sum(item[2]=='cancel' for item in self.engine.pending),1)
        self.engine.advance(1001)
        self.assertIn(self.engine.orders[ident].status,('cancelled','rejected'))
        self.assertFalse(self.engine.wallet.stat('BTC').valid)

    def test_spot_gap_explicitly_invalidates_shared_dependency(self):
        self.engine.spot.at=999
        self.run.reject_input('spot',{},ValueError('invalid/stale spot'))
        self.assertFalse(self.engine.books['WTI'].valid)
        self.assertEqual(self.engine.spot.at,0)
        self.assertEqual(self.engine.audit.log.call_args.kwargs['reason'],'invalid/stale spot')

    def test_unexpected_exception_text_cannot_leak_payload(self):
        self.run.reject_input('kalshi',dict(msg=dict(market_ticker='BTC')),ValueError('private secret'))
        self.assertEqual(self.engine.audit.log.call_args.kwargs['reason'],'malformed kalshi event')


class HostedConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_backpressure_cannot_reorder_producer_timestamps(self):
        run=object.__new__(ForwardRun);blocked=asyncio.Event();release=asyncio.Event();items=[]
        class Queue:
            async def put(self,item):
                if item[1]=='older':blocked.set();await release.wait()
                items.append(item)
        run.queue=Queue()
        with patch('services.paper_demo.shadow.runner.time.time',side_effect=[1000,1001]):
            older=asyncio.create_task(run.put('clock','older'));await blocked.wait()
            newer=asyncio.create_task(run.put('clock','newer'));await asyncio.sleep(0)
            self.assertEqual(items,[])
            release.set();await asyncio.gather(older,newer)
        self.assertEqual([x[1] for x in items],['older','newer'])
        self.assertEqual([x[2] for x in items],[1000,1001])

    async def test_buffered_burst_yields_to_socket_task_without_reordering(self):
        run=object.__new__(HostedRun)
        run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.prepare_fees=lambda source,payload,now:payload
        seen=[];socket_observed=[]
        def handle(source,payload,now):
            seen.append(payload['n'])
            if len(seen)==384:run.done.set()
        run.engine.handle=handle
        for n in range(384):await run.queue.put(('clock',{'n':n},1000+n*.01))
        async def socket_reader():socket_observed.append(len(seen))
        reader=asyncio.create_task(socket_reader())
        await run.consume();await reader
        self.assertEqual(seen,list(range(384)))
        self.assertLess(socket_observed[0],384)
        self.assertGreaterEqual(run.audit.flush.call_count,3)
        self.assertLess(run.audit.flush.call_count,384)

    async def test_failed_batch_does_not_acknowledge_uncertain_inputs(self):
        run=object.__new__(HostedRun)
        run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.prepare_fees=lambda source,payload,now:payload
        run.audit.flush.side_effect=RuntimeError('database commit failed')
        for n in range(4):await run.queue.put(('clock',{},1000+n*.01))
        with self.assertRaises(RuntimeError):await run.consume()
        run.audit.abort.assert_called_once()
        self.assertEqual(run.queue._unfinished_tasks,4)

    async def test_consumer_keeps_specific_error_and_only_affected_book(self):
        run=object.__new__(HostedRun)
        run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Engine(Mock());run.engine.advance(1000)
        run.verified_fees=Mock();run.verified_fees.schedule.return_value=('quadratic',1)
        for t in ('BTC','WTI'):
            run.engine.add_market(dict(ticker=t,close=1900),FeePolicy())
            run.engine.books[t].valid=True
        def rejected(*args):
            run.done.set()
            raise ValueError('stale book event')
        run.engine.handle=rejected
        await run.queue.put(('kalshi',dict(msg=dict(market_ticker='BTC')),1001))
        await run.consume()
        self.assertTrue(run.engine.books['WTI'].valid)
        self.assertFalse(run.engine.books['BTC'].valid)
        run.audit.flush.assert_called_once()


class SocketRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscriptions_updates_and_resnapshots_use_current_single_sid(self):
        run=object.__new__(ForwardRun);run.done=asyncio.Event();run.signer=Mock()
        run.engine=Engine(Mock());run.selected={'a':'BTC'}
        for t in ('BTC','WTI'):
            run.engine.add_market(dict(ticker=t,close=1900),FeePolicy())
        run.engine.books['BTC'].sid=999  # Restored connection's obsolete SID.
        commands=[];events=[];step=0;self_outer=self
        class Socket:
            async def send(self,raw):commands.append(json.loads(raw))
            async def recv(self):
                nonlocal step
                step+=1
                if step==1:return json.dumps(dict(type='subscribed',msg=dict(channel='orderbook_delta',sid=11)))
                if step==2:return json.dumps(dict(type='subscribed',msg=dict(channel='trade',sid=12)))
                if step==3:
                    # The restored/paused copy still has obsolete SID 999, but
                    # its repair must already target the current book SID 11.
                    self_outer.assertTrue(any(c['cmd']=='update_subscription' and c['params'].get('action')=='get_snapshot' and c['params']['sid']==11 and 'BTC' in c['params']['market_tickers'] for c in commands))
                    run.selected['b']='WTI'
                    run.engine.books['BTC'].sid=11
                    return json.dumps(dict(type='ok'))
                if step==4:
                    run.done.set()
                    return json.dumps(dict(type='ok'))
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        async def put(source,payload):events.append((source,payload))
        run.put=put
        with patch('services.paper_demo.shadow.runner.connect',return_value=Socket()),patch('services.paper_demo.shadow.runner.asyncio.sleep',new=AsyncMock()):
            await run.kalshi()
        self.assertEqual([c['params']['channels'] for c in commands if c['cmd']=='subscribe'],
                         [['market_lifecycle_v2'],['orderbook_delta'],['trade']])
        updates=[c['params'] for c in commands if c['cmd']=='update_subscription']
        self.assertEqual({u['sid'] for u in updates if u['action']=='add_markets'},{11,12})
        self.assertTrue(any(u['action']=='get_snapshot' for u in updates))
        self.assertTrue(all(u['sid'] in (11,12) and 'sids' not in u for u in updates))

    async def test_server_rejections_back_off_even_when_handshake_succeeds(self):
        run=object.__new__(ForwardRun);run.done=asyncio.Event();run.signer=Mock()
        run.selected={};run.engine=Engine(Mock());delays=[]
        class Socket:
            async def send(self,raw):pass
            async def recv(self):return json.dumps(dict(type='error',id=1,msg=dict(code=11)))
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        async def put(*args):pass
        async def sleep(delay):
            delays.append(delay)
            if len(delays)==3:run.done.set()
        run.put=put
        with patch('services.paper_demo.shadow.runner.connect',return_value=Socket()),patch('services.paper_demo.shadow.runner.asyncio.sleep',new=sleep):
            with self.assertLogs('shadow',level='WARNING') as logs:await run.kalshi()
        self.assertEqual(delays,[.25,.5,1])
        self.assertIn('code=11 request=1',logs.output[0])

class NonblockingHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_pong_wait_never_stops_draining_application_messages(self):
        run=object.__new__(ForwardRun);run.done=asyncio.Event();run.signer=Mock()
        run.engine=Engine(Mock());run.selected={};run.heartbeat_interval=0;seen=[]
        class Socket:
            def __init__(self):self.steps=0;self.pending=None
            async def send(self,raw):pass
            async def ping(self):
                self.pending=asyncio.get_running_loop().create_future();return self.pending
            async def recv(self):
                self.steps+=1
                if self.steps==1:return json.dumps(dict(type='subscribed',msg=dict(channel='orderbook_delta',sid=1)))
                if self.pending and not self.pending.done():self.pending.set_result(.01)
                if self.steps>=3:run.done.set()
                return json.dumps(dict(type='ok'))
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        async def put(source,payload):seen.append(source)
        run.put=put
        with patch('services.paper_demo.shadow.runner.connect',return_value=Socket()):
            await asyncio.wait_for(run.kalshi(),.2)
        self.assertIn('book_heartbeat',seen)

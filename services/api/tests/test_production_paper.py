"""Production paper rules and real-Postgres invariants. No real order calls."""
import json,time,unittest,threading,os
from uuid import uuid4
from unittest.mock import Mock,patch
import httpx
from cryptography.fernet import Fernet
from services.paper_demo.model import D,charge,sweep,eligible_trade,queue_ahead
from services.paper_demo.ledger import Ledger,get,wire
from services.paper_demo.exchange import ProductionData,PaperExchange,Fees
from services.demo.exchange import ExchangeFailure
from services.api.tests import test_demo_postgres as fixtures
from services.api.tests.test_demo_engine import config

class PaperRules(unittest.TestCase):
    def test_fee_rounding_uses_current_centicent_formula_and_verified_maker_schedule(self):
        self.assertEqual(charge('.5',1,'quadratic',1),(D('.5'),D('0')))
        self.assertEqual(charge('.5',1,'quadratic_with_maker_fees',1),(D('.5'),D('.0044')))
        self.assertEqual(charge('.5',1,'quadratic',1,False),(D('.5'),D('.0175')))
        self.assertEqual(charge('.03',D('.5'),'quadratic_with_maker_fees',2),(D('.015'),D('.0006')))
        with self.assertRaises(ValueError):charge('.5',1,'unknown',1)
    def test_immediate_fills_walk_asks_and_bids_without_mid_or_excess_volume(self):
        book=dict(yes={D('.58'):D(3),D('.57'):D(5)},no={D('.40'):D(10),D('.39'):D(40),D('.38'):D(20)})
        fills,remaining=sweep(book,'yes','entry','.61',100)
        self.assertEqual(fills,[(D('.60'),D(10)),(D('.61'),D(40))]);self.assertEqual(remaining,50)
        self.assertEqual(sweep(book,'yes','exit','.57',10),([(D('.58'),D(3)),(D('.57'),D(5))],D(2)))
        self.assertEqual(sweep(book,'no','entry','.42',10),([(D('.42'),D(3))],D(7)))
    def test_resting_orders_require_later_matching_aggressor_trade(self):
        order=dict(side='yes',kind='entry',active_at=100.25,expires=400,price_dollars='.03')
        trade=dict(ts_ms=101000,yes_price_dollars='.03',no_price_dollars='.97',count_fp='2.50',taker_outcome_side='no')
        self.assertEqual(eligible_trade(order,trade,101),D('2.50'))
        for changed in [dict(ts_ms=100000),dict(ts_ms=110000),dict(taker_outcome_side='yes'),dict(is_block_trade=True),dict(count_fp='NaN'),dict(yes_price_dollars='.04')]:
            with self.subTest(changed=changed):self.assertIsNone(eligible_trade(order,dict(trade,**changed),101))
    def test_read_transport_and_paper_adapter_cannot_send_production_writes(self):
        seen=[];data=ProductionData(client=httpx.Client(transport=httpx.MockTransport(lambda r:(seen.append(r),httpx.Response(200,json={}))[1])))
        for method in ['POST','PUT','PATCH','DELETE']:
            with self.assertRaises(ExchangeFailure):data.call(method,'/portfolio/events/orders')
        with self.assertRaises(ExchangeFailure):data.call('GET','/portfolio/balance')
        data.call('GET','/markets');self.assertEqual([r.method for r in seen],['GET']);self.assertIn('external-api.kalshi.com',str(seen[0].url));data.close()
        ex=PaperExchange(Mock(),Mock(),client=httpx.Client(transport=httpx.MockTransport(lambda r:self.fail('Paper order routes cannot use HTTP'))))
        with self.assertRaises(ExchangeFailure):ex.call('POST','/portfolio/events/orders',body={})
        ex.close()
    def test_fee_schedule_honors_effective_event_override_and_clear(self):
        now=time.time();stamp=lambda dt:__import__('datetime').datetime.fromtimestamp(now+dt,__import__('datetime').timezone.utc).isoformat()
        fees=Fees(Mock());fees.cache['t']=dict(at=now,base=('quadratic',1),changes=[],events=[dict(scheduled_ts=stamp(-10),fee_type_override='quadratic_with_maker_fees',fee_multiplier_override=2),dict(scheduled_ts=stamp(10),fee_type_override=None,fee_multiplier_override=None)])
        self.assertEqual(fees.schedule('t',now),('quadratic_with_maker_fees',2));self.assertEqual(fees.schedule('t',now+11),('quadratic',1))
        with self.assertRaises(ExchangeFailure):fees.schedule('absent',now)
    def test_queue_includes_better_and_same_price_visible_orders(self):
        book=dict(yes={D('.03'):D(5),D('.04'):D(2)},no={D('.90'):D(3),D('.91'):D(4)})
        self.assertEqual(queue_ahead(book,'yes','entry','.03'),7)
        self.assertEqual(queue_ahead(book,'yes','exit','.10'),7)

class PaperStream(unittest.TestCase):
    def test_production_stream_subscribes_only_to_market_channels_and_yields_after_fill(self):
        from services.paper_demo.runtime import PaperWorker
        from services.api.tests.test_demo_engine import FakeStore,NOW
        messages=[dict(type='subscribed',msg=dict(channel='orderbook_delta',sid=2)),dict(type='subscribed',msg=dict(channel='trade',sid=3)),dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=NOW*1000,msg=dict(market_ticker='t',clock=1,yes_dollars_fp=[['0.02','10']],no_dollars_fp=[['0.96','10']])),dict(type='trade',sid=3,seq=1,msg=dict(market_ticker='t',trade_id='trade',ts=NOW,count_fp='1',yes_price_dollars='.03',no_price_dollars='.97',taker_outcome_side='no'))]
        class Socket:
            received_at=NOW
            def __init__(self):self.sent=[]
            def send(self,message):self.sent.append(json.loads(message))
            def recv(self,**kwargs):
                if not messages:raise TimeoutError()
                return json.dumps(messages.pop(0))
            def close(self):pass
        socket=Socket();exchange=PaperExchange(FakeStore(),Mock(),client=httpx.Client(transport=httpx.MockTransport(lambda r:self.fail('No REST expected'))));exchange.ledger=Mock();exchange.observe_trade=Mock(return_value=True)
        worker=PaperWorker(exchange.store,exchange,threading.Event(),lambda:None);worker.quotes={'t':dict(close=NOW+900,status='active',series='KXBTC15M')}
        with patch('services.demo.runtime.time.time',return_value=NOW),patch('websockets.sync.client.connect',return_value=socket) as connect,patch('services.demo.runtime.BufferedSocket',side_effect=lambda s:s):worker.stream(False)
        self.assertEqual(connect.call_args.args[0],'wss://external-api-ws.kalshi.com/trade-api/ws/v2')
        channels=[channel for message in socket.sent for channel in message.get('params',{}).get('channels',[])]
        self.assertEqual(channels,['orderbook_delta','trade']);self.assertNotIn('fill',channels);self.assertNotIn('user_orders',channels)
        self.assertEqual(worker.paper_trade_sid,3);self.assertEqual(worker.stream_event_revision,1);self.assertFalse(worker.recovered);self.assertEqual(worker.last_reconcile,0)
        self.assertTrue(exchange.books['t']);exchange.close()

@unittest.skipUnless(fixtures.URL,'Disposable PostgreSQL is required')
class PaperPostgres(unittest.TestCase):
    setUpClass=classmethod(fixtures.DemoPostgres.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.DemoPostgres.tearDownClass.__func__)
    setUp=fixtures.DemoPostgres.setUp
    tearDown=fixtures.DemoPostgres.tearDown
    def scenario(self):
        self.now=time.time();self.ledger=Ledger(self.demo);self.ledger.initialize(10000)
        self.q=dict(bid=2,ask=4,at=self.now,close=self.now+900,book_verified=True,book_ready=True,exchange_index=2)
        self.book=dict(yes={D('.02'):D(10)},no={D('.96'):D(10)})
    def order(self,quantity=2,side='yes',kind='entry',price=3,**extra):
        intent=dict(client_id=str(uuid4()),ticker='t',side=side,kind=kind,quantity=quantity,price=price,close=self.now+300,**extra)
        result=self.ledger.submit(intent,self.book,self.q,('quadratic',1),self.now)
        return intent,result
    def trade(self,count='1',ts=None,side='no',identifier=None,**extra):
        ts=self.now+1 if ts is None else ts
        trade=dict(trade_id=identifier or str(uuid4()),market_ticker='t',ts_ms=ts*1000,yes_price_dollars='.03',no_price_dollars='.97',taker_outcome_side=side,count_fp=count);trade.update(extra)
        return self.ledger.trade(trade,self.q,ts)
    def test_shared_volume_fractional_fills_and_deduplication_survive_restart(self):
        self.scenario();a,_=self.order();b,_=self.order();identifier=str(uuid4())
        self.assertTrue(self.trade('2.50',identifier=identifier))
        orders=self.ledger.orders();self.assertEqual(sum(D(o['filled']) for o in orders),D('2.50'))
        self.ledger=Ledger(self.demo);self.assertFalse(self.trade('2.50',identifier=identifier))
        self.assertEqual(self.ledger.positions(),[dict(ticker='t',position_fp='2.50')])
        with self.store.pool.connection() as c:self.assertEqual(D(get(c,'cash')['dollars']),D('99.925'))
    def test_visible_queue_and_latency_prevent_instant_touch_fills(self):
        self.scenario();self.book['yes'][D('.03')]=D(5);a,_=self.order()
        self.assertFalse(self.trade('10',ts=self.now+.1))
        self.assertFalse(self.trade('3'));self.assertFalse(self.trade('2',ts=self.now+1.1))
        self.assertTrue(self.trade('1',ts=self.now+1.2));self.assertEqual(self.ledger.orders()[0]['filled'],'1')
    def test_gap_freezes_fills_and_snapshot_restores_conservative_queue(self):
        self.scenario();self.order();self.ledger.gap()
        self.assertFalse(self.trade('5'))
        self.book['yes'][D('.03')]=D(3);self.ledger.requeue('t',self.book)
        self.assertFalse(self.trade('3'));self.assertTrue(self.trade('1',ts=self.now+1.1))
    def test_post_only_crossing_and_overreservation_are_rejected(self):
        self.scenario()
        with self.assertRaises(ExchangeFailure):self.order(price=4)
        self.order(quantity=3000)
        with self.assertRaises(ExchangeFailure):self.order(quantity=1000)
        self.assertEqual(len(self.ledger.orders()),1)
    def test_cancel_latency_allows_pre_cancel_fill_and_blocks_later_print(self):
        self.scenario();_,result=self.order()
        self.ledger.cancel(result['order_id'],self.now+1)
        self.assertTrue(self.trade('1',ts=self.now+1.1))
        self.assertFalse(self.trade('1',ts=self.now+1.3));self.ledger.expire(self.now+1.3)
        self.assertEqual(self.ledger.orders()[0]['status'],'canceled');self.assertEqual(self.ledger.orders()[0]['filled'],'1')
    def test_sell_requires_held_inventory_and_settlement_is_exactly_once(self):
        self.scenario();entry,_=self.order();self.trade('2')
        self.order(quantity=1,kind='exit',parent=entry['client_id'])
        with self.assertRaises(ExchangeFailure):self.order(quantity=2,kind='exit',parent=entry['client_id'])
        self.assertTrue(self.trade('1',side='yes',ts=self.now+1.1))
        self.ledger.settle(dict(ticker='t',status='finalized',result='yes'))
        self.ledger.settle(dict(ticker='t',status='finalized',result='yes'))
        self.assertEqual(self.ledger.positions(),[])
        with self.store.pool.connection() as c:self.assertEqual(D(get(c,'cash')['dollars']),D('100.97'))
    def test_buying_opposite_side_nets_cash_once(self):
        self.scenario();self.order();self.trade('2')
        self.q.update(bid=96,ask=98);self.book=dict(yes={D('.96'):D(10)},no={D('.02'):D(10)})
        self.order(quantity=2,side='no',price=3)
        self.trade('2',side='yes',ts=self.now+1.1,yes_price_dollars='.97',no_price_dollars='.03')
        self.assertEqual(self.ledger.positions(),[])
        with self.store.pool.connection() as c:self.assertEqual(D(get(c,'cash')['dollars']),D('101.88'))
    def test_fractional_flat_positions_do_not_accumulate_in_active_snapshots(self):
        from services.paper_demo.ledger import rows
        self.scenario();entry,_=self.order(quantity=2.5);self.trade('2.50')
        self.order(quantity=2.5,kind='exit',parent=entry['client_id']);self.trade('2.50',side='yes',ts=self.now+1.1)
        with self.store.pool.connection() as c:self.assertEqual(rows(c,'position'),[])
    def test_cancel_retirement_works_with_research_job_update_permission_only(self):
        from psycopg import sql
        from services.paper_demo.ledger import save,rows
        self.scenario();self.order();order=self.ledger.orders()[0];order.update(status='canceled',remaining='0')
        role=sql.Identifier('paper_test_'+uuid4().hex)
        with self.store.pool.connection() as c:
            c.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(role))
            c.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role))
            c.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON public.research_job TO {}').format(role))
        try:
            with self.store.pool.connection() as c:
                c.execute(sql.SQL('SET LOCAL ROLE {}').format(role));save(c,order)
                self.assertEqual(rows(c,'resting'),[])
        finally:
            with self.store.pool.connection() as c:
                c.execute(sql.SQL('DROP OWNED BY {}').format(role));c.execute(sql.SQL('DROP ROLE {}').format(role))
    def test_subcent_fees_are_deducted_without_rounding_to_whole_cents(self):
        self.scenario();intent=dict(client_id=str(uuid4()),ticker='t',side='yes',kind='entry',quantity=1,price=3,close=self.now+300)
        self.ledger.submit(intent,self.book,self.q,('quadratic_with_maker_fees',1),self.now);self.trade('1')
        with self.store.pool.connection() as c:self.assertEqual(D(get(c,'cash')['dollars']),D('99.9694'))
        self.assertEqual(D(self.ledger.orders()[0]['fees']),D('.0006'))
    def test_transition_preserves_history_and_starts_new_statistics_once(self):
        from services.paper_demo.transition import migrate
        bot=str(uuid4());self.demo.put('bot/'+bot,dict(desired='running'),parameters=dict(config=config(),revision=3,settings_revision=4))
        self.demo.put('account',dict(equity_cents=12345));self.demo.event('settlement','Previous result',bot=bot,details=dict(realized_cents=900))
        with patch('services.paper_demo.transition.credentials',return_value=None):migrate(self.demo,{},lambda:None);migrate(self.demo,{},lambda:None)
        self.assertEqual(self.demo.get('bot/'+bot)['parameters']['revision'],4);self.assertEqual(self.demo.get('bot/'+bot)['progress']['desired'],'running')
        self.assertEqual(self.demo.get('account')['progress']['equity_cents'],12345)
        current=self.client.get('/demo/workspace').json();self.assertEqual(current['engine']['source'],'production_paper')
        previous=self.client.get('/demo/legacy').json();self.assertTrue(any(r['progress'].get('message')=='Previous result' for r in previous['items']))
        self.assertFalse(any(r['progress'].get('message')=='Previous result' for r in self.demo.rows('event/')))
    def test_virtual_funding_never_uses_real_account_and_is_not_profit(self):
        self.scenario();self.demo.put('engine',dict(source='production_paper'))
        self.demo.put('account',dict(equity_cents=10000,cash_cents=10000,position_value_cents=0,at=self.now))
        self.demo.put('equity/initial',dict(at=self.now-10,value=10000))
        response=self.client.post('/demo/virtual-funds',json=dict(amount_cents=100));self.assertEqual(response.status_code,200,response.text)
        current=self.client.get('/demo/workspace').json();self.assertEqual(current['account_change_cents'],0)
        with self.store.pool.connection() as c:self.assertEqual(D(get(c,'cash')['dollars']),D('101'))
    def test_production_read_connection_is_separate_encrypted_and_owner_only(self):
        from services.api.tests.test_live_execution import signer
        from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption
        key=signer();pem=key.key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()).decode();vault=Fernet.generate_key().decode()
        with patch.dict(os.environ,DEMO_VAULT_KEY=vault),patch('services.paper_demo.exchange.ProductionData') as data:
            data.return_value.call.return_value=dict(api_keys=[dict(api_key_id=key.identifier,scopes=['read'])])
            response=self.client.post('/demo/connection',json=dict(key_id=key.identifier,private_key=pem))
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNotNone(self.demo.get('paper-credentials'));self.assertIsNone(self.demo.get('credentials'))
            self.assertNotIn(pem,json.dumps(self.demo.get('paper-credentials')['progress']))
        self.client.headers.pop('x-csrf-token');self.assertEqual(self.client.post('/demo/virtual-funds',json=dict(amount_cents=1)).status_code,403)

import json,queue,threading,time,unittest
from unittest.mock import patch,Mock
from services.demo.stream_buffer import BufferedSocket,close_details
from services.demo.watchlist import select_markets
from services.demo.runtime import Worker,quote as parse_quote
from services.demo.engine import candidates,qualifies
from services.demo.exchange import ExchangeFailure
from services.api.tests.test_demo_engine import NOW,FakeStore,bot,quote

class Connection:
    def __init__(self,target):self.messages=queue.Queue();self.count=0;self.target=target;self.drained=threading.Event()
    def recv(self,timeout=1):
        try:message=self.messages.get(timeout=timeout)
        except queue.Empty:raise TimeoutError()
        self.count+=1
        if self.count>=self.target:self.drained.set()
        return message
    def close(self):pass

class Receiver(unittest.TestCase):
    def test_reader_drains_while_rest_consumer_is_busy_and_preserves_every_message(self):
        connection=Connection(30);stream=BufferedSocket(connection)
        try:
            for index in range(30):connection.messages.put(str(index))
            self.assertTrue(connection.drained.wait(2))
            # No consumer recv call was made while the independent reader ran.
            self.assertEqual([stream.recv(timeout=1) for _ in range(30)],[str(i) for i in range(30)])
            self.assertIsNotNone(stream.received_at);self.assertEqual(stream.stats()['bytes'],0)
        finally:stream.close()
        self.assertFalse(stream.thread.is_alive())
    def test_overflow_invalidates_instead_of_silently_dropping_a_delta(self):
        connection=Connection(3);stream=BufferedSocket(connection,max_messages=2)
        try:
            for index in range(3):connection.messages.put(str(index))
            self.assertTrue(connection.drained.wait(2))
            with self.assertRaises(ExchangeFailure) as caught:stream.recv(timeout=1)
            self.assertEqual(caught.exception.code,'stream_backlog')
        finally:stream.close()
    def test_close_diagnostics_never_expose_server_reason(self):
        error=type('Error',(),{'sent':type('Frame',(),dict(code=1011,reason='keepalive ping timeout PRIVATE'))(),'rcvd':None})()
        self.assertEqual(close_details(error),dict(sent_code=1011,received_code=None,close_cause='keepalive_timeout'))

class Sports(unittest.TestCase):
    def market(self,**changes):
        row=dict(ticker='KXNBAGAME-TEST',series_ticker='KXNBAGAME',status='active',yes_bid_dollars='.60',yes_ask_dollars='.65',
            close_time=NOW+3*86400,expected_expiration_time=NOW+200,can_close_early=True)
        row.update(changes);return row
    def test_expected_finish_qualifies_today_without_shortening_existing_position_protection(self):
        ticker,q=parse_quote(self.market(),NOW)
        self.assertEqual(q['entry_close'],NOW+200);self.assertEqual(q['close'],NOW+3*86400)
        b=bot();b['config']['squares'][0]['asset']='sports'
        self.assertTrue(qualifies(b['config']['squares'][0],q,'yes',NOW,'ask'))
        self.assertEqual(len(candidates([b],{ticker:q},{},NOW)),1)
        self.assertEqual(candidates([b],{ticker:q},{},NOW+201),[])
        # The real market remains open for protective exits after estimated finish.
        self.assertGreater(q['close'],NOW+201)
    def test_entry_expiry_uses_expected_finish_while_market_deadline_is_retained(self):
        ticker,q=parse_quote(self.market(),NOW)
        b=bot();b['config']['squares'][0]['asset']='sports'
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[b];worker.quotes={ticker:q}
        worker.recovered=True;worker.last_reconcile=NOW;worker.account=dict(cash_cents=10000,equity_cents=10000)
        worker.submit=Mock();worker.funding=Mock();worker.funding.ensure.return_value=True
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(worker.submit.call_args.args[0]['close'],NOW+200)
        self.assertEqual(q['close'],NOW+3*86400)

    def test_no_estimate_is_invented_for_fixed_deadline_or_missing_metadata(self):
        for change in [dict(can_close_early=False),dict(expected_expiration_time=None)]:
            _,q=parse_quote(self.market(**change),NOW)
            self.assertEqual(q['entry_close'],q['close'])
    def test_discovery_fetches_sports_without_the_incorrect_24h_hard_close_filter(self):
        class Ex:
            def __init__(self,market):self.market=market;self.params=None
            def call(self,*args,**kwargs):self.params=kwargs['params'];return dict(markets=[self.market])
        ex=Ex(self.market());worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        b=bot();b['config']['squares'][0]['asset']='sports';worker.bots=[b]
        with patch.dict('services.research.reports.SERIES',sports={'KXNBAGAME'}),patch('services.demo.runtime.time.time',return_value=NOW):worker.discover()
        self.assertNotIn('max_close_ts',ex.params);self.assertEqual(worker.quotes['KXNBAGAME-TEST']['at'],0)
    def test_full_crypto_watchlist_cannot_starve_sports_or_drop_existing_holdings(self):
        quotes={f'crypto-{i}':dict(close=NOW+60,entry_close=NOW+60,status='active',series='KXBTC15M') for i in range(100)}
        quotes.update({f'sports-{i}':dict(close=NOW+3*86400,entry_close=NOW+3600,status='active',series='KXNBAGAME') for i in range(30)})
        selected=select_markets(quotes,{'crypto-99'},NOW)
        self.assertEqual(len(selected),100);self.assertIn('crypto-99',selected)
        self.assertEqual(sum(q['series']=='KXNBAGAME' for q in selected.values()),30)
    def test_unfilled_entries_cancel_at_window_end_even_when_prices_are_stale(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);b=bot();b['config']['squares'][0].update(min_minutes=5,max_minutes=10)
        worker.bots=[b];worker.quotes={'t':dict(quote(),at=NOW-30)}
        order=dict(kind='entry',bot=b['id'],revision=1,square=0,ticker='t',close=NOW+1000,status='resting',remaining=1,filled=0,exchange_id='one',side='yes')
        worker.orders=[order];worker.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        worker.cancel.assert_called_once()

class MakerRejection(unittest.TestCase):
    def test_definitive_maker_rejection_preserves_reconciliation_and_waits_for_new_market_quote(self):
        class Ex:
            def submit(self,intent):raise ExchangeFailure('exchange_rejected',False,status=400,reason='post_only')
        worker=Worker(FakeStore(),Ex(),threading.Event(),lambda:None);worker.recovered=True;worker.last_reconcile=NOW
        worker.quotes={'t':dict(quote(),clock=123)}
        intent=dict(client_id='x',ticker='t',bot='bot-1',kind='exit',price=65,quantity=1,side='yes',status='intent',remaining=0,filled=0)
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.submit(intent)
        self.assertEqual(intent['status'],'rejected');self.assertTrue(worker.recovered);self.assertEqual(worker.last_reconcile,NOW)
        self.assertEqual(worker.maker_retries['t'],dict(clock=123,seq=None,after=NOW+.5))
        self.assertEqual(worker.blocked,set())

    def test_quote_retry_gate_keeps_unrelated_market_active_and_requires_new_clock(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[bot()]
        worker.quotes={t:dict(quote(),clock=123) for t in ('t','u')}
        worker.recovered=True;worker.last_reconcile=NOW;worker.account=dict(cash_cents=10000,equity_cents=10000)
        worker.funding=Mock();worker.funding.ensure.return_value=True;worker.submit=Mock()
        worker.maker_retries={'t':dict(clock=123,seq=None,after=NOW+.5)}
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(worker.submit.call_args.args[0]['ticker'],'u')
        worker.submit.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW+1):worker.trade()
        worker.submit.assert_not_called()
        worker.quotes['t']['seq']=124
        with patch('services.demo.runtime.time.time',return_value=NOW+1):worker.trade()
        self.assertEqual(worker.submit.call_args.args[0]['ticker'],'t')

    def test_unaccepted_entry_rearms_with_a_new_attempt_id_without_replaying_ambiguous_writes(self):
        class Ex:
            def submit(self,intent):raise ExchangeFailure('exchange_rejected',False,status=400,reason='post_only')
        worker=Worker(FakeStore(),Ex(),threading.Event(),lambda:None);worker.recovered=True
        worker.quotes={'t':dict(quote(),clock=123,seq=10)}
        worker.states={'bot-1':{'t/0/yes':dict(submitted=True,cycle=1,attempt=0)}}
        intent=dict(client_id='x',ticker='t',bot='bot-1',revision=1,square=0,kind='entry',price=64,quantity=1,side='yes',status='intent',remaining=0,filled=0)
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.submit(intent)
        self.assertFalse(worker.states['bot-1']['t/0/yes']['submitted'])
        self.assertEqual(worker.states['bot-1']['t/0/yes']['attempt'],1)
        self.assertTrue(worker.recovered)

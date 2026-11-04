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

class FundingIsolation(unittest.TestCase):
    def test_unfunded_first_market_cannot_starve_funded_second_market(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.bots=[bot()]
        worker.quotes={t:dict(quote(),exchange_index=i) for t,i in [('t',2),('u',3)]}
        worker.recovered=True;worker.last_reconcile=NOW;worker.account=dict(cash_cents=10000,equity_cents=10000)
        worker.funding=Mock();worker.funding.ensure.side_effect=[False,True];worker.submit=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.trade()
        self.assertEqual(worker.submit.call_args.args[0]['ticker'],'u')
        self.assertFalse(worker.states['bot-1']['t/0/yes']['submitted'])


class StreamResilience(unittest.TestCase):
    def test_ended_book_update_keeps_live_books_and_sequence_validation(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.quotes={'live':quote(),'ended':dict(quote(),close=NOW)}
        worker.subscription={'live'};worker.book_sid=2
        snapshot=dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=NOW*1000,
            msg=dict(market_ticker='live',clock=1,yes_dollars_fp=[['0.50','1']],no_dollars_fp=[['0.40','1']]))
        ended=dict(type='orderbook_delta',sid=2,seq=2,
            msg=dict(market_ticker='ended',clock=2,side='yes',price_dollars='1.00',delta_fp='1'))
        messages=[snapshot,ended]
        class Socket:
            def recv(self,**kwargs):
                if not messages:raise TimeoutError()
                return json.dumps(messages.pop(0))
        worker.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.stream()
        self.assertIn('live',worker.books.books)
        self.assertEqual(worker.sequence[2],2)
        # Bad prices in a still-active market remain a hard feed failure.
        messages.append(dict(ended,seq=3,msg=dict(ended['msg'],market_ticker='live')))
        with patch('services.demo.runtime.time.time',return_value=NOW),self.assertRaises(ExchangeFailure) as caught:
            worker.stream()
        self.assertEqual(caught.exception.code,'stream_book_invalid')

    def test_ordered_prices_survive_clean_exchange_close_and_trigger_controlled_reconnect(self):
        from websockets.frames import Close
        from websockets.exceptions import ConnectionClosedOK
        class CleanClose:
            def __init__(self):self.messages=['first','second','third'];self.closed=threading.Event()
            def recv(self,timeout=1):
                if self.messages:return self.messages.pop(0)
                self.closed.set()
                raise ConnectionClosedOK(Close(1000,''),Close(1000,''),True)
            def close(self):pass
        connection=CleanClose();stream=BufferedSocket(connection)
        try:
            self.assertTrue(connection.closed.wait(2))
            self.assertEqual([stream.recv(timeout=1) for _ in range(3)],['first','second','third'])
            self.assertEqual(stream.stats()['received'],3)
            self.assertEqual(stream.stats()['consumed'],3)
            self.assertEqual(stream.stats()['close_code'],1000)
            with self.assertRaises(ExchangeFailure) as caught:stream.recv(timeout=1)
            self.assertEqual(caught.exception.code,'stream_closed')
        finally:stream.close()

    def test_large_price_burst_drains_all_sequenced_messages_without_dropping_protective_events(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.quotes={'t':quote()};worker.subscription={'t'}
        snapshot=dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=NOW*1000,
            msg=dict(market_ticker='t',clock=1,yes_dollars_fp=[['0.50','1']],no_dollars_fp=[['0.40','1']]))
        updates=[dict(type='orderbook_delta',sid=2,seq=i,sending_ts_ms=NOW*1000,
            msg=dict(market_ticker='t',clock=i,ts_ms=NOW*1000,side='no',
                price_dollars='0.45',delta_fp='0')) for i in range(2,352)]
        messages=[snapshot,*updates]
        class Socket:
            def recv(self,**kwargs):
                if not messages:raise TimeoutError()
                return json.dumps(messages.pop(0))
        worker.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.stream()
        self.assertEqual(len(messages),0)
        self.assertEqual(worker.quotes['t']['seq'],351)

    def test_normal_disconnect_fences_entries_and_reports_duration_until_verified_recovery(self):
        class StreamStore(FakeStore):
            def __init__(self):super().__init__();self.alerts=[];self.cleared=[]
            def alert(self,*a,**kw):self.alerts.append(a)
            def clear_alert(self,key):self.cleared.append(key)
        store=StreamStore()
        exchange=Mock(reads=0,writes=0)
        worker=Worker(store,exchange,threading.Event(),lambda:None)
        worker.quotes={'t':quote()};worker.recovered=True;worker.last_verified=NOW-1
        class Socket:
            def __init__(self):self.closed=False
            def stats(self):return dict(messages=0,peak_messages=50,bytes=0)
            def close(self):self.closed=True
        sock=Socket();worker.socket=sock
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.recover_feed(ExchangeFailure('stream_closed'))
        self.assertTrue(sock.closed);self.assertFalse(worker.recovered)
        self.assertEqual(worker.quotes['t']['at'],0)
        self.assertEqual(worker.stream_disconnect_count,1)
        self.assertEqual(store.saved[-1][1]['state'],'reconnecting')
        self.assertEqual(store.alerts,[])
        worker.recovered=True;worker.socket=Socket();worker.book_sid=2
        worker.quotes={'t':dict(quote(),source='orderbook',book_ready=True,at=NOW+2)}
        with patch('services.demo.runtime.time.time',return_value=NOW+2):
            self.assertTrue(worker.stream_recovered())
        self.assertEqual(worker.stream_recovery_count,1)
        self.assertEqual(worker.stream_outage_since,None)
        self.assertIn('stream',store.cleared)

    def test_extended_unverified_feed_outage_alerts_instead_of_staying_infinite_routine_sync(self):
        class StreamStore(FakeStore):
            def __init__(self):super().__init__();self.alerts=[]
            def alert(self,*a,**kw):self.alerts.append(a)
        store=StreamStore();worker=Worker(store,Mock(reads=0,writes=0),threading.Event(),lambda:None)
        worker.last_verified=NOW-5;worker.stream_outage_since=NOW-30
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.trading_health();worker.trading_health()
        self.assertEqual(len(store.alerts),1)
        self.assertEqual(store.saved[-1][1]['state'],'reconnecting')
        self.assertEqual(store.saved[-1][1]['stream']['outage_seconds'],30)


class IndependentFeedRecovery(unittest.TestCase):
    def test_fresh_verified_prices_clear_outage_even_while_new_order_ownership_is_reconciling(self):
        class Alerts(FakeStore):
            def __init__(self):super().__init__();self.cleared=[]
            def clear_alert(self,key):self.cleared.append(key)
        store=Alerts();worker=Worker(store,Mock(reads=0,writes=0),threading.Event(),lambda:None)
        worker.stream_outage_since=NOW-30
        worker.recovered=False # A recent accepted order is awaiting REST confirmation.
        worker.last_verified=NOW-2
        worker.socket=object();worker.book_sid=2
        worker.quotes={'t':dict(quote(),source='orderbook',book_ready=True,at=NOW)}
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.trading_health()
        self.assertIsNone(worker.stream_outage_since)
        self.assertEqual(worker.stream_recovery_count,1)
        self.assertEqual(store.cleared,['stream'])
        # Do not confuse a healthy feed with verified account ownership.
        self.assertFalse(worker.recovered)
        self.assertEqual(store.saved[-1][1]['state'],'reconciling')

    def test_pending_account_verification_never_makes_an_unverified_book_look_recovered(self):
        class Alerts(FakeStore):
            def __init__(self):super().__init__();self.cleared=[]
            def clear_alert(self,key):self.cleared.append(key)
            def alert(self,*args,**kwargs):pass
        store=Alerts();worker=Worker(store,Mock(reads=0,writes=0),threading.Event(),lambda:None)
        worker.stream_outage_since=NOW-3;worker.recovered=False
        worker.socket=object();worker.book_sid=2
        worker.quotes={'t':dict(quote(),source='orderbook',book_ready=False,at=NOW)}
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.trading_health()
        self.assertIsNotNone(worker.stream_outage_since)
        self.assertEqual(store.saved[-1][1]['state'],'reconnecting')
        self.assertEqual(store.cleared,[])


class RestReadStreamDrain(unittest.TestCase):
    def test_rest_reconciliation_drains_sequenced_feed_without_waiting_for_whole_history(self):
        import httpx
        from services.demo.exchange import Exchange
        now=int(time.time())
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'balance':1000}))
        ex=Exchange(Mock(headers=lambda *args:{}),client=httpx.Client(transport=transport))
        worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        self.assertIsNotNone(ex.before_read)
        worker.stage='reconciliation'
        worker.quotes={'t':dict(quote(),at=0,close=now+180)}
        worker.subscription={'t'};worker.book_sid=2
        messages=[dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=now*1000,
            msg=dict(market_ticker='t',clock=1,yes_dollars_fp=[['0.50','1']],no_dollars_fp=[['0.40','1']]))]
        messages.extend(dict(type='orderbook_delta',sid=2,seq=i,sending_ts_ms=now*1000,
            msg=dict(market_ticker='t',clock=i,ts_ms=now*1000,side='no',price_dollars='0.45',delta_fp='0'))
            for i in range(2,402))
        class Socket:
            received_at=now
            def __init__(self):self.consumed=0
            def recv(self,timeout=0):
                if not messages:raise TimeoutError()
                self.consumed+=1
                return json.dumps(messages.pop(0))
            def stats(self):return dict(consumed=self.consumed,messages=len(messages),bytes=0)
        worker.socket=Socket()
        response=ex.call('GET','/portfolio/balance')
        self.assertEqual(response['balance'],1000)
        self.assertEqual(worker.quotes['t']['seq'],401)
        self.assertEqual(len(messages),0)
        self.assertGreaterEqual(worker.rest_feed_messages,401)
        self.assertGreater(worker.rest_feed_drains,0)
        ex.close()

    def test_rest_read_pump_latches_protective_exit_during_verification_without_selling(self):
        import httpx
        from services.demo.exchange import Exchange
        now=int(time.time())
        ex=Exchange(Mock(headers=lambda *args:{}),client=httpx.Client(transport=httpx.MockTransport(
            lambda request:httpx.Response(200,json={'balance':1000}))))
        store=FakeStore();worker=Worker(store,ex,threading.Event(),lambda:None)
        worker.stage='reconciliation';worker.recovered=False
        b=bot(loss_mode='manual',loss_cents=55)
        worker.bots=[b]
        worker.quotes={'t':dict(quote(),at=0,close=now+180)}
        order=dict(client_id='entry-1',kind='entry',bot=b['id'],ticker='t',
            revision=1,square=0,side='yes',price=65,quantity=1,status='held',filled=1,sold=0,remaining=0)
        worker.orders=[order];worker.subscription={'t'};worker.book_sid=2
        messages=[
          dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=now*1000,
            msg=dict(market_ticker='t',clock=1,yes_dollars_fp=[['0.50','1']],no_dollars_fp=[['0.40','1']])),
          dict(type='orderbook_delta',sid=2,seq=2,sending_ts_ms=now*1000,
            msg=dict(market_ticker='t',clock=2,ts_ms=now*1000,side='no',price_dollars='0.45',delta_fp='1'))
        ]
        class Socket:
            received_at=now
            def __init__(self):self.consumed=0
            def recv(self,timeout=0):
                if not messages:raise TimeoutError()
                self.consumed+=1
                return json.dumps(messages.pop(0))
            def stats(self):return dict(consumed=self.consumed,messages=len(messages),bytes=0)
        worker.socket=Socket()
        ex.call('GET','/portfolio/balance')
        self.assertTrue(order['exit_triggered'])
        self.assertIn('exit_trigger',store.events)
        self.assertEqual(ex.writes,0)
        self.assertFalse(worker.recovered)
        ex.close()

    def test_provider_read_cooldown_drains_without_replaying_order_writes(self):
        import httpx
        from services.demo.exchange import Exchange
        observed=[];ex=Exchange(Mock(headers=lambda *args:{}),
            client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={}))))
        ex.before_read=lambda:observed.append(time.monotonic())
        ex.next_read=time.monotonic()+.45
        ex.call('GET','/portfolio/balance')
        self.assertGreaterEqual(len(observed),2,'reconnection polling must continue through REST pacing')
        observed.clear()
        ex.call('POST','/portfolio/events/orders',body={})
        self.assertEqual(observed,[],'never re-enter the stream while preparing a write')
        ex.close()


class Order404Recovery(unittest.TestCase):
    def entry(self):
        return dict(client_id='entry-1',exchange_id='remote-1',kind='entry',
            bot='bot-1',ticker='KXBTC15M-TEST',side='yes',price=70,
            quantity=3,filled=0,remaining=3,sold=0,status='resting',
            revision=1,square=0,close=NOW+300)

    def test_missing_cancel_does_not_assume_zero_exposure_or_raise_global_order_alarm(self):
        ex=Mock();ex.cancel.side_effect=ExchangeFailure('exchange_rejected',
            status=404,provider_code='not_found')
        store=FakeStore();worker=Worker(store,ex,threading.Event(),lambda:None)
        o=self.entry();worker.orders=[o];worker.recovered=True;worker.last_reconcile=NOW
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.cancel(o,'Closing unfilled bid')
            worker.cancel(o,'Second attempted cancel must be suppressed')
        ex.cancel.assert_called_once()
        self.assertEqual((o['status'],o['remaining']),('cancel_pending',3))
        self.assertIn(o['ticker'],worker.blocked)
        self.assertFalse(worker.recovered)
        self.assertEqual(worker.last_reconcile,0)
        self.assertIn('cancel_verification_pending',store.events)
        self.assertEqual(store.saved[-1][1]['status'],'cancel_pending')

    def test_pending_404_cancel_never_rearms_a_buy_low_cycle(self):
        ex=Mock();ex.cancel.side_effect=ExchangeFailure('exchange_rejected',status=404,provider_code='not_found')
        store=FakeStore();worker=Worker(store,ex,threading.Event(),lambda:None)
        b=bot();b['config']['strategy']='buy_low_sell_high'
        worker.bots=[b];o=self.entry()
        o.update(entry_strategy='buy_low_sell_high',bot=b['id'],cycle=1)
        worker.orders=[o]
        worker.states={b['id']:{f"{o['ticker']}/0/yes":dict(submitted=True,cycle=1,attempt=0)}}
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.park_cycle_entry(o,'Parking bid')
        state=worker.states[b['id']][f"{o['ticker']}/0/yes"]
        self.assertTrue(state['submitted'])
        self.assertEqual(state['attempt'],0)
        self.assertEqual(o['status'],'cancel_pending')

    def test_missing_order_lookup_remains_unverified_but_other_errors_still_raise(self):
        ex=Mock();ex.call.side_effect=ExchangeFailure('exchange_rejected',
            status=404,provider_code='not_found')
        worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        self.assertIsNone(worker.lookup_exchange_order(self.entry()))
        ex.call.side_effect=ExchangeFailure('exchange_rejected',status=503,provider_code='service_unavailable')
        with self.assertRaises(ExchangeFailure):
            worker.lookup_exchange_order(self.entry())

    def test_definitively_rejected_create_is_not_replayed_or_mistaken_for_accepted_order(self):
        ex=Mock();ex.submit.side_effect=ExchangeFailure('exchange_rejected',
            status=404,provider_code='not_found')
        store=FakeStore();worker=Worker(store,ex,threading.Event(),lambda:None)
        worker.recovered=True;worker.last_reconcile=NOW
        worker.quotes={'KXBTC15M-TEST':dict(quote(),at=NOW)}
        o=self.entry();o.update(status='intent',exchange_id=None,remaining=0)
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.submit(o)
        ex.submit.assert_called_once()
        self.assertEqual(o['status'],'rejected')
        self.assertTrue(worker.recovered)
        self.assertEqual(worker.last_reconcile,NOW)
        self.assertEqual(worker.quotes[o['ticker']]['at'],0)
        self.assertNotIn(o['ticker'],worker.blocked)
        self.assertIn('order_rejected',store.events)


    def test_verified_still_resting_order_after_404_is_not_canceled_in_a_tight_loop(self):
        ex=Mock();ex.cancel.side_effect=ExchangeFailure('exchange_rejected',status=404,provider_code='not_found')
        worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        o=self.entry();worker.orders=[o]
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.cancel(o,'First attempt')
            # REST has confirmed it is still resting; do not hammer the same
            # DELETE route every trading loop before the retry cooldown.
            o['status']='resting'
            worker.cancel(o,'Second attempt')
            worker.trade()
        ex.cancel.assert_called_once()
        with patch('services.demo.runtime.time.time',return_value=NOW+31):
            worker.cancel(o,'Retry after verified cooldown')
        self.assertEqual(ex.cancel.call_count,2)
        self.assertEqual(o['cancel_404_count'],2)

    def test_failed_cancel_cooldown_does_not_starve_other_markets(self):
        ex=Mock();worker=Worker(FakeStore(),ex,threading.Event(),lambda:None)
        b=bot();worker.bots=[b]
        o=self.entry();o['bot']=b['id'];o['cancel_404_at']=NOW
        worker.orders=[o];worker.blocked={o['ticker']}
        worker.quotes={o['ticker']:quote(), 'u':quote()}
        worker.recovered=True;worker.last_reconcile=NOW
        worker.account=dict(equity_cents=10000,cash_cents=10000)
        worker.funding=Mock();worker.funding.ensure.return_value=True
        worker.submit=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):
            worker.trade()
        self.assertEqual(worker.submit.call_count,1)
        self.assertEqual(worker.submit.call_args.args[0]['ticker'],'u')
        ex.cancel.assert_not_called()


class MarketOpenCoverage(unittest.TestCase):
    def test_discovery_sweeps_three_distinct_live_cycle_series_per_call(self):
        from services.research.reports import SERIES
        seen=[]
        class Ex:
            def call(self,method,path,*,params):
                seen.append(params)
                return dict(markets=[],cursor='')
        worker=Worker(FakeStore(),Ex(),threading.Event(),lambda:None)
        worker.bots=[]
        for asset in ('btc','eth','sol'):
            b=bot();b['id']=asset;b['config']['strategy']='buy_low_sell_high'
            b['config']['squares'][0]['asset']=asset
            worker.bots.append(b)
        # The round-wide sweep runs first; per-series fallback retains its
        # three-series coverage after that bounded sweep has completed.
        worker.cycle_discovery_epoch=int(NOW//900)
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.discover()
        self.assertEqual(len(seen),3)
        self.assertEqual({p['series_ticker'] for p in seen},set().union(*(SERIES[a] for a in ('btc','eth','sol'))))
        self.assertEqual(worker.series_index,3)

    def test_watchlist_includes_every_individual_series_before_overallocating_brent(self):
        from services.research.reports import INDIVIDUAL_15M_SERIES
        from services.demo.watchlist import select_markets
        series={'btc':'KXBTC15M','eth':'KXETH15M',**INDIVIDUAL_15M_SERIES}
        quotes={}
        for asset,code in series.items():
            for n in range(85 if asset in ('brent_15m','copper_15m') else 1):
                quotes[f'{code}-{n}']=dict(status='active',series=code,open=NOW-n,close=NOW+600,entry_close=NOW+600)
        selected=select_markets(quotes,set(),NOW,limit=100,cycle_series=set(series.values()))
        self.assertEqual(len(selected),100)
        self.assertEqual({q['series'] for q in selected.values()},set(series.values()))
        self.assertLess(sum(q['series']=='KXBRENT15M' for q in selected.values()),65)

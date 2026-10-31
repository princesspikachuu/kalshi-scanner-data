import json,threading,unittest
from unittest.mock import patch
from services.demo.orderbook import OrderBooks
from services.demo.exchange import ExchangeFailure
from services.demo.runtime import Worker
from services.api.tests.test_demo_engine import NOW,FakeStore,bot,quote

def snapshot(**kw):
    raw=dict(market_ticker='t',clock=5,yes_dollars_fp=[['0.45','3'],['0.50','2']],no_dollars_fp=[['0.40','4']]);raw.update(kw)
    return dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=NOW*1000,msg=raw)
def delta(**kw):
    raw=dict(market_ticker='t',clock=6,ts_ms=NOW*1000,side='no',price_dollars='0.45',delta_fp='1');raw.update(kw)
    return dict(type='orderbook_delta',sid=2,seq=2,sending_ts_ms=(NOW+1)*1000,msg=raw)

class Books(unittest.TestCase):
    def test_build_complement_apply_remove_and_replace(self):
        books=OrderBooks();_,q=books.apply(snapshot(),NOW)
        self.assertEqual((q['bid'],q['ask']),(50,60))
        _,q=books.apply(delta(),NOW+1);self.assertEqual(q['ask'],55);self.assertEqual(q['at'],NOW)
        _,q=books.apply(delta(delta_fp='-1'),NOW+1);self.assertEqual(q['ask'],60)
        _,q=books.apply(snapshot(yes_dollars_fp=[['0.48','1']],no_dollars_fp=[]),NOW+1)
        self.assertEqual(q['bid'],48);self.assertEqual(q['ask'],100);self.assertFalse(q['book_ready'])
        self.assertEqual(len(books.books['t']['yes']),1)
    def test_fractional_prices_are_not_rounded_into_fake_zero_or_hundred(self):
        _,q=OrderBooks().apply(snapshot(yes_dollars_fp=[['0.001','1']],no_dollars_fp=[['0.001','1']]),NOW)
        self.assertEqual((q['bid'],q['ask']),(0.1,99.9))
    def test_missing_snapshot_negative_size_bad_clock_and_nonfinite_fail_closed(self):
        for message in [delta(),delta(delta_fp='-100'),delta(clock=1),delta(price_dollars='NaN')]:
            books=OrderBooks()
            if message!=delta():books.apply(snapshot(),NOW)
            with self.assertRaises(ExchangeFailure):books.apply(message,NOW)
            self.assertEqual(books.books,{})
    def test_sequence_gap_fences_execution(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.quotes={'t':quote()};worker.subscription={'t'}
        messages=[snapshot(),dict(delta(),seq=3)]
        class Socket:
            def recv(self,**kw):
                if not messages:raise TimeoutError
                return json.dumps(messages.pop(0))
        worker.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW),self.assertRaises(ExchangeFailure) as caught:worker.stream()
        self.assertEqual(caught.exception.code,'stream_gap')
    def test_discovery_changes_subscription_without_disconnect_or_losing_held_book(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.quotes={'t':quote(),'new':quote()};worker.subscription={'t'};worker.book_sid=2;worker.books.apply(snapshot(),NOW)
        class Socket:
            def __init__(self):self.sent=[]
            def send(self,data):self.sent.append(json.loads(data))
            def recv(self,**kw):raise TimeoutError
        sock=worker.socket=Socket();worker.stream()
        self.assertIs(worker.socket,sock);self.assertIn('t',worker.books.books)
        self.assertEqual(sock.sent[0]['params'],dict(sids=[2],market_tickers=['new'],action='add_markets'))
    def test_legacy_unfilled_fixed_bid_is_canceled_once_and_rearmed(self):
        b=bot(maximum_cents=96);worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.bots=[b];worker.recovered=True
        worker.states={b['id']:{'t/0/yes':dict(submitted=True)}}
        o=dict(client_id='old',exchange_id='remote',kind='entry',bot=b['id'],revision=1,ticker='t',side='yes',square=0,remaining=1,filled=0,status='resting',price=96,quantity=1)
        worker.orders=[o]
        def cancel(order,reason):order.update(remaining=0,status='closed');worker.recovered=False
        with patch.object(worker,'cancel',side_effect=cancel) as called:worker.trade()
        called.assert_called_once();self.assertFalse(worker.states[b['id']]['t/0/yes']['submitted'])
        self.assertEqual(worker.states[b['id']]['t/0/yes']['attempt'],1)
        self.assertEqual(o['entry_pricing'],'cap_v2')
    def test_quiet_book_only_refreshed_after_pong_and_drained_messages(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None)
        worker.quotes={'t':dict(quote(),source='orderbook',at=NOW-30,event_at=NOW-30)};worker.subscription={'t'};worker.books.apply(snapshot(),NOW)
        pong=threading.Event()
        class Socket:
            def recv(self,**kw):raise TimeoutError
            def ping(self):return pong
        worker.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW):worker.stream()
        self.assertEqual(worker.quotes['t']['at'],NOW-30)
        pong.set()
        with patch('services.demo.runtime.time.time',return_value=NOW+1):worker.stream()
        self.assertEqual(worker.quotes['t']['at'],NOW+1)
        self.assertEqual(worker.quotes['t']['event_at'],NOW-30)
        with patch('services.demo.runtime.time.time',return_value=NOW+20):worker.stream()
        self.assertEqual(worker.quotes['t']['at'],NOW+1)
    def test_fill_yields_for_reconciliation_before_later_price_changes(self):
        worker=Worker(FakeStore(),object(),threading.Event(),lambda:None);worker.quotes={'t':quote()};worker.subscription={'t'}
        messages=[dict(type='fill',msg=dict(market_ticker='t')),snapshot()]
        class Socket:
            def recv(self,**kw):return json.dumps(messages.pop(0))
        worker.socket=Socket();worker.last_reconcile=NOW
        worker.stream()
        self.assertEqual(worker.last_reconcile,0);self.assertEqual(len(messages),1)
        self.assertEqual(worker.books.books,{})

import json,threading,unittest
from unittest.mock import Mock,patch
from services.api.demo_models import BotConfig
from services.api.tests.test_demo_engine import NOW,FakeStore,config,quote
from services.demo.engine import candidates,wire_order
from services.demo.cycles import offset_plan
from services.demo.runtime import Worker

def bot(**changes):
    return dict(id='bot-1',revision=1,desired='running',config=config(**dict(dict(strategy='buy_low_sell_high',cycle_cutoff_minutes=1),**changes)))
def book(**changes):
    return dict(quote(),status='active',open=NOW-10,close=NOW+900,source='orderbook',book_verified=True,**changes)
def entry(**changes):
    value=dict(client_id='low',bot='bot-1',revision=1,kind='entry',ticker='t',side='yes',square=0,cycle=1,price=10,quantity=10,
        filled=0,remaining=10,sold=0,status='resting',entry_pricing='cap_v2',entry_strategy='buy_low_sell_high',profit_target_cents=20,
        created_at=NOW-1,close=NOW+840,exchange_id='ex-low',exit_reference='ask')
    value.update(changes);return value

def worker():
    w=Worker(FakeStore(),object(),threading.Event(),lambda:None);w.bots=[bot()];w.quotes={'t':book()}
    w.recovered=True;w.last_reconcile=NOW;w.account=dict(cash_cents=10000,equity_cents=10000)
    w.funding=Mock();w.funding.ensure.return_value=True;w.submit=Mock();return w

class CycleEntries(unittest.TestCase):
    def test_both_sides_post_at_fixed_low_on_a_verified_open_book(self):
        b=bot();q=book();result=candidates([b],{'t':q},{},NOW)
        self.assertEqual({r['side'] for r in result},{'yes','no'});self.assertEqual({r['price'] for r in result},{10})
        empty=dict(q,bid=0,ask=100,book_ready=False)
        self.assertEqual(len(candidates([b],{'t':empty},{},NOW)),2)
        self.assertEqual(candidates([b],{'t':dict(q,book_verified=False)},{},NOW),[])
        self.assertEqual(candidates([b],{'t':dict(q,source='rest')},{},NOW),[])
        self.assertEqual(candidates([b],{'t':dict(q,open=NOW+1)},{},NOW),[])
    def test_cutoff_is_exclusive_and_partial_fills_can_still_sell_after_it(self):
        b=bot();q=book();end=NOW+840
        self.assertEqual(candidates([b],{'t':dict(q,at=end)},{},end),[])
        self.assertEqual(len(candidates([b],{'t':dict(q,at=end-.01)},{},end-.01)),2)
        w=worker();w.orders=[entry(filled=3,remaining=0)];w.quotes['t']['at']=end+1;w.last_reconcile=end+1
        with patch('services.demo.runtime.time.time',return_value=end+1):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['exit_role'],'profit')
    def test_entry_expiry_and_both_outcomes_are_independent_not_duplicate_bids(self):
        w=worker()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        first=w.submit.call_args.args[0];self.assertEqual(first['close'],NOW+840)
        self.assertEqual(first['entry_strategy'],'buy_low_sell_high');self.assertEqual(first['profit_target_cents'],20)
        first.update(status='resting',remaining=first['quantity']);w.orders=[first];w.submit.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        second=w.submit.call_args.args[0];self.assertNotEqual(first['side'],second['side'])
        second.update(status='resting',remaining=second['quantity']);w.orders.append(second);w.submit.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
    def test_cutoff_cancels_remaining_low_bid_even_with_stale_prices(self):
        w=worker();w.orders=[entry()];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW+841):w.trade()
        w.cancel.assert_called_once()
    def test_validates_non_crossing_two_sided_low_and_higher_sell_prices(self):
        for changes in [dict(cycle_buy_cents=50),dict(cycle_buy_cents=20,cycle_sell_cents=20),dict(cycle_cutoff_minutes=-1)]:
            with self.assertRaises(ValueError):bot(**changes)

class ProfitSells(unittest.TestCase):
    def test_partial_fills_get_only_uncovered_inventory_at_fixed_target(self):
        w=worker();w.states={'bot-1':{'t/0/no':dict(cycle=1,submitted=True,first_at=NOW)}};parent=entry(filled=3,remaining=7);w.orders=[parent]
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        sell=w.submit.call_args.args[0];self.assertEqual((sell['price'],sell['quantity'],sell['exit_role']),(20,3,'profit'))
        sell.update(status='resting',remaining=3);w.orders.append(sell);w.submit.reset_mock()
        parent['filled']=5;parent['remaining']=5
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['quantity'],2)
        w.submit.reset_mock();parent['filled']=3
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
        payload=wire_order(sell);self.assertFalse(payload['post_only']);self.assertEqual(payload['price'],'0.2000')
    def test_profit_sell_does_not_chase_price_and_stop_cancels_it_first(self):
        w=worker();w.states={'bot-1':{'t/0/no':dict(cycle=1,submitted=True,first_at=NOW)}};parent=entry(filled=3,remaining=0);sell=dict(parent,client_id='high',kind='exit',parent='low',exit_role='profit',price=20,filled=0,remaining=3)
        w.orders=[parent,sell];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_not_called();w.submit.assert_not_called()
        parent['exit_triggered']=True;parent['exit_ceiling_cents']=5
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_called_once();self.assertEqual(w.cancel.call_args.args[0]['client_id'],'high');w.submit.assert_not_called()
    def test_repeat_is_durable_once_only_and_never_after_stop_or_partial_exit(self):
        w=worker();key='t/0/yes';w.states={'bot-1':{key:dict(cycle=1,submitted=True,first_at=NOW)}}
        parent=entry(filled=10,remaining=0,sold=3,status='held')
        w.rearm_cycle(parent,NOW);self.assertTrue(w.states['bot-1'][key]['submitted'])
        parent.update(sold=10,status='closed');w.rearm_cycle(parent,NOW)
        self.assertEqual(w.states['bot-1'][key]['cycle'],2);self.assertFalse(w.states['bot-1'][key]['submitted'])
        count=len(w.store.saved);w.rearm_cycle(parent,NOW);self.assertEqual(len(w.store.saved),count)
        w.states['bot-1'][key]=dict(cycle=1,submitted=True,first_at=NOW);parent['exit_triggered']=True
        w.rearm_cycle(parent,NOW);self.assertTrue(w.states['bot-1'][key]['submitted'])
        parent['exit_triggered']=False;w.bots[0]['config']['cycle_repeat']=False
        w.rearm_cycle(parent,NOW);self.assertTrue(w.states['bot-1'][key]['submitted'])

class PositionOffsets(unittest.TestCase):
    def test_offsets_only_confirmed_owned_inventory_and_waits_for_live_sells_to_cancel(self):
        yes=entry(filled=3,remaining=0);no=entry(client_id='no',side='no',filled=2,remaining=0)
        changes,cancel=offset_plan([yes,no],{}, {'t':1},set())
        self.assertEqual(changes,{'low':2,'no':2});self.assertEqual(cancel,set())
        sell=dict(yes,kind='exit',parent='low',client_id='high',remaining=3,filled=0)
        self.assertEqual(offset_plan([yes,no,sell],{}, {'t':1},set()),({}, {'t'}))
        self.assertEqual(offset_plan([yes,no],{}, {'t':2},set()),({},set()))
        self.assertEqual(offset_plan([yes,no],{}, {'t':1},{'t'}),({},set()))
        self.assertEqual(offset_plan([yes,dict(no,status='uncertain')],{}, {'t':1},set()),({},set()))
        yes['offset_quantity']=2;no['offset_quantity']=2
        self.assertEqual(offset_plan([yes,no],{}, {'t':1},set()),({},set()))
    def test_netting_cancels_sell_before_any_new_profit_or_entry_order(self):
        w=worker();w.netting_pending={'t'};w.orders=[dict(entry(),kind='exit',client_id='high',parent='low',remaining=2,exit_role='profit')];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_called_once();w.submit.assert_not_called()

class Lifecycle(unittest.TestCase):
    def test_open_notification_refreshes_only_selected_series(self):
        w=worker();w.subscription={'t'};w.book_sid=1
        class Socket:
            def __init__(self):self.sent=[];self.messages=[dict(type='market_lifecycle_v2',sid=3,seq=1,msg=dict(event_type='activated',market_ticker='KXBTC15M-NEW'))]
            def send(self,message):self.sent.append(json.loads(message))
            def recv(self,timeout):
                if not self.messages:raise TimeoutError()
                return json.dumps(self.messages.pop(0))
        w.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.stream()
        self.assertEqual(w.pending_markets,{'KXBTC15M-NEW'});self.assertEqual(w.last_discovery,0)
        self.assertEqual(w.socket.sent[0]['params']['channels'],['market_lifecycle_v2'])

class CancelFencing(unittest.TestCase):
    def test_opposite_low_is_parked_before_profit_and_no_new_buys_while_held(self):
        w=worker();yes=entry(filled=3,remaining=7);no=entry(client_id='other',side='no')
        w.orders=[yes,no];w.states={'bot-1':{'t/0/no':dict(cycle=1,submitted=True,first_at=NOW)}}
        w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.cancel.call_args.args[0]['client_id'],'other');w.submit.assert_not_called()
        self.assertFalse(w.states['bot-1']['t/0/no']['submitted'])
        no.update(remaining=0,status='cancel_pending');w.cancel.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
        no['status']='closed'
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['exit_role'],'profit')
    def test_one_cycle_state_survives_temporary_watchlist_removal_until_market_end(self):
        b=bot(cycle_repeat=False);states={};candidates([b],{'t':book()},states,NOW)
        states['bot-1']['t/0/yes']['submitted']=True
        candidates([b],{},states,NOW+1)
        self.assertIn('t/0/yes',states['bot-1'])
        result=candidates([b],{'t':dict(book(),at=NOW+2)},states,NOW+2)
        self.assertEqual([r['side'] for r in result],['no'])

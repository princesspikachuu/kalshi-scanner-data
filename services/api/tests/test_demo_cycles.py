import json,threading,unittest
from unittest.mock import Mock,patch
from services.api.demo_models import BotConfig
from services.api.tests.test_demo_engine import NOW,FakeStore,config,quote
from services.demo.engine import candidates,wire_order
from services.demo.cycles import offset_plan,entry_block_reason,park_reason,shared_quantity
from services.demo.runtime import Worker
from services.demo.exchange import ExchangeFailure

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

class RejectionPrices(unittest.TestCase):
    def rejecting_worker(self,reason='post_only',ambiguous=False):
        w=worker();w.quotes['t'].update(clock=1,seq=1)
        w.exchange=Mock();w.exchange.submit.side_effect=ExchangeFailure('exchange_rejected',ambiguous,status=400,reason=reason)
        w.states={'bot-1':{'t/0/yes':dict(cycle=1,submitted=True,first_at=NOW),
                           't/0/no':dict(cycle=1,submitted=True,first_at=NOW)}}
        return w
    def test_rejected_buys_shift_both_prices_from_last_attempt_on_either_outcome(self):
        for side in ('yes','no'):
            w=self.rejecting_worker();order=entry(side=side,remaining=0,status='intent')
            with patch('services.demo.runtime.time.time',return_value=NOW):Worker.submit(w,order)
            self.assertTrue(w.recovered);self.assertEqual(order['status'],'rejected')
            self.assertEqual(candidates(w.bots,w.quotes,w.states,NOW+1),[])
            w.quotes['t'].update(seq=2,at=NOW+1)
            result=candidates(w.bots,w.quotes,w.states,NOW+1)
            self.assertEqual([(r['side'],r['price'],r['profit_target_cents']) for r in result],[(side,8,18)])
            with patch('services.demo.runtime.time.time',return_value=NOW+1):w.trade()
            retry=w.submit.call_args.args[0];self.assertEqual((retry['price'],retry['profit_target_cents']),(8,18))
            self.assertNotEqual(retry['client_id'],order['client_id'])
            with patch('services.demo.runtime.time.time',return_value=NOW+1):Worker.submit(w,retry)
            w.quotes['t'].update(seq=3,at=NOW+2)
            result=candidates(w.bots,w.quotes,w.states,NOW+2)
            self.assertEqual((result[0]['price'],result[0]['profit_target_cents']),(6,16))
    def test_profit_rejection_raises_target_waits_for_new_quote_and_preserves_inventory(self):
        w=self.rejecting_worker('price_tick');parent=entry(filled=3,remaining=0);w.orders=[parent]
        self.assertTrue(w.profit_sell(parent,w.quotes['t'],NOW));sell=w.submit.call_args.args[0]
        with patch('services.demo.runtime.time.time',return_value=NOW):Worker.submit(w,sell)
        self.assertEqual(parent['profit_target_cents'],22);self.assertEqual(parent['filled'],3)
        w.submit.reset_mock();self.assertFalse(w.profit_sell(parent,w.quotes['t'],NOW+1))
        w.quotes['t']['seq']=2
        self.assertFalse(w.profit_sell(parent,w.quotes['t'],NOW+.1))
        self.assertTrue(w.profit_sell(parent,w.quotes['t'],NOW+1))
        retry=w.submit.call_args.args[0];self.assertEqual((retry['price'],retry['quantity']),(22,3))
        self.assertNotEqual(retry['client_id'],sell['client_id'])
    def test_bounds_stop_retries_and_protective_exit_still_takes_over(self):
        w=self.rejecting_worker();order=entry(price=2,profit_target_cents=12)
        with patch('services.demo.runtime.time.time',return_value=NOW):Worker.submit(w,order)
        w.quotes['t']['seq']=2
        self.assertEqual(candidates(w.bots,w.quotes,w.states,NOW+1),[])
        parent=entry(filled=3,remaining=0,profit_target_cents=99);w.orders=[parent]
        sell=dict(parent,client_id='high',kind='exit',exit_role='profit',parent=parent['client_id'],price=99)
        with patch('services.demo.runtime.time.time',return_value=NOW):Worker.submit(w,sell)
        self.assertTrue(parent['profit_retry_exhausted']);self.assertFalse(w.profit_sell(parent,w.quotes['t'],NOW+1))
        parent.update(exit_triggered=True,exit_ceiling_cents=40);w.submit.reset_mock()
        w.quotes['t'].update(bid=30,ask=35)
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['kind'],'exit')
        self.assertNotEqual(w.submit.call_args.args[0].get('exit_role'),'profit')
    def test_ambiguous_and_funding_errors_do_not_adjust_prices(self):
        for reason,ambiguous in [('balance',False),('post_only',True),('routing',False),('quantity',False)]:
            w=self.rejecting_worker(reason,ambiguous);order=entry()
            with self.assertRaises(ExchangeFailure):Worker.submit(w,order)
            self.assertNotIn('retry_buy_cents',w.states['bot-1']['t/0/yes'])
            self.assertEqual(order['profit_target_cents'],20)
    def test_retry_recovery_is_idempotent_and_new_cycle_starts_at_configured_prices(self):
        w=self.rejecting_worker();order=entry(rejection_reason='post_only',status='rejected')
        with patch('services.demo.runtime.time.time',return_value=NOW):
            self.assertTrue(w.retry_cycle_rejection(order));self.assertTrue(w.retry_cycle_rejection(order))
        state=w.states['bot-1']['t/0/yes'];self.assertEqual((state['attempt'],state['retry_buy_cents']),(1,8))
        state['submitted']=True;order.update(status='closed',filled=10,sold=10,remaining=0)
        w.rearm_cycle(order,NOW+1);w.quotes['t'].update(seq=2,at=NOW+1)
        result=candidates(w.bots,w.quotes,w.states,NOW+1)
        self.assertEqual((result[0]['cycle'],result[0]['price'],result[0]['profit_target_cents']),(2,10,20))

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
        b=bot();q=book();end=NOW+720
        self.assertEqual(candidates([b],{'t':dict(q,at=end)},{},end),[])
        self.assertEqual(len(candidates([b],{'t':dict(q,at=end-.01)},{},end-.01)),2)
        w=worker();w.orders=[entry(filled=3,remaining=0)];w.quotes['t']['at']=end+1;w.last_reconcile=end+1
        with patch('services.demo.runtime.time.time',return_value=end+1):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['exit_role'],'profit')
    def test_entry_expiry_and_both_outcomes_are_independent_not_duplicate_bids(self):
        w=worker()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        first=w.submit.call_args.args[0];self.assertEqual(first['close'],NOW+720)
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

class SharedMarkets(unittest.TestCase):
    def test_daily_cutoff_and_shard_funding_are_real_entry_blockers(self):
        w=worker();w.bots[0]['config']['daily_loss_percent']=5
        w.daily_pnl_day=int(NOW//86400);w.daily_pnl={'bot-1':-600}
        info=w.entry_diagnostics(NOW)['bot-1']
        self.assertEqual(info['entry_blockers'].get('daily_loss'),2)
        self.assertIn('daily loss cutoff reached',info['message'])
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
        w.bots[0]['config']['daily_loss_percent']=None
        w.funding.waits={0:dict(reason='funding',at=NOW,required_cents=10,available_cents=0)}
        self.assertEqual(w.entry_diagnostics(NOW)['bot-1']['entry_blockers'].get('funding'),2)
        w.quotes['t']['at']=NOW-20
        self.assertIn('fresh verified prices',w.entry_diagnostics(NOW)['bot-1']['message'])
    def test_five_bots_can_each_bid_both_outcomes_without_stealing_ownership(self):
        w=worker();w.bots=[]
        for low in (3,6,9,12,15):
            b=bot(cycle_buy_cents=low,cycle_sell_cents=low+3)
            b['id']=f'bot-{low}';w.bots.append(b)
        for _ in range(10):
            w.submit.reset_mock()
            with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
            self.assertIsNotNone(w.submit.call_args)
            order=w.submit.call_args.args[0];order.update(status='resting',remaining=order['quantity']);w.orders.append(order)
        self.assertEqual({(o['bot'],o['side']) for o in w.orders},{(b['id'],s) for b in w.bots for s in ('yes','no')})
        self.assertEqual(len({o['client_id'] for o in w.orders}),10)
        self.assertLessEqual(sum(o['quantity']*o['price'] for o in w.orders),300)
        self.assertTrue(all(o['quantity']*o['price']<=100 for o in w.orders))
        w.submit.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
    def test_fair_sharing_never_increases_cash_bid_bot_or_market_limits(self):
        cfg=bot()['config'];item=dict(bot='a',price=10);peers=[item,dict(bot='b',price=15)]
        self.assertEqual(shared_quantity(item,peers,cfg,10000,10000,0,0),10)
        self.assertEqual(shared_quantity(item,peers,cfg,10000,0,0,0),0)
        self.assertEqual(shared_quantity(item,peers,cfg,10000,10000,300,0),0)
        self.assertEqual(shared_quantity(item,peers,cfg,10000,10000,0,1000),0)
        self.assertEqual(shared_quantity(item,peers,cfg,10000,5,0,0),0)
        self.assertEqual(shared_quantity(item,[item,dict(item,side='no')],cfg,10000,10000,240,0),3)
    def test_sharing_keeps_duplicate_manual_strategy_and_verification_fences(self):
        item=dict(bot='bot-2',side='yes',price=6)
        self.assertIsNone(entry_block_reason(item,[entry()]))
        self.assertEqual(entry_block_reason(dict(item,bot='bot-1'),[entry()]),'duplicate')
        self.assertEqual(entry_block_reason(item,[entry(entry_strategy='conditions')]),'other_strategy')
        self.assertEqual(entry_block_reason(item,[entry(status='cancel_pending',remaining=0)]),'verification')
        self.assertEqual(entry_block_reason(item,[],True),'netting')
    def test_same_side_inventory_is_shared_but_opposite_low_bids_wait(self):
        parent=entry(filled=3,remaining=0,price=12,profit_target_cents=15)
        w=worker();other=bot(cycle_buy_cents=6,cycle_sell_cents=9);other['id']='bot-2'
        w.bots.append(other);w.orders=[parent]
        self.assertIsNone(entry_block_reason(dict(bot='bot-2',side='yes',price=6),w.orders))
        self.assertEqual(entry_block_reason(dict(bot='bot-2',side='no',price=6),w.orders),'opposite_inventory')
        sell=dict(kind='exit',exit_role='profit',client_id='high',parent='low',bot='bot-1',ticker='t',side='yes',price=15,status='resting',remaining=3)
        w.orders.append(sell)
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual((w.submit.call_args.args[0]['bot'],w.submit.call_args.args[0]['side']),('bot-2','yes'))
    def test_crossing_buys_cancel_and_confirm_before_another_bots_profit_sell(self):
        w=worker();parent=entry(filled=3,remaining=0,price=3,profit_target_cents=6)
        other=entry(bot='bot-2',client_id='other',price=15,profit_target_cents=18)
        b=bot(cycle_buy_cents=15,cycle_sell_cents=18);b['id']='bot-2';w.bots.append(b)
        w.orders=[parent,other];w.states={'bot-2':{'t/0/yes':dict(cycle=1,submitted=True,first_at=NOW)}};w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.cancel.call_args.args[0]['client_id'],'other');w.submit.assert_not_called()
        self.assertFalse(w.states['bot-2']['t/0/yes']['submitted'])
        other.update(status='cancel_pending',remaining=0);w.submit.reset_mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
        other['status']='closed'
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual((w.submit.call_args.args[0]['parent'],w.submit.call_args.args[0]['price']),('low',6))
    def test_existing_profit_sell_blocks_only_crossing_prices_not_all_bots(self):
        parent=entry(price=3,profit_target_cents=6,filled=3,remaining=0)
        sell=dict(parent,kind='exit',parent='low',client_id='high',exit_role='profit',price=6,filled=0,remaining=3)
        rows=[parent,sell]
        self.assertEqual(entry_block_reason(dict(bot='b',side='yes',price=6),rows),'self_trade')
        self.assertIsNone(entry_block_reason(dict(bot='b',side='yes',price=3),rows))
        self.assertIsNone(park_reason(entry(bot='b',price=3),rows))
        self.assertEqual(park_reason(entry(bot='b',price=15),rows),'self_trade')
        self.assertFalse(worker().profit_sell(dict(parent,exit_triggered=True),book(),NOW))
    def test_offsets_across_bots_keep_quantities_and_cancel_pending_sells_fenced(self):
        a=entry(filled=3,remaining=0);b=entry(bot='bot-2',client_id='other',side='no',filled=2,remaining=0)
        self.assertEqual(offset_plan([a,b],{}, {'t':1},set()),({'low':2,'other':2},set()))
        high=dict(a,kind='exit',parent='low',client_id='high',filled=0,remaining=0,status='cancel_pending')
        self.assertEqual(offset_plan([a,b,high],{}, {'t':1},set()),({}, {'t'}))
        w=worker();w.orders=[a,b];self.assertFalse(w.profit_sell(a,book(),NOW))
    def test_late_fill_after_parking_claims_the_cycle_and_respects_repeat_off(self):
        w=worker();w.bots[0]['config']['cycle_repeat']=False
        w.states={'bot-1':{'t/0/yes':dict(cycle=1,submitted=False,first_at=NOW,attempt=1)}}
        late=entry(filled=3,remaining=0)
        w.restore_filled_cycle_claim(late)
        self.assertTrue(w.states['bot-1']['t/0/yes']['submitted'])
        late.update(status='closed',sold=3);w.rearm_cycle(late,NOW+1)
        self.assertTrue(w.states['bot-1']['t/0/yes']['submitted'])
    def test_shared_budget_still_limits_entries_and_diagnostics_name_the_blocker(self):
        w=worker();other=bot(cycle_buy_cents=6,cycle_sell_cents=9);other['id']='bot-2';w.bots.append(other)
        w.orders=[entry(quantity=100,remaining=100)]
        info=w.entry_diagnostics(NOW)['bot-2']
        self.assertEqual(info['entry_blockers'].get('budget'),2)
        self.assertIn('insufficient available funds or allocation',info['message'])
        w.orders=[entry(price=3,profit_target_cents=6,filled=3,remaining=0)]
        info=w.entry_diagnostics(NOW)['bot-2']
        self.assertEqual(info['entry_blockers'].get('self_trade'),1)
        self.assertEqual(info['entry_blockers'].get('opposite_inventory'),1)
        self.assertIn('would cross your own sell',info['message'])
    def test_protective_exit_parks_other_bots_bid_without_permanently_using_its_cycle(self):
        w=worker();parent=entry(filled=3,remaining=0,exit_triggered=True,exit_ceiling_cents=40)
        other=entry(bot='bot-2',client_id='other',price=6,profit_target_cents=9)
        b=bot(cycle_buy_cents=6,cycle_sell_cents=9);b['id']='bot-2';w.bots.append(b)
        w.orders=[parent,other];w.states={'bot-2':{'t/0/yes':dict(cycle=1,submitted=True,first_at=NOW)}};w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertFalse(w.states['bot-2']['t/0/yes']['submitted'])
        other.update(status='cancel_pending',remaining=0)
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.submit.assert_not_called()
        w.orders=[];w.bots[0]['desired']='paused'
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['bot'],'bot-2')

class ProfitSells(unittest.TestCase):
    def test_stale_quote_after_funding_does_not_starve_other_markets(self):
        w=worker();w.quotes['u']=book()
        def funded(*args):
            w.quotes['t']['at']=NOW-10
            return True
        w.funding.ensure.side_effect=funded
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['ticker'],'u')


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


class ThreeMinuteLowBidExpiry(unittest.TestCase):
    def test_three_minute_deadline_overrides_older_one_minute_buy_cutoff(self):
        from services.demo.cycles import buy_cancel_deadline,eligible
        b=bot(cycle_cutoff_minutes=1);q=book()
        self.assertTrue(eligible(b['config'],b['config']['squares'][0],q,NOW+719))
        self.assertFalse(eligible(b['config'],b['config']['squares'][0],q,NOW+720))
        older=entry(close=NOW+840,market_close_at=NOW+900)
        self.assertEqual(buy_cancel_deadline(older,q),NOW+720)
        w=worker();w.orders=[older];w.cancel=Mock();w.recovered=False
        w.quotes['t']['at']=NOW-100
        with patch('services.demo.runtime.time.time',return_value=NOW+719):w.trade()
        w.cancel.assert_not_called()
        with patch('services.demo.runtime.time.time',return_value=NOW+720):w.trade()
        self.assertEqual(w.cancel.call_count,1)
        self.assertEqual(w.cancel.call_args.args[0]['client_id'],'low')

    def test_cancel_priority_keeps_partially_filled_lot_and_profit_sell(self):
        w=worker();o=entry(filled=4,remaining=6,market_close_at=NOW+900)
        w.orders=[o];w.cancel=Mock();w.submit=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW+720):w.trade()
        w.cancel.assert_called_once()
        self.assertEqual(o['filled'],4)
        w.submit.assert_not_called()
        o.update(remaining=0,status='held')
        w.quotes['t']['at']=NOW+721;w.last_reconcile=NOW+721
        with patch('services.demo.runtime.time.time',return_value=NOW+721):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['kind'],'exit')
        self.assertEqual(w.submit.call_args.args[0]['exit_role'],'profit')
        self.assertEqual(w.submit.call_args.args[0]['quantity'],4)

    def test_cancel_is_fenced_if_exchange_status_is_uncertain(self):
        w=worker();o=entry(market_close_at=NOW+900,status='cancel_pending')
        w.orders=[o];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW+721):w.trade()
        w.cancel.assert_not_called()

    def test_native_exchange_expiration_is_three_minutes_even_when_new_buys_stop_earlier(self):
        w=worker();w.bots=[bot(cycle_cutoff_minutes=5)]
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        intent=w.submit.call_args.args[0]
        self.assertEqual(intent['close'],NOW+720)
        self.assertEqual(intent['market_close_at'],NOW+900)
        self.assertEqual(wire_order(intent)['expiration_time'],NOW+720)


class CrossBotCapitalFairness(unittest.TestCase):
    def test_least_funded_bots_come_before_second_bids_for_funded_bots(self):
        from services.demo.engine import fair_order_candidates
        items=[dict(bot=b,ticker=b) for b in ('large','empty','small')]
        self.assertEqual([p['bot'] for p in fair_order_candidates(items,'empty',{'large':4500,'empty':0,'small':300})],
                         ['empty','small','large'])

    def test_smaller_tranches_spread_initial_cash_across_28_bots(self):
        from services.demo.engine import cycle_tranche,fair_budget_config
        cfg=bot(bot_percent=100,bid_percent=100,market_percent=100)['config']
        self.assertAlmostEqual(cycle_tranche(cfg,28000,28),250)
        self.assertEqual(cycle_tranche(cfg,28000,1),28000)
        self.assertEqual(cycle_tranche(fair_budget_config(dict(cfg,bot_percent=1),28),28000,28),70)

    def test_small_verified_shard_cash_is_shared_instead_of_waiting_for_a_large_transfer(self):
        from services.demo.funding import ShardFunding
        w=worker();w.bots=[bot(bot_percent=100,bid_percent=100,market_percent=100),
                         bot(bot_percent=100,bid_percent=100,market_percent=100)]
        w.bots[1]['id']='bot-2'
        w.store.get=Mock(return_value=None);w.store.clear_alert=Mock()
        exchange=Mock();exchange.call.return_value=dict(subaccount_balances=[
            dict(subaccount_number=0,exchange_index=0,balance='5.00')])
        w.funding=ShardFunding(w.store,exchange)
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['quantity'],25)
        self.assertFalse(any(c.args[0]=='POST' for c in exchange.call.call_args_list))

    def test_oversized_unfilled_bid_is_released_without_selling_held_lots(self):
        w=worker();a=bot(bot_percent=100,bid_percent=100,market_percent=100)
        b=bot(bot_percent=100,bid_percent=100,market_percent=100);b['id']='bot-2'
        w.bots=[a,b]
        # The second bot has a fresh, unrelated market needing its first bid.
        w.quotes['other']=book();o=entry(quantity=400,remaining=400,price=10)
        w.orders=[o];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_called_once();self.assertEqual(w.cancel.call_args.args[0]['client_id'],'low')
        self.assertTrue(o['allocation_rearm']);w.submit.assert_not_called()
        w.states={o['bot']:{'t/0/yes':dict(cycle=1,submitted=True,attempt=0)}}
        w.rearm_allocation_cancel(o)
        self.assertTrue(w.states[o['bot']]['t/0/yes']['submitted'],'wait for terminal exchange evidence')
        o.update(status='closed',remaining=0,filled=1)
        w.rearm_allocation_cancel(o)
        self.assertTrue(w.states[o['bot']]['t/0/yes']['submitted'],'a cancellation race fill is retained')
        o['filled']=0;w.rearm_allocation_cancel(o)
        self.assertFalse(w.states[o['bot']]['t/0/yes']['submitted'])
        self.assertEqual(w.states[o['bot']]['t/0/yes']['attempt'],1)

    def test_equal_account_share_caps_28_bots_but_never_raises_user_limits(self):
        from services.demo.engine import fair_budget_config,quantity
        cfg=bot(bot_percent=100,bid_percent=100,market_percent=100)['config']
        fair=fair_budget_config(cfg,28)
        self.assertAlmostEqual(fair['bot_percent'],100/28)
        self.assertEqual(quantity(fair,3,10000,10000,0,0),119)
        self.assertEqual(quantity(fair,3,10000,10000,0,357),0)
        self.assertEqual(cfg['bot_percent'],100,'do not mutate saved preferences')
        strict=bot(bot_percent=2,bid_percent=100,market_percent=100)['config']
        self.assertEqual(fair_budget_config(strict,28)['bot_percent'],2)
        self.assertIs(fair_budget_config(cfg,1),cfg)

    def test_round_robin_prioritizes_different_bots_before_the_next_bid_of_one(self):
        from services.demo.engine import fair_order_candidates
        incoming=[
            dict(bot='A',ticker='A-1',first_at=1),
            dict(bot='A',ticker='A-2',first_at=2),
            dict(bot='B',ticker='B-1',first_at=1),
            dict(bot='C',ticker='C-1',first_at=1),
            dict(bot='A',ticker='A-3',first_at=3),
        ]
        self.assertEqual([x['ticker'] for x in fair_order_candidates(incoming)],
            ['A-1','B-1','C-1','A-2','A-3'])
        self.assertEqual([x['ticker'] for x in fair_order_candidates(incoming,'A')],
            ['B-1','C-1','A-1','A-2','A-3'])

    def test_live_scheduler_allocates_equally_and_posts_both_yes_no_sides(self):
        w=worker();w.bots=[]
        for i in range(4):
            b=bot(bot_percent=100,bid_percent=100,market_percent=100)
            b['id']=f'bot-{i}'
            w.bots.append(b)
        for _ in range(8):
            w.submit.reset_mock()
            with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
            self.assertTrue(w.submit.called)
            order=w.submit.call_args.args[0]
            self.assertEqual(order['kind'],'entry')
            order.update(status='resting',remaining=order['quantity'])
            w.orders.append(order)
        self.assertEqual([o['bot'] for o in w.orders],
            ['bot-0','bot-1','bot-2','bot-3']*2)
        for b in w.bots:
            own=[o for o in w.orders if o['bot']==b['id']]
            self.assertEqual({o['side'] for o in own},{'yes','no'})
            self.assertLessEqual(sum(o['quantity']*o['price'] for o in own),2500)
        self.assertLessEqual(sum(o['quantity']*o['price'] for o in w.orders),10000)

    def test_paused_bots_do_not_reserve_a_running_bots_share(self):
        from services.demo.engine import fair_budget_config
        w=worker();w.bots=[bot(),bot()]
        w.bots[0]['id']='running';w.bots[1]['id']='paused';w.bots[1]['desired']='paused'
        w.funding.waits={}
        info=w.entry_diagnostics(NOW)
        self.assertEqual(info['running']['running_allocation_peers'],1)
        self.assertEqual(info['running']['allocation_cap_cents'],1000)

    def test_ranked_normal_strategy_keeps_higher_expected_return_priority(self):
        w=worker()
        normal=dict(id='z-normal',revision=1,desired='running',config=config())
        normal['config']['squares'][0].update(min_minutes=0,max_minutes=15,expected_roi=10)
        low=bot();low['id']='a-low'
        w.bots=[low,normal]
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        self.assertEqual(w.submit.call_args.args[0]['bot'],'z-normal')

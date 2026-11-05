import unittest
from unittest.mock import Mock,patch
from services.api.tests.test_demo_cycles import worker,entry,NOW
from services.demo.engine import wire_order
from services.demo.late_exit import due,maker_price,needs_action
from services.demo.runtime import Worker
from services.demo.exchange import ExchangeFailure

def late_worker(side='yes',bid=30,ask=32,remaining_minutes=5):
    w=worker();w.bots[0]['config'].update(cycle_buy_cents=3,cycle_repeat=False,cycle_entry_minutes=5,cycle_exit_mode='late_threshold')
    p=entry(price=3,filled=10,remaining=0,side=side,cycle_exit_mode='late_threshold',late_exit_minutes=5,
        late_exit_threshold_cents=40,late_exit_reprice_cents=5,market_close_at=NOW+remaining_minutes*60)
    w.orders=[p];q=w.quotes['t'];q.update(open=NOW-600,close=p['market_close_at'],bid=bid if side=='yes' else 100-ask,ask=ask if side=='yes' else 100-bid)
    w.exchange=Mock(writes=0);return w,p,q

class LateExitTests(unittest.TestCase):
    def trade(self,w,now=NOW):
        with patch('services.demo.runtime.time.time',return_value=now):w.trade(allow_entries=False)
    def test_final_window_and_strict_threshold_boundaries_on_both_sides(self):
        for side in ('yes','no'):
            for bid,minutes,expected in [(39,5,True),(40,5,False),(50,1,False),(39,5.001,False),(0,5,True)]:
                with self.subTest(side=side,bid=bid,minutes=minutes):
                    w,p,q=late_worker(side,bid,bid+2,minutes);self.trade(w)
                    self.assertEqual(w.submit.called,expected)
                    if expected:
                        sale=w.submit.call_args.args[0];self.assertEqual(sale['price'],bid+1)
                        self.assertTrue(wire_order(sale)['post_only']);self.assertEqual(sale['quantity'],10)
                        self.assertEqual(sale['close'],q['close'])
    def test_initial_late_sell_is_due_without_a_new_stream_message(self):
        w,p,q=late_worker();self.assertTrue(w.urgent_exit_pending(NOW));self.trade(w)
        self.assertTrue(p['late_exit_triggered']);w.submit.assert_called_once()
    def test_no_profit_sell_or_urgent_busy_loop_before_final_window_or_above_threshold(self):
        for bid,minutes in [(3,10),(40,5),(80,2)]:
            w,p,q=late_worker(bid=bid,ask=bid+2,remaining_minutes=minutes)
            self.assertFalse(w.profit_sell(p,q,NOW));self.assertFalse(w.urgent_exit_pending(NOW));self.trade(w)
            w.submit.assert_not_called()
    def working_sale(self):
        w,p,q=late_worker();self.trade(w);sale=w.submit.call_args.args[0]
        sale.update(status='resting',remaining=10,exchange_id='remote');w.orders.append(sale);w.submit.reset_mock()
        w.cancel=Mock();return w,p,q,sale
    def test_gap_of_five_does_not_replace_but_six_does(self):
        w,p,q,sale=self.working_sale();q.update(bid=25,ask=27)
        self.trade(w);w.cancel.assert_not_called();w.submit.assert_not_called()
        q.update(bid=24,ask=26);self.trade(w);w.cancel.assert_called_once_with(sale,unittest.mock.ANY)
        self.assertEqual(p['late_exit_ceiling_cents'],25);w.submit.assert_not_called()
    def test_cancel_verification_precedes_replacement_and_partial_fills_reduce_quantity(self):
        w,p,q,sale=self.working_sale();w.cancel=Worker.cancel.__get__(w,Worker);q.update(bid=24,ask=26)
        self.trade(w);self.assertFalse(w.recovered);self.assertEqual(sale['status'],'cancel_pending');w.submit.assert_not_called()
        self.assertTrue(w.urgent_exit_pending(NOW))
        self.trade(w);w.submit.assert_not_called()
        # The exchange confirms three fills and cancellation of the remainder.
        sale.update(status='closed',filled=3);p['sold']=3;w.recovered=True;w.last_reconcile=NOW;q.update(bid=20,ask=22)
        self.trade(w);replacement=w.submit.call_args.args[0]
        self.assertEqual((replacement['price'],replacement['quantity']),(21,7))
        self.assertNotEqual(replacement['client_id'],sale['client_id'])
    def test_prices_never_rise_and_trigger_remains_latched_after_recovery(self):
        w,p,q,sale=self.working_sale();q.update(bid=42,ask=44)
        self.trade(w);w.cancel.assert_not_called();w.submit.assert_not_called();self.assertEqual(p['late_exit_ceiling_cents'],31)
        sale.update(status='closed',remaining=0);self.trade(w);w.submit.assert_not_called()
        q.update(bid=29,ask=31);self.trade(w);self.assertEqual(w.submit.call_args.args[0]['price'],30)
    def test_stale_unverified_or_closed_market_cannot_authorize_an_exit(self):
        for change in [dict(at=NOW-6),dict(book_verified=False),dict(status='closed'),dict(close=NOW),dict(price_grid_refresh=True)]:
            w,p,q=late_worker();q.update(change);self.trade(w);w.submit.assert_not_called()
    def test_missing_or_ambiguous_child_cannot_duplicate_sell(self):
        for status in ('intent','uncertain','cancel_pending'):
            w,p,q,sale=self.working_sale();sale['status']=status;q.update(bid=5,ask=7)
            self.trade(w);w.cancel.assert_not_called();w.submit.assert_not_called()
    def test_grid_rounding_valid_for_yes_and_no_with_full_cent_offset(self):
        for side in ('yes','no'):
            w,p,q=late_worker(side,bid=20.3,ask=22)
            q['price_ranges']=[dict(start='0',end='1',step='.005')]
            self.assertEqual(maker_price(p,q),21.5)
    def test_rejected_exit_uses_fresh_book_and_new_id_without_raising_limit(self):
        w,p,q=late_worker();w.submit=Worker.submit.__get__(w,Worker)
        w.exchange.submit.side_effect=ExchangeFailure('exchange_rejected',False,status=400,reason='post_only')
        self.trade(w);self.assertEqual(p['late_exit_ceiling_cents'],31)
        first=w.exchange.submit.call_args.args[0]['client_id'];self.trade(w);self.assertEqual(w.exchange.submit.call_count,1)
        q.update(clock=2,seq=2,at=NOW+1,bid=28,ask=30)
        self.trade(w,NOW+1);self.assertNotEqual(w.exchange.submit.call_args.args[0]['client_id'],first)
        self.assertEqual(w.exchange.submit.call_args.args[0]['price'],29)
    def test_unconfirmed_account_never_sends_initial_sale(self):
        w,p,q=late_worker();w.recovered=False;self.trade(w);w.submit.assert_not_called()
    def test_ambiguous_sell_is_not_replayed_and_blocks_only_its_market(self):
        w,p,q=late_worker();w.submit=Worker.submit.__get__(w,Worker)
        w.exchange.submit.side_effect=ExchangeFailure('connection',True)
        with self.assertRaises(ExchangeFailure):self.trade(w)
        self.assertIn('t',w.blocked);self.assertFalse(w.recovered)
        self.trade(w);self.assertEqual(w.exchange.submit.call_count,1)
    def test_new_buys_keep_three_cent_price_and_native_five_minute_expiration(self):
        w=worker();w.bots[0]['config'].update(cycle_buy_cents=3,cycle_repeat=False,cycle_entry_minutes=5,cycle_exit_mode='late_threshold')
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        buy=w.submit.call_args.args[0]
        self.assertEqual((buy['price'],buy['cycle_exit_mode']),(3,'late_threshold'))
        self.assertEqual(buy['close'],w.quotes['t']['open']+300)
    def test_inactive_entry_market_does_not_prevent_a_held_position_exit(self):
        w,p,q=late_worker();w.bots[0]['config']['require_active_market']=True
        w.market_inactive[q['series']]=dict(reason='No external liquidity',retry_at=NOW+60)
        self.trade(w);w.submit.assert_called_once()
    def test_old_profit_sell_is_canceled_when_open_inventory_adopts_hold_policy(self):
        w,p,q=late_worker(remaining_minutes=10)
        w.orders.append(dict(client_id='old-profit',kind='exit',exit_role='profit',parent=p['client_id'],bot=p['bot'],ticker='t',side='yes',price=6,status='resting',remaining=10,filled=0))
        w.cancel=Mock();self.trade(w)
        w.cancel.assert_called_once();w.submit.assert_not_called()
